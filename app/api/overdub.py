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
from app.api import _launch as launch_api
from app.api._launch import check_space, job_dir, launch_job
from app.api._shared import free_path, work_dir_of
from app.audio.overdub import (
    OverdubError,
    OverdubLevels,
    _parse_plan,
    extract_original_pcm,
    select_translatable_cues,
)
from app.dub_script import script_path
from app.jobs import JobKind, JobStatus, kind_of
from app.text.srt import parse_srt
from app.vocal_overdub_export import _line_manifest, export_existing
from app.vocal_overdub_regenerate import seed_regeneration, source_inputs
from app.vocal_overdub_review import (
    ReviewDraftConflict,
    approved_plan,
    model_suggestions,
    read_review_draft,
    record_plan,
    save_review_draft,
    transcript_suggestions,
)

router = APIRouter()
logger = logging.getLogger("persodub.api.overdub")
_EXPORT_LOCK = threading.Lock()
_DRAFT_LOCK = threading.Lock()
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


class DraftRequest(BaseModel):
    source_wav_sha256: str
    total_frames: int
    expected_revision: str | None = None
    events: list[dict]
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


def _review_text_cues(path, work):
    """Local-only transcript context is advisory, never a source A4 label."""
    path = Path(path)
    if not path.is_file() or path.resolve().parent != Path(work).resolve():
        return []
    return [
        {"start": cue["start"], "end": cue["end"], "text": cue.get("text", "")}
        for cue in parse_srt(path.read_text(encoding="utf-8-sig"))
    ]


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
        source_cues = _review_text_cues(work / "original.srt", work)
        translated_cues = _review_text_cues(script_path(str(work)), work)
        if suggestions is None:
            suggestions = transcript_suggestions(
                frames, [(cue["start"], cue["end"]) for cue in source_cues]
            )
        with _DRAFT_LOCK:
            draft, revision = read_review_draft(work)
        stale = bool(draft and (
            draft["source_wav_sha256"] != source_sha
            or draft["total_frames"] != frames
        ))
        return {
            "source_wav_sha256": source_sha, "total_frames": frames,
            "sample_rate": 48000, "suggestions": suggestions,
            "source_cues": source_cues, "translated_cues": translated_cues,
            "analysis": analysis, "ast_available": configured,
            "requires_review": True,
            "review_draft": None if stale else draft,
            "draft_revision": revision, "draft_stale": stale,
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


@router.post("/api/dub/jobs/{jid}/overdub/draft")
def overdub_save_draft(jid: str, request: DraftRequest):
    """Store only unapproved review progress, never an authorized export plan."""
    source, work = _job(jid)
    try:
        current = _source_preview(source, work, analyze=False)
        if (current["source_wav_sha256"] != request.source_wav_sha256
                or current["total_frames"] != request.total_frames):
            raise OverdubError("Review draft does not match the current source audio")
        draft = {
            "schema_version": 1,
            "source_wav_sha256": request.source_wav_sha256,
            "total_frames": request.total_frames,
            "events": request.events,
            "original_speech_db": request.original_speech_db,
            "dub_speech_db": request.dub_speech_db,
            "fade_ms": request.fade_ms,
            "review_confirmed": False,
        }
        with _DRAFT_LOCK:
            revision = save_review_draft(work, draft, request.expected_revision)
        return {"saved": True, "revision": revision, "review_confirmed": False}
    except ReviewDraftConflict as error:
        raise HTTPException(409, str(error)) from error
    except (OverdubError, OSError, ValueError) as error:
        raise HTTPException(422, str(error)[:180]) from error


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


def _require_selected_voice_engine(count):
    """Only voice synthesis is needed: the source, ASR and translation are cached."""
    if count == 0:
        return
    from app.api import dub as dub_api

    missing = launch_api.missing_models(
        False, None, need_engine=True, separation_local=False,
    )
    if missing:
        launch_api.raise_models_needed(missing)
    dub_api._require_voice_engine_running()


@router.post("/api/dub/jobs/{jid}/overdub/regenerate")
def overdub_regenerate(jid: str, request: ExportRequest):
    """Start an independent selective-TTS job from the approved original A4 plan.

    Unlike export, this does not reuse any old qwen_line_N.wav. It copies
    only the source, cached separation/transcript and complete editable script
    into a fresh job. The normal JobStore queue owns the expensive synthesis,
    cancellation, resume and progress.
    """
    source, work = _job(jid)
    if request.review_confirmed is not True:
        raise HTTPException(422, "Confirm the reviewed event decisions before regenerating")
    try:
        levels = OverdubLevels(
            request.original_speech_db, request.dub_speech_db, request.fade_ms,
        )
        # Reject obsolete or incomplete source caches before making a project.
        try:
            inputs = source_inputs(work)
        except OverdubError as error:
            raise HTTPException(409, str(error)[:180]) from error
        seconds = media.video_duration(str(source))
        _check_export_room(source, work, seconds)
        current = _source_preview(source, work, analyze=False)
        if request.source_wav_sha256 != current["source_wav_sha256"] or (
            request.total_frames != current["total_frames"]
        ):
            raise OverdubError("The source audio has changed since review")
        plan = approved_plan(
            current["total_frames"], current["source_wav_sha256"], request.events
        )
        cues = parse_srt(inputs["sub.srt"].read_text(encoding="utf-8-sig"))
        spans = _parse_plan(plan, current["total_frames"], current["source_wav_sha256"])
        selected, skipped = select_translatable_cues(cues, spans)
        if selected:
            _require_selected_voice_engine(len(selected))
        check_space(state.WORKSPACE)

        # Allocate and stage atomically with respect to other Overdub exports.
        # No existing video, plan or line WAV is ever replaced.
        with _EXPORT_LOCK:
            from app.api import dub as dub_api

            original_job = state.job_store.get(jid)
            project = original_job.get("project") or work.name
            title = project + " Overdub"
            new_work = Path(job_dir(title, original_job.get("language_code") or "ru"))
            try:
                seed_regeneration(inputs, new_work, plan, levels)
            except Exception:
                shutil.rmtree(new_work)
                raise
            fields = {
                "project": title,
                "title": title,
                "day": launch_api.today(),
                "from_link": False,
                "work_dir": str(new_work),
                "language": original_job.get("language") or "Russian",
                "language_code": original_job.get("language_code") or "ru",
                "source_lang": original_job.get("source_lang"),
                "dub_mode": "local",
                "audio_mode": "overdub",
                "overdub_source_job": jid,
                "stt_engine": original_job.get("stt_engine") or "whisper",
                "translator": original_job.get("translator"),
                "translator_model": original_job.get("translator_model"),
                "tts": original_job.get("tts") or "qwen3",
                "quality": original_job.get("quality"),
                "separation": original_job.get("separation") or "demucs",
            }

            def _target(new_jid, log):
                return dub_api._work_for(fields, new_jid, resume=True)(log)

            new_jid = launch_job(
                str(new_work), fields, "Rebuilding reviewed Overdub speech from cached source",
                _target,
            )
        return {
            "job_id": new_jid, "approved_for_tts": len(selected),
            "source_only": skipped,
            "status_url": f"/api/dub/jobs/{new_jid}",
        }
    except HTTPException:
        raise
    except (OverdubError, OSError, ValueError, RuntimeError) as error:
        logger.info("Selective Overdub refused: %s", type(error).__name__)
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
