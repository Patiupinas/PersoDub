"""Read-only audio-grounded ASR cross-check for reviewed PersoDub intervals.

Original job uses faster-whisper large-v3; this probe uses an independently
run, explicitly cached OpenAI Whisper-small checkpoint. Since both use
Whisper-family architecture, agreement is corroboration, NOT transcription
ground truth. Reports and source speech are kept outside the repository.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

DEFAULT_PAD_SECONDS = 1.8
MAX_CLIP_SECONDS = 30.0
MAX_REVIEW_ROWS = 100
SAMPLE_RATE = 16000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for data in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def _words(text: str) -> list[str]:
    """Match ordered English words without conflating translated languages."""
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.casefold())


def ordered_reference_coverage(reference: str, heard: str) -> float | None:
    """Lexical overlap proxy; NOT word-error-rate or speech accuracy."""
    left, right = _words(reference), _words(heard)
    if not left:
        return None
    common = sum(block.size for block in SequenceMatcher(
        None, left, right, autojunk=False
    ).get_matching_blocks())
    return round(common / len(left), 5)


def read_review_rows(path: Path) -> list[dict]:
    """Validate scoped time intervals; leave reviewer fields untouched."""
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        required = {
            "start_s", "end_s", "english_asr", "russian_translation"
        }
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Review CSV missing required source fields")
        rows = list(reader)
    if not rows or len(rows) > MAX_REVIEW_ROWS:
        raise ValueError("Review CSV must contain 1-100 rows")
    last = -1.0
    for row in rows:
        start, end = float(row["start_s"]), float(row["end_s"])
        if (not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end <= start or end - start > MAX_CLIP_SECONDS
                or start < last):
            raise ValueError("Review CSV has invalid or unsorted time intervals")
        if not row["english_asr"].strip() or not row["russian_translation"].strip():
            raise ValueError("Review CSV has empty source or translation")
        row["start_s"] = start
        row["end_s"] = end
        last = start
    return rows


def decode_audio_window(
    media: Path, start_s: float, duration_s: float,
    ffmpeg: str = "ffmpeg"
):
    """Decode only a bounded mono PCM window; no copied media is persisted."""
    import numpy as np

    if start_s < 0 or duration_s <= 0 or duration_s > MAX_CLIP_SECONDS + 4.0:
        raise ValueError("Invalid audio window")
    result = subprocess.run(
        [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
         "-ss", f"{start_s:.3f}", "-i", str(media),
         "-t", f"{duration_s:.3f}", "-vn", "-ac", "1", "-ar",
         str(SAMPLE_RATE), "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"],
        check=True, capture_output=True, timeout=75,
    )
    decoded = np.frombuffer(result.stdout, dtype="<f4")
    if decoded.size < 1000:
        raise ValueError("Decoded audio window was empty")
    if not np.all(np.isfinite(decoded)):
        raise ValueError("Decoded audio window was not finite")
    return decoded.copy()


def crosscheck(
    media: Path,
    review_csv: Path,
    *,
    transcriber,
    decoder=decode_audio_window,
    padding: float = DEFAULT_PAD_SECONDS,
    model_metadata: dict | None = None,
) -> dict:
    """Run a distinct model on source PCM, not the existing English SRT."""
    if padding < 0 or padding > 4 or not math.isfinite(padding):
        raise ValueError("Padding out of range")
    media, review_csv = media.resolve(), review_csv.resolve()
    if not media.is_file() or not review_csv.is_file():
        raise ValueError("Media and review CSV must both exist")

    rows = read_review_rows(review_csv)
    results = []
    for row in rows:
        start = max(0.0, row["start_s"] - padding)
        end = row["end_s"] + padding
        if end - start > MAX_CLIP_SECONDS + 4.0:
            raise ValueError("Review span plus context is too long")
        waveform = decoder(media, start, end - start)
        heard = transcriber(waveform)
        if not isinstance(heard, str):
            raise ValueError("ASR must return text")
        duration = row["end_s"] - row["start_s"]
        words_per_s = len(_words(row["english_asr"])) / duration
        results.append({
            "start_s": row["start_s"],
            "end_s": row["end_s"],
            "clip_start_s": round(start, 3),
            "clip_end_s": round(end, 3),
            "source_cues": row.get("source_cues", ""),
            "original_english_asr": row["english_asr"],
            "independent_asr_text": heard.strip(),
            "russian_translation": row["russian_translation"],
            "original_cue_words_per_second": round(words_per_s, 3),
            "ordered_source_word_coverage": ordered_reference_coverage(
                row["english_asr"], heard
            ),
            "diagnostic_flags": (
                ["original_cue_timing_review"] if words_per_s > 6.0 else []
            ) + (["independent_asr_empty"] if not heard.strip() else []),
            "human_transcript_verified": False,
            "human_translation_verified": False,
        })

    return {
        "schema_version": 1,
        "status": "OBSERVED",
        "independent_ground_truth": False,
        "source": {
            "media_sha256": _sha256(media),
            "review_csv_sha256": _sha256(review_csv),
        },
        "reference_asr": {
            "family": "whisper",
            "engine": "whisper_as_reported_by_job",
            "provenance": (
                "The job manifest says stt_engine=whisper; the current worker "
                "defaults to faster-whisper-large-v3, but this job does not "
                "record the exact original model checkpoint hash."
            ),
        },
        "crosscheck_asr": model_metadata or {"method": "injected_test_model"},
        "method": {
            "segment_input": "direct_source_media_pcm_not_dubbed_audio",
            "audio": "16k_mono_float_pcm_bounded_windows",
            "context_padding_seconds": padding,
            "ordered_source_word_coverage": "diagnostic_only_not_WER",
            "verified_transcription": False,
            "verified_translation": False,
        },
        "summary": {
            "reviewed_intervals": len(results),
            "timing_review_intervals": sum(
                "original_cue_timing_review" in item["diagnostic_flags"]
                for item in results
            ),
        },
        "rows": results,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-media", type=Path, required=True)
    parser.add_argument("--review-csv", type=Path, required=True)
    parser.add_argument("--model-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--padding", type=float, default=DEFAULT_PAD_SECONDS)
    parser.add_argument("--device", default="cpu", choices=["cpu", "mps"])
    args = parser.parse_args(argv)

    checkpoint = args.model_file.expanduser().resolve()
    if not checkpoint.is_file():
        raise ValueError("Whisper model must already exist: no auto-download")
    import whisper

    model = whisper.load_model(str(checkpoint), device=args.device)

    def recognize(waveform):
        result = model.transcribe(
            waveform, language="en", fp16=False, temperature=0.0,
            condition_on_previous_text=False, verbose=False,
        )
        return str(result["text"]).strip()

    report = crosscheck(
        args.source_media, args.review_csv, transcriber=recognize,
        padding=args.padding,
        model_metadata={
            "method": "whisper_%s_separate_decode" % checkpoint.stem,
            "checkpoint_sha256": _sha256(checkpoint),
            "device": args.device,
            "model_family_independent": False,
            "fresh_decode_from_original_pcm": True,
        },
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"], "summary": report["summary"],
        "out": str(args.out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
