"""Add selectable source and partial Russian captions to a private research MP4.

These captions do not assert independent EN ASR or RU human translation truth.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from app.text.srt import build_srt


def draft_russian_cues(frozen, extra=None, offset_s=145.0, placements=None):
    cues = []
    actual = {} if placements is None else {row["id"]: row for row in placements}
    if placements is not None and len(actual) != len(placements):
        raise ValueError("Duplicate voice placement IDs")
    included = set()

    def append_case(item, fallback_start, fallback_end):
        if item["id"] in included:
            raise ValueError("Duplicate Russian subtitle ID")
        included.add(item["id"])
        if placements is not None:
            placed = actual.get(item["id"])
            if placed is None:
                raise ValueError("Subtitle has no real voice placement")
            frames = [placed.get(key) for key in ("start_frame", "end_frame", "slot_end_frame")]
            if (any(type(value) is not int for value in frames)
                    or frames[0] < 0 or frames[0] >= frames[1] or frames[1] > frames[2]):
                raise ValueError("Invalid actual voice placement frames")
            fallback_start, fallback_end = frames[0] / 48000, frames[1] / 48000
        cues.append({"start": fallback_start, "end": fallback_end, "text": item["text"]})

    for item in frozen["cases"]:
        if item.get("a4_reviewed") is not False:
            raise ValueError("Frozen research clips must remain explicitly unapproved")
        start = offset_s + item["start"]
        if item.get("source_start") is not None:
            start = max(start, item["source_start"])
        source_end = item.get("source_end", offset_s + item["slot_end"])
        end = min(offset_s + item["slot_end"], source_end,
                  start + item["audio_duration"])
        append_case(item, start, end)
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
            append_case(item, start, end)
    if placements is not None and included != set(actual):
        raise ValueError("Voice placement has no matching Russian subtitle")
    cues.sort(key=lambda row: (row["start"], row["end"]))
    for index, row in enumerate(cues):
        if row["end"] <= row["start"]:
            raise ValueError("Invalid subtitle interval")
        if index and row["start"] < cues[index - 1]["end"]:
            raise ValueError("Overlapping Russian cue windows")
    return cues


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    parser.add_argument("--voice-receipt", type=Path)
    parser.add_argument("--russian-srt", type=Path, required=True)
    parser.add_argument("--output-mp4", type=Path, required=True)
    args = parser.parse_args()
    if args.russian_srt.exists():
        raise FileExistsError(args.russian_srt)
    frozen = json.loads(args.frozen_manifest.read_text())
    extra = json.loads(args.extra_manifest.read_text()) if args.extra_manifest else None
    placements = None
    if args.voice_receipt:
        receipt = json.loads(args.voice_receipt.read_text())
        if (receipt.get("status") != "OBSERVED_RESEARCH_PREVIEW_NOT_A4_APPROVED"
                or receipt.get("output_mp4_sha256") != file_sha256(args.input_mp4)
                or type(receipt.get("experimental_voice_cases")) is not list):
            raise ValueError("Voice placement receipt does not match research audio")
        placements = receipt["experimental_voice_cases"]
    cues = draft_russian_cues(frozen, extra, placements=placements)
    args.russian_srt.write_text(build_srt(cues), encoding="utf-8")
    info = subtitles(args.input_mp4, args.english_srt,
                     args.russian_srt, args.output_mp4)
    print(json.dumps({"ru_cues": len(cues), "streams": [
        x["codec_type"] for x in info["streams"]],
        "output": str(args.output_mp4)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
