"""Local finished-project Overdub review and export.

Only explicit user-reviewed actions are given to the mixer. AST predictions
are separately labelled observations; neither STT nor AST grants A4 permission.
"""
import hashlib
import json
import logging
import math
import re
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import media, settings_env, state
from app.api._shared import free_path, work_dir_of
from app.audio.overdub import OverdubError, OverdubLevels, extract_original_pcm
from app.jobs import JobKind, JobStatus, kind_of
from app.text.srt import parse_srt
from app.vocal_overdub_export import _line_manifest, export_existing
from app.vocal_overdub_review import (
    approved_plan,
    model_suggestions,
    record_plan,
    transcript_suggestions,
)

router = APIRouter()
logger = logging.getLogger("persodub.api.overdub")
_EXPORT_LOCK = threading.Lock()
_FILE_RE = re.compile(r"^finished-overdub(?:-[0-9]+)?\.mp4$")
PCM_BYTES_PER_SECOND = 48000 * 2 * 2
# Keep a margin for RIFF metadata (WAV length fields are 32-bit unsigned).
MAX_RIFF_PCM_BYTES = (1 << 32) - (1 << 20)
AST_MIN_TIMEOUT_SECONDS = 900.0
AST_MAX_TIMEOUT_SECONDS = 12 * 3600.0


def _audio_size(duration):
    """Estimate a complete stereo source PCM allocation without decoding it."""
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        raise OverdubError("Cannot determine the original video duration")
    required = math.ceil(duration * PCM_BYTES_PER_SECOND)
    if required > MAX_RIFF_PCM_BYTES:
        raise OverdubError(
            "This recording exceeds the single-WAV export limit; "
            "segmented long-form Overdub export is required"
        )
    return required


def _check_export_room(source, work, duration):
    """Budget for four decoded WAVs and two temporary video copies."""
    pcm = _audio_size(duration)
    needed = pcm * 4 + source.stat().st_size * 2 + 256 * 1024 * 1024
    if shutil.disk_usage(work).free < needed:
        raise OverdubError("Not enough free disk space for the Overdub export")


def _ast_timeout(duration):
    """Allow long-form analysis to scale beyond the former fixed 900s limit."""
    return max(AST_MIN_TIMEOUT_SECONDS, min(AST_MAX_TIMEOUT_SECONDS, duration * 4))


class PreviewRequest(BaseModel):
    analyze: bool = False


class ExportRequest(BaseModel):
    source_wav_sha256: str
    total_frames: int
    events: list[dict]
    review_confirmed: bool = False
    original_speech_db: float = -16.0
    dub_speech_db: float = -2.0
    fade_ms: float = 300.0


def _job(jid):
    job = state.job_store.get(jid)
    if job is None:
        raise HTTPException(404, "Unknown project")
    if kind_of(job) != JobKind.DUB or job.get("status") != JobStatus.DONE:
        raise HTTPException(409, "Overdub requires a completed dubbing project")
    if job.get("dub_mode") == "perso":
        raise HTTPException(409, "Overdub re-export supports local Qwen dubbing only")
    work = Path(work_dir_of(job)).resolve()
    source = work / "input.mp4"
    if not source.is_file() or not (work / "lines.json").is_file():
        raise HTTPException(409, "Original video or synthesized lines are not available")
    try:
        _line_manifest(work)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "Saved Qwen voice lines are unavailable") from exc
    return source, work


def _source_preview(source, work, analyze=False):
    """Decode the current cut from source each time; never trust stale plan WAV."""
    with tempfile.TemporaryDirectory(prefix="overdub-preview-", dir=str(work)) as scratch:
        wav = Path(scratch) / "source.wav"
        duration = media.video_duration(str(source))
        _audio_size(duration)
        extract_original_pcm(source, wav, duration=duration)
        with wave.open(str(wav), "rb") as f:
            frames = f.getnframes()
        digest = hashlib.sha256()
        with wav.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        source_sha = digest.hexdigest()
        suggestions = None
        analysis = "not_requested"
        # Desktop kit.env is the live settings authority; ordinary process
        # environment remains the fallback for standalone server deployments.
        python = settings_env.current_value("PERSODUB_AST_PYTHON")
        model = settings_env.current_value("PERSODUB_AST_MODEL_DIR")
        configured = bool(python and model and Path(python).is_file() and Path(model).is_dir())
        if analyze and configured:
            observed_path = Path(scratch) / "ast.json"
            try:
                subprocess.run(
                    [python, "-m", "app.scripts.ast_overdub_observer",
                     "--original", str(wav), "--model-dir", model,
                     "--output", str(observed_path)],
                    cwd=str(Path(__file__).resolve().parents[2]),
                    check=True, timeout=_ast_timeout(duration), capture_output=True, text=True,
                )
                observed = json.loads(observed_path.read_text(encoding="utf-8"))
                suggestions = model_suggestions(frames, source_sha, observed)
                analysis = "ast_observations"
            except (subprocess.SubprocessError, ValueError, OSError, OverdubError) as error:
                logger.info("AST observer could not run: %s", type(error).__name__)
                analysis = "model_failed"
        elif analyze:
            analysis = "model_not_configured"
        if suggestions is None:
            cues = []
            script = work / "original.srt"
            if script.is_file():
                for cue in parse_srt(script.read_text(encoding="utf-8-sig")):
                    cues.append((cue["start"], cue["end"]))
            suggestions = transcript_suggestions(frames, cues)
        return {
            "source_wav_sha256": source_sha, "total_frames": frames,
            "sample_rate": 48000, "suggestions": suggestions,
            "analysis": analysis, "ast_available": configured,
            "requires_review": True,
        }


@router.get("/api/dub/jobs/{jid}/overdub/source")
def overdub_original_source(jid: str):
    """Stream only the exact original source video for manual A4 listening.

    The existing results/download endpoint suggests an attachment filename;
    explicit inline response lets the native video player seek to an event.
    It never serves translated audio, a work-folder path, or generated media.
    """
    source, _ = _job(jid)
    return FileResponse(
        source, media_type="video/mp4", content_disposition_type="inline",
    )


@router.post("/api/dub/jobs/{jid}/overdub/prepare")
def overdub_prepare(jid: str, request: PreviewRequest):
    source, work = _job(jid)
    try:
        return _source_preview(source, work, request.analyze)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, OverdubError) as error:
        logger.info("Overdub preview failed: %s", type(error).__name__)
        raise HTTPException(422, "Could not prepare original audio for overdub") from error


@router.post("/api/dub/jobs/{jid}/overdub/export")
def overdub_export(jid: str, request: ExportRequest):
    source, work = _job(jid)
    if request.review_confirmed is not True:
        raise HTTPException(422, "Confirm the reviewed event decisions before exporting")
    try:
        profile = OverdubLevels(
            request.original_speech_db, request.dub_speech_db, request.fade_ms
        )
        # Long-form jobs need room for several audio and container copies
        # before the first potentially multi-hour decode begins.
        _check_export_room(source, work, media.video_duration(str(source)))
        # Re-read the source exactly before allowing any new rendered artifact.
        current = _source_preview(source, work, analyze=False)
        if request.source_wav_sha256 != current["source_wav_sha256"] or (
            request.total_frames != current["total_frames"]
        ):
            raise OverdubError("The source audio has changed since review")
        plan = approved_plan(
            current["total_frames"], current["source_wav_sha256"], request.events
        )
        with _EXPORT_LOCK:
            plan_path = Path(free_path(str(work / "overdub-approved"), ".json"))
            record_plan(plan_path, plan)
            output = Path(free_path(str(work / "finished-overdub"), ".mp4"))
            try:
                receipt = export_existing(source, work, plan_path, output, levels=profile)
            except Exception:
                plan_path.unlink(missing_ok=True)
                raise
        return {
            "file": output.name,
            "download_url": f"/api/dub/jobs/{jid}/overdub/files/{output.name}",
            "receipt": receipt,
        }
    except (OverdubError, OSError, ValueError, RuntimeError) as error:
        logger.info("Overdub export rejected: %s", type(error).__name__)
        raise HTTPException(422, str(error)[:180]) from error


@router.get("/api/dub/jobs/{jid}/overdub/files/{name}")
def overdub_file(jid: str, name: str):
    _, work = _job(jid)
    if not _FILE_RE.fullmatch(name):
        raise HTTPException(404, "Unknown Overdub file")
    file_path = (work / name).resolve()
    if file_path.parent != work or not file_path.is_file():
        raise HTTPException(404, "Overdub export not found")
    return FileResponse(file_path, media_type="video/mp4", filename=name)
