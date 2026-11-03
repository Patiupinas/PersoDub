"""Seed a fresh A4-selected Overdub job from a completed local dubbing.

Only immutable source inputs and successful pre-voice stage caches are copied.
The original work folder and its Qwen lines are never modified or re-used.
"""
import json
import os
import shutil
from pathlib import Path

from app.audio.overdub import OverdubError, OverdubLevels
from app.dub_script import script_path
from app.text.srt import parse_srt
from app.vocal_overdub_review import record_plan

STAGES = ("separated.json", "transcript.json")
SOURCE_SRT = "original.srt"


def source_inputs(work_dir):
    """Resolve the existing local stage outputs before creating any new job."""
    work = Path(work_dir).resolve()
    paths = {}
    for filename in ("input.mp4", SOURCE_SRT, *STAGES):
        source = work / filename
        if not source.is_file() or source.resolve().parent != work:
            raise OverdubError(f"Source project is missing its {filename} stage cache")
        paths[filename] = source

    current_script = Path(script_path(str(work)))
    if not current_script.is_file() or current_script.resolve().parent != work:
        raise OverdubError("Source project is missing its translated script")
    try:
        if not parse_srt(current_script.read_text(encoding="utf-8-sig")):
            raise OverdubError("Source project has no translated speech cues")
        if not parse_srt(paths[SOURCE_SRT].read_text(encoding="utf-8-sig")):
            raise OverdubError("Source project has no original speech cues")
        separated = json.loads(paths["separated.json"].read_text(encoding="utf-8"))
        transcript = json.loads(paths["transcript.json"].read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, TypeError, KeyError) as error:
        raise OverdubError("Source project stage cache is not readable") from error

    if not isinstance(transcript, dict) or not isinstance(transcript.get("cues"), list) or not transcript["cues"]:
        raise OverdubError("Source project has no reusable transcript")
    if not isinstance(separated, dict):
        raise OverdubError("Source project has no reusable separation")
    for kind in ("vocals", "background"):
        name = separated.get(kind)
        if (not isinstance(name, str) or not name or name != os.path.basename(name)
                or name in paths or name in ("sub.srt", "source.srt")
                or (work / name).resolve().parent != work
                or not (work / name).is_file() or (work / name).stat().st_size <= 44):
            raise OverdubError(f"Source project is missing its {kind} audio cache")
        paths[name] = work / name
    paths["sub.srt"] = current_script
    paths["source.srt"] = paths[SOURCE_SRT]
    return paths


def seed_regeneration(inputs, new_work, plan, levels):
    """Write a new, isolated source snapshot; do not copy any qwen_line WAVs."""
    dest = Path(new_work)
    if not dest.is_dir() or list(dest.iterdir()):
        raise OverdubError("Selective Overdub requires a new empty job directory")
    if type(levels) is not OverdubLevels:
        raise OverdubError("Unknown Overdub gain profile")
    for name, source in inputs.items():
        if name == SOURCE_SRT:
            continue
        shutil.copyfile(source, dest / name)
    record_plan(dest / "overdub_events.json", plan)
    with (dest / "overdub_levels.json").open("x", encoding="utf-8") as f:
        json.dump({
            "original_speech_db": levels.speech_original_db,
            "dub_speech_db": levels.speech_dub_db,
            "fade_ms": levels.fade_ms,
        }, f)
        f.write("\n")
