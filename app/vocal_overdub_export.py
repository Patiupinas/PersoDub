"""Re-export an existing PersoDub job as a selectable two-track overdub MP4.

The operation reuses the original video's soundtrack and previously synthesized
Qwen line WAVs. It does not run speech recognition, translation or TTS.
"""
import argparse
import json
import math
import os
import tempfile
from pathlib import Path

from app import media
from app.audio.overdub import (
    OverdubLevels,
    create_review_plan,
    extract_original_pcm,
    render_overdub,
    validate_overdub_plan,
    write_silent_bed_like,
)
from app.qwen_assemble import place_lines


def _line_manifest(work_dir):
    path = Path(work_dir) / "lines.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if type(data) is not dict or set(data) != {"language", "lines"}:
        raise ValueError("This job has no valid lines.json synthesis manifest")
    lines = data["lines"]
    if type(lines) is not list or not lines:
        raise ValueError("No synthesized speech lines are recorded for this job")
    paths, starts, gains = [], [], []
    for i, line in enumerate(lines):
        if type(line) is not dict or line.get("i") != i:
            raise ValueError("Synthesis line numbering differs from this job")
        start = line.get("start")
        if type(start) not in (int, float) or not math.isfinite(start) or start < 0:
            raise ValueError(f"Line {i} has no valid playback start")
        gain = line.get("gain")
        if gain is not None and (
            type(gain) not in (int, float)
            or not math.isfinite(gain) or not 0.0 <= gain <= 4.0
        ):
            raise ValueError(f"Line {i} has invalid playback gain")
        audio = Path(work_dir) / f"qwen_line_{i}.wav"
        paths.append(str(audio) if audio.is_file() else None)
        starts.append(float(start))
        gains.append(gain)
    if not any(paths):
        raise ValueError("No synthesized Qwen line WAVs remain in this job")
    return paths, starts, gains


def prepare_existing(video, work_dir, events_path):
    """Extract the exact source clock and prepare an unapproved all-REVIEW plan."""
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    original = Path(work_dir) / "overdub_original_48k.wav"
    if original.exists():
        raise ValueError("Source PCM already exists; use a fresh preparation directory")
    extract_original_pcm(video, original, duration=media.video_duration(str(video)))
    return create_review_plan(original, events_path)


def export_existing(video, work_dir, events_path, output_mp4, levels=None):
    """Create a new two-audio-stream video from approved event actions."""
    video = Path(video).resolve()
    output = Path(output_mp4).resolve()
    job = Path(work_dir).resolve()
    plan = Path(events_path).resolve()
    if output.exists() or output in (video, plan) or output.parent != job:
        raise ValueError("Overdub output must be new and inside the existing job directory")
    line_paths, starts, gains = _line_manifest(job)
    duration = media.video_duration(str(video))
    # The source PCM is rebuilt from the actual video, never trusted from a
    # prior preparation that may have used a different cut or source file.
    with tempfile.TemporaryDirectory(prefix="overdub-", dir=str(job)) as scratch:
        tmp = Path(scratch)
        original = tmp / "original.wav"
        extract_original_pcm(video, original, duration=duration)
        validate_overdub_plan(original, plan)
        silent = tmp / "silent.wav"
        voice = tmp / "translated_voice_only.wav"
        mixed = tmp / "dynamic_overdub.wav"
        write_silent_bed_like(original, silent)
        place_lines(str(silent), line_paths, starts, str(voice),
                    gains=gains, log=lambda msg: None)
        receipt = render_overdub(original, voice, plan, mixed, levels=levels)
        staging = tmp / "finished.mp4"
        result = media.mux_overdub(str(video), str(mixed), str(staging), duration)
        if result.returncode:
            raise RuntimeError("Could not export overdub video: " + (
                result.stderr.strip().splitlines()[-1] if result.stderr.strip()
                else "ffmpeg returned an error"
            ))
        media.ensure_video_length(
            str(video), str(staging), lambda msg: None, preserve_overdub_tracks=True
        )
        os.replace(staging, output)
    receipt.update({
        "output_mp4": output.name,
        "audio_tracks": ["Overdub", "Original"],
        "source_video": video.name,
    })
    receipt_path = output.with_suffix(output.suffix + ".overdub.json")
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export local dual-language overdub")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--video", required=True, type=Path)
    prepare.add_argument("--work-dir", required=True, type=Path)
    prepare.add_argument("--events", required=True, type=Path)
    export = commands.add_parser("export")
    export.add_argument("--video", required=True, type=Path)
    export.add_argument("--work-dir", required=True, type=Path)
    export.add_argument("--events", required=True, type=Path)
    export.add_argument("--output", required=True, type=Path)
    export.add_argument("--original-speech-db", type=float, default=-16.0)
    export.add_argument("--dub-speech-db", type=float, default=-2.0)
    export.add_argument("--fade-ms", type=float, default=300.0)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_existing(args.video, args.work_dir, args.events)
        else:
            profile = OverdubLevels(
                args.original_speech_db, args.dub_speech_db, args.fade_ms
            )
            result = export_existing(
                args.video, args.work_dir, args.events, args.output, levels=profile
            )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"Overdub export rejected: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
