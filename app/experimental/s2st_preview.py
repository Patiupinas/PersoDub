"""Short experimental S2ST video with selectable original and mixed audio.

This is a research-only preview of one explicitly selected speech interval.
It reuses the exact PersoDub Overdub renderer and double-audio-track muxer.
It never converts the surrounding singing, changes the original project or
truncates a spoken translation to fit its source time slot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import tempfile
import wave
from pathlib import Path

from app import media
from app.audio.overdub import extract_original_pcm, render_overdub
from app.experimental.s2st_quality import assess_candidate


def _sha(path):
    hash_value = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hash_value.update(chunk)
    return hash_value.hexdigest()


def _probe_audio_duration(path):
    response = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        text=True, capture_output=True, check=True, timeout=30,
    )
    return float(response.stdout.strip())


def render(source_video, translated_wav, start, end, output_mp4):
    """Create one speech-only lab preview, original audio always selectable."""
    source_video = Path(source_video).resolve()
    translated_wav = Path(translated_wav).resolve()
    output_mp4 = Path(output_mp4).resolve()
    if not source_video.is_file() or not translated_wav.is_file():
        raise FileNotFoundError("Source and translated clips are required")
    if (output_mp4.exists() or output_mp4 in (source_video, translated_wav)
            or output_mp4.suffix.lower() != ".mp4"):
        raise ValueError("Preview MP4 must be new and distinct from inputs")
    if not all(type(x) in (int, float) and math.isfinite(x) for x in (start, end)):
        raise ValueError("Non-finite source interval")
    interval = end - start
    if start < 0 or not (0.3 <= interval <= 30):
        raise ValueError("Source interval must be bounded at 30 seconds")
    original_duration = media.video_duration(str(source_video))
    if end > original_duration + 0.03:
        raise ValueError("Preview is outside original source")
    translated_duration = _probe_audio_duration(translated_wav)
    gate = assess_candidate(interval, translated_duration)
    if gate["state"] == "REVIEW_REQUIRED":
        raise ValueError(
            "S2ST preview requires review and cannot auto-place: "
            + ", ".join(gate["reasons"])
        )
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="persodub-s2st-preview-",
                                     dir=str(output_mp4.parent)) as scratch:
        temp = Path(scratch)
        video = temp / "clip.mp4"
        original_pcm = temp / "original.wav"
        speech_pcm = temp / "speech.wav"
        mixed_pcm = temp / "mixed.wav"
        plan_path = temp / "events.json"
        staged_mp4 = temp / "out.mp4"
        r = subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error",
             "-ss", "%.6f" % start, "-i", str(source_video),
             "-t", "%.6f" % interval, "-map", "0:v:0", "-map", "0:a:0",
             "-c:v", "libx264", "-preset", "veryfast",
             "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode:
            raise RuntimeError("FFmpeg source clip failed: " + r.stderr[-180:])
        clipped_duration = media.video_duration(str(video))
        if translated_duration > clipped_duration + 0.05:
            raise ValueError("Video clip cannot contain the full translated speech")
        extract_original_pcm(video, original_pcm, duration=clipped_duration)
        with wave.open(str(original_pcm), "rb") as reference:
            total_frames = reference.getnframes()
        with wave.open(str(translated_wav), "rb") as audio:
            speech_seconds = audio.getnframes() / audio.getframerate()
        translated_frames = min(total_frames, round(speech_seconds * 48000))
        r = subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-v", "error",
             "-i", str(translated_wav), "-af", "apad",
             "-t", "%.6f" % (total_frames / 48000),
             "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
             str(speech_pcm)],
            capture_output=True, text=True, timeout=90,
        )
        if r.returncode:
            raise RuntimeError("FFmpeg speech resample failed: " + r.stderr[-180:])
        events = [{
            "start_frame": 0, "end_frame": translated_frames,
            "action": "TRANSLATE",
        }]
        if translated_frames < total_frames:
            events.append({
                "start_frame": translated_frames, "end_frame": total_frames,
                "action": "PRESERVE",
            })
        plan = {
            "schema_version": 1, "sample_rate": 48000,
            "source_wav_sha256": _sha(original_pcm),
            "total_frames": total_frames, "events": events,
        }
        plan_path.write_text(json.dumps(plan, indent=2) + "\n")
        receipt = render_overdub(original_pcm, speech_pcm, plan_path, mixed_pcm)
        mux = media.mux_overdub(
            str(video), str(mixed_pcm), str(staged_mp4), clipped_duration,
        )
        if mux.returncode:
            raise RuntimeError("Overdub MP4 mux failed: " + mux.stderr[-180:])
        media.ensure_video_length(str(video), str(staged_mp4),
                                  lambda msg: None, preserve_overdub_tracks=True)
        stream_info = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index:stream_tags=handler_name",
             "-of", "json", str(staged_mp4)],
            capture_output=True, text=True, check=True, timeout=30,
        )
        streams = json.loads(stream_info.stdout).get("streams", [])
        if len(streams) != 2:
            raise RuntimeError("S2ST preview must have 2 selectable audio tracks")
        os.replace(staged_mp4, output_mp4)
        return {
            "schema_version": 1,
            "status": "experimental_speech_clip_overdub",
            "source_video_sha256": _sha(source_video),
            "translated_audio_sha256": _sha(translated_wav),
            "output_sha256": _sha(output_mp4),
            "clip_start_s": start, "clip_end_s": end,
            "preview_duration_s": clipped_duration,
            "translated_duration_s": translated_duration,
            "tracks": [s.get("tags", {}).get("handler_name") for s in streams],
            "record": receipt,
            "needs_listening_review": True,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-video", type=Path, required=True)
    parser.add_argument("--translated-wav", type=Path, required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    result = render(args.source_video, args.translated_wav,
                    args.start, args.end, args.out)
    if args.report:
        path = args.report.resolve()
        if path.exists() or path == args.out.resolve():
            raise FileExistsError("Report path must be separate and new")
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
