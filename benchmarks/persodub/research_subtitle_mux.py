"""Add selectable source and partial Russian captions to a private research MP4.

These captions do not assert independent EN ASR or RU human translation truth.
"""
import argparse
import json
import subprocess
from pathlib import Path

from app.text.srt import build_srt


def draft_russian_cues(frozen, extra=None, offset_s=145.0):
    cues = []
    for item in frozen["cases"]:
        if item.get("a4_reviewed") is not False:
            raise ValueError("Frozen research clips must remain explicitly unapproved")
        start = offset_s + item["start"]
        end = min(offset_s + item["slot_end"], start + item["audio_duration"])
        cues.append({"start": start, "end": end, "text": item["text"]})
    if extra is not None:
        if extra.get("status") != "OBSERVED_UNREVIEWED_TTS_RESEARCH":
            raise ValueError("Additional Russian captions lack research provenance")
        for item in extra["files"]:
            if item.get("human_a4_approved") is not False:
                raise ValueError("Unexpected A4 authority in research captions")
            if item["status"] != "FITS_SOURCE_SLOT_UNREVIEWED":
                continue
            start = item["start"]
            end = min(item["slot_end"], start + item["duration_seconds"])
            cues.append({"start": start, "end": end, "text": item["text"]})
    cues.sort(key=lambda row: (row["start"], row["end"]))
    for index, row in enumerate(cues):
        if row["end"] <= row["start"]:
            raise ValueError("Invalid subtitle interval")
        if index and row["start"] < cues[index - 1]["end"]:
            raise ValueError("Overlapping Russian cue windows")
    return cues


def subtitles(input_mp4, source_srt, russian_srt, output_mp4):
    if Path(output_mp4).exists():
        raise FileExistsError(output_mp4)
    args = [
        "ffmpeg", "-v", "error", "-n", "-i", str(input_mp4),
        "-i", str(source_srt), "-i", str(russian_srt),
        "-map", "0:v:0", "-map", "0:a:0", "-map", "0:a:1",
        "-map", "1:0", "-map", "2:0", "-c:v", "copy", "-c:a", "copy",
        "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
        "-metadata:s:s:1", "language=rus",
        "-metadata:s:s:0", "handler_name=Source English (research ASR)",
        "-metadata:s:s:1", "handler_name=Russian (research draft)",
        "-disposition:a:0", "default", "-disposition:a:1", "0",
        "-movflags", "+faststart", str(output_mp4),
    ]
    try:
        subprocess.run(args, check=True, capture_output=True, text=True, timeout=180)
    except Exception:
        Path(output_mp4).unlink(missing_ok=True)
        raise
    result = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,codec_name:stream_tags=language,handler_name",
        "-of", "json", str(output_mp4),
    ]))
    kinds = [x["codec_type"] for x in result["streams"]]
    if kinds != ["video", "audio", "audio", "subtitle", "subtitle"]:
        raise ValueError("Output has unexpected media/subtitle stream topology")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-mp4", type=Path, required=True)
    parser.add_argument("--english-srt", type=Path, required=True)
    parser.add_argument("--frozen-manifest", type=Path, required=True)
    parser.add_argument("--extra-manifest", type=Path)
    parser.add_argument("--russian-srt", type=Path, required=True)
    parser.add_argument("--output-mp4", type=Path, required=True)
    args = parser.parse_args()
    if args.russian_srt.exists():
        raise FileExistsError(args.russian_srt)
    frozen = json.loads(args.frozen_manifest.read_text())
    extra = json.loads(args.extra_manifest.read_text()) if args.extra_manifest else None
    cues = draft_russian_cues(frozen, extra)
    args.russian_srt.write_text(build_srt(cues), encoding="utf-8")
    info = subtitles(args.input_mp4, args.english_srt,
                     args.russian_srt, args.output_mp4)
    print(json.dumps({"ru_cues": len(cues), "streams": [
        x["codec_type"] for x in info["streams"]],
        "output": str(args.output_mp4)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
