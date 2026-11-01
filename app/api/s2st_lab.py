"""Opt-in, bounded S2ST research API for existing completed local projects.

The regular Qwen pipeline and approved Overdub plans are not modified.
The heavyweight model always runs in its own interpreter, never in FastAPI.
"""
import hashlib
import io
import json
import logging
import math
import os
import re
import subprocess
import sys
import threading
import uuid
import wave
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, StrictInt

from app import settings_env, state
from app.api._shared import work_dir_of
from app.jobs import JobKind, JobStatus, kind_of

router = APIRouter()
logger = logging.getLogger("persodub.api.s2st_lab")
_START_LOCK = threading.Lock()
_RUNNING = {}
RUN_ID_RE = re.compile(r"^[a-f0-9]{12}$")
MEDIA_NAME_RE = re.compile(r"^(source|ru)-([0-9]{3,9})\.wav$|^preview-([0-9]{3,9})\.mp4$")
PAGE_SIZE = 50
MAX_CLIPS_PER_RUN = 6
MAX_CLIP_SECONDS = 30.0


class StartRequest(BaseModel):
    indices: List[StrictInt]
    source_token: str
    speech_review_confirmed: bool = False


def _job(jid):
    job = state.job_store.get(jid)
    if job is None:
        raise HTTPException(404, "Unknown project")
    if kind_of(job) != JobKind.DUB or job.get("status") != JobStatus.DONE:
        raise HTTPException(409, "S2ST lab requires a completed dubbing project")
    if job.get("dub_mode") == "perso":
        raise HTTPException(409, "S2ST lab requires the original local project")
    work = Path(work_dir_of(job)).resolve()
    if not (work / "input.mp4").is_file() or not (work / "speakers.json").is_file():
        raise HTTPException(409, "Original video or source speech cues are unavailable")
    return work


def _source(work):
    path = work / "input.mp4"
    cues_path = work / "speakers.json"
    try:
        cues_raw = cues_path.read_bytes()
        cues = json.loads(cues_raw.decode("utf-8"))
        if type(cues) is not list or not cues:
            raise ValueError("No source speech cues")
        video = path.stat()
        digest = hashlib.sha256()
        digest.update(cues_raw)
        digest.update(("%d:%d" % (video.st_size, video.st_mtime_ns)).encode())
    except (OSError, ValueError, UnicodeError) as exc:
        raise HTTPException(409, "Could not load original speech intervals") from exc
    return cues, digest.hexdigest()


def _model_configuration():
    """Prefer kit.env/process overrides, otherwise discover the local lab kit."""
    home = Path.home() / ".persodub-dev-kit"
    python = settings_env.current_value("PERSODUB_S2ST_PYTHON") or str(
        home / "research" / "seamless-m4t-v2" / "venv" / "bin" / "python"
    )
    model = settings_env.current_value("PERSODUB_S2ST_MODEL_DIR") or str(
        home / "models" / "seamless-m4t-v2-large"
    )
    exe = Path(python).expanduser()
    root = Path(model).expanduser()
    ready = exe.is_file() and root.is_dir()
    if ready:
        try:
            with (root / "config.json").open(encoding="utf-8") as stream:
                ready = json.load(stream).get("model_type") == "seamless_m4t_v2"
            ready = ready and all(
                (root / name).stat().st_size > 0 for name in (
                    "model-00001-of-00002.safetensors",
                    "model-00002-of-00002.safetensors",
                    "model.safetensors.index.json",
                )
            )
        except (OSError, ValueError, TypeError):
            ready = False
    return {"available": bool(ready), "python": str(exe), "model_dir": str(root)}


def _lab_root(work):
    return work / "s2st-lab"


def _latest(work):
    path = _lab_root(work) / "latest.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if type(value) is not dict or not RUN_ID_RE.fullmatch(value.get("run_id", "")):
            return None
        return value
    except (OSError, ValueError, TypeError):
        return None


def _atomic_json(path, value):
    pending = path.with_suffix(path.suffix + ".part")
    with pending.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)


def _read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _run_status(work):
    latest = _latest(work)
    if not latest:
        return None
    run_id = latest["run_id"]
    run_dir = _lab_root(work) / run_id
    data = run_dir / "data"
    finished = _read_json(run_dir / "worker-state.json")
    progress = _read_json(data / "progress.json")
    if finished and finished.get("state") in ("done", "error"):
        status = finished["state"]
    else:
        proc = _RUNNING.get(run_id)
        active = proc.poll() is None if proc is not None else _alive(latest.get("pid"))
        status = "running" if active else "error"
    results = []
    qa = _read_json(data / "quality-triage.json")
    if qa and isinstance(qa.get("cases"), list):
        for case in qa["cases"]:
            row = dict(case)
            index = row.get("index")
            if type(index) is not int:
                continue
            prefix = "/api/dub/jobs/%s/s2st/files/%s/" % (latest["jid"], run_id)
            for name, kind in (
                ("source-%03d.wav" % index, "original_audio_url"),
                ("ru-%03d.wav" % index, "russian_audio_url"),
                ("preview-%03d.mp4" % index, "preview_video_url"),
            ):
                if (data / name).is_file():
                    row[kind] = prefix + name
            results.append(row)
    return {
        "run_id": run_id, "status": status,
        "progress": progress if isinstance(progress, dict) else None,
        "results": results,
        "error": (finished or {}).get("error_type") if status == "error" else None,
    }


@router.get("/api/dub/jobs/{jid}/s2st")
def s2st_info(jid: str, page: int = 0):
    work = _job(jid)
    cues, token = _source(work)
    if page < 0 or page > (len(cues) - 1) // PAGE_SIZE:
        raise HTTPException(422, "Speech cue page is out of range")
    visible = []
    for i in range(page * PAGE_SIZE, min((page + 1) * PAGE_SIZE, len(cues))):
        cue = cues[i]
        if not isinstance(cue, dict):
            continue
        start, end = cue.get("start"), cue.get("end")
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end)):
            continue
        visible.append({
            "index": i, "start": start, "end": end,
            "speaker": str(cue.get("speaker", "unknown"))[:48],
            "selectable": 0 < end - start <= MAX_CLIP_SECONDS and start >= 0,
        })
    return {
        "source_token": token, "page": page, "page_size": PAGE_SIZE,
        "total_cues": len(cues), "max_clips": MAX_CLIPS_PER_RUN,
        "model_available": _model_configuration()["available"],
        "cues": visible, "run": _run_status(work),
    }


@router.get("/api/dub/jobs/{jid}/s2st/source/{index}")
def s2st_source_audio(jid: str, index: int, source_token: str):
    """Let the user actually hear each original cue before approving speech."""
    work = _job(jid)
    cues, token = _source(work)
    if source_token != token:
        raise HTTPException(409, "The original source has changed since review")
    if index < 0 or index >= len(cues):
        raise HTTPException(404, "Unknown source speech interval")
    cue = cues[index]
    if not isinstance(cue, dict):
        raise HTTPException(422, "Invalid speech interval")
    start, end = cue.get("start"), cue.get("end")
    if (type(start) not in (int, float) or type(end) not in (int, float)
            or not all(math.isfinite(x) for x in (start, end))
            or start < 0 or not 0 < end - start <= MAX_CLIP_SECONDS):
        raise HTTPException(422, "Speech interval is too long or invalid")
    try:
        decoded = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error",
             "-ss", "%.6f" % start, "-i", str(work / "input.mp4"),
             "-t", "%.6f" % (end - start), "-map", "0:a:0", "-vn",
             "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
             "-f", "s16le", "pipe:1"],
            capture_output=True, check=True, timeout=90,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.info("Original S2ST source preview unavailable: %s", type(exc).__name__)
        raise HTTPException(422, "Could not decode original speech") from exc
    if (not decoded.stdout or len(decoded.stdout) > MAX_CLIP_SECONDS * 16000 * 2
            or len(decoded.stdout) % 2):
        raise HTTPException(422, "Original speech preview is outside 30-second limits")
    # FFmpeg cannot know RIFF lengths when writing WAV to stdout. Encode
    # bounded raw PCM first, then stamp the exact frame count in the header.
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(decoded.stdout)
    return Response(output.getvalue(), media_type="audio/wav",
                    headers={"Cache-Control": "no-store"})


@router.get("/api/dub/jobs/{jid}/s2st/status")
def s2st_status(jid: str):
    return {"run": _run_status(_job(jid))}


@router.post("/api/dub/jobs/{jid}/s2st/start")
def s2st_start(jid: str, request: StartRequest):
    work = _job(jid)
    if request.speech_review_confirmed is not True:
        raise HTTPException(422, "Confirm that all chosen intervals contain only speech")
    indices = request.indices
    if (not indices or len(indices) > MAX_CLIPS_PER_RUN
            or len(indices) != len(set(indices))):
        raise HTTPException(422, "Select 1 to 6 distinct speech intervals")
    cues, token = _source(work)
    if token != request.source_token:
        raise HTTPException(409, "The source cues or video changed since review")
    for index in indices:
        if index < 0 or index >= len(cues):
            raise HTTPException(422, "Source speech interval is out of range")
        cue = cues[index]
        if type(cue) is not dict:
            raise HTTPException(422, "Invalid source speech interval")
        a, b = cue.get("start"), cue.get("end")
        if (type(a) not in (int, float) or type(b) not in (int, float)
                or not all(math.isfinite(x) for x in (a, b))
                or a < 0 or not 0 < b - a <= MAX_CLIP_SECONDS):
            raise HTTPException(422, "Selected speech interval is not a bounded speech segment")
    model = _model_configuration()
    if not model["available"]:
        raise HTTPException(409, "Local SeamlessM4T v2 weights or Python runtime are not configured")
    with _START_LOCK:
        previous = _run_status(work)
        if previous and previous["status"] == "running":
            raise HTTPException(409, "An S2ST experiment is already running")
        if any(proc.poll() is None for proc in _RUNNING.values()):
            raise HTTPException(409, "Another S2ST model run is using this computer")
        root = _lab_root(work)
        root.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4().hex[:12]
        folder = root / run_id
        folder.mkdir(exist_ok=False)
        command = [
            model["python"], "-u", "-m", "app.experimental.s2st_lab_worker",
            "--job-dir", str(work),
            "--indices", ",".join(str(x) for x in indices),
            "--experiment-dir", str(folder / "data"),
            "--model-dir", model["model_dir"],
            "--device", "mps" if sys.platform == "darwin" else "cpu",
        ]
        environment = dict(os.environ)
        environment["HF_HUB_OFFLINE"] = "1"
        environment["TRANSFORMERS_OFFLINE"] = "1"
        environment["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
        log = folder / "worker.log"
        try:
            with log.open("x", encoding="utf-8") as output:
                process = subprocess.Popen(
                    command, cwd=str(Path(__file__).resolve().parents[2]),
                    env=environment, stdout=output, stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            _RUNNING[run_id] = process
            _atomic_json(root / "latest.json", {
                "run_id": run_id, "pid": process.pid, "jid": jid,
            })
        except (OSError, ValueError) as exc:
            if "process" in locals():
                process.terminate()
            raise HTTPException(503, "Could not start the local S2ST engine") from exc
    return {"run_id": run_id, "status": "running"}


@router.get("/api/dub/jobs/{jid}/s2st/files/{run_id}/{name}")
def s2st_files(jid: str, run_id: str, name: str):
    work = _job(jid)
    if not RUN_ID_RE.fullmatch(run_id):
        raise HTTPException(404, "Unknown S2ST experiment")
    match = MEDIA_NAME_RE.fullmatch(name)
    if not match:
        raise HTTPException(404, "Unknown S2ST result")
    folder = (_lab_root(work) / run_id).resolve()
    if folder.parent != _lab_root(work).resolve():
        raise HTTPException(404, "Unknown S2ST experiment")
    data = folder / "data"
    plan = _read_json(data / "plan.json")
    index = int(match.group(2) or match.group(3))
    if not plan or index not in [e.get("index") for e in plan.get("entries", [])]:
        raise HTTPException(404, "Source segment is not in this experiment")
    path = (data / name).resolve()
    if path.parent != data or not path.is_file():
        raise HTTPException(404, "Experiment result is not available")
    return FileResponse(path, media_type="video/mp4" if name.endswith(".mp4") else "audio/wav")
