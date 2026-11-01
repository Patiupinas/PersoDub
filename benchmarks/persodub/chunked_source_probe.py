"""Resumable, bounded, source-audio ASR comparison. Research only.

Each 34-second original-video window is decoded once with a fresh
faster-whisper subprocess. This isolates runaway text-generation loops and
records TIMEOUT/ERROR as measurements, never as acoustic quality judgments.
Model, source and original-transcript identities bind the checkpoint.
All text stays in a private report outside the Git repository.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import re
import subprocess
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

from app.source_transcript_quality import cue_timing_metrics, summarize_source_timing
from benchmarks.persodub.source_asr_crosscheck import (
    MAX_CLIP_SECONDS,
    decode_audio_window,
    ordered_reference_coverage,
)

MAX_WINDOW_S = MAX_CLIP_SECONDS + 4.0
SCHEMA_VERSION = 1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def plan_windows(duration: float, window: float = MAX_WINDOW_S,
                 overlap: float = 5.0) -> list[dict]:
    """Fixed boundaries with disjoint midpoint-owned cores."""
    if (not all(map(math.isfinite, (duration, window, overlap)))
            or duration <= 0 or duration > 24 * 3600
            or window < 10 or window > MAX_WINDOW_S
            or overlap < 0 or overlap >= window / 2):
        raise ValueError("Invalid bounded-window configuration")
    result = []
    step = window - overlap
    start = 0.0
    while start < duration - 0.0005:
        end = min(duration, start + window)
        result.append({
            "index": len(result), "start_s": round(start, 3),
            "end_s": round(end, 3),
        })
        if end >= duration - 0.0005:
            break
        start += step
    # Assign the overlapping time equally to adjacent windows. Do not claim
    # this resolves partial English sentences or label boundaries.
    for index, item in enumerate(result):
        item["core_start_s"] = (
            0.0 if index == 0
            else round((result[index - 1]["end_s"] + item["start_s"]) / 2, 3)
        )
        item["core_end_s"] = (
            round(duration, 3) if index == len(result) - 1
            else round((item["end_s"] + result[index + 1]["start_s"]) / 2, 3)
        )
    if any(w["core_end_s"] <= w["core_start_s"] for w in result):
        raise ValueError("Window owned cores must not be empty")
    return result


def _media_duration(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
        capture_output=True, text=True, timeout=15, check=True,
    )
    duration = float(proc.stdout)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid original media duration")
    return duration


def _worker(media: Path, model_dir: Path, start: float,
            end: float, condition_previous: bool) -> dict:
    """Run in an isolated process, never the long-lived app interpreter."""
    from faster_whisper import WhisperModel

    waveform = decode_audio_window(media, start, end - start)
    model = WhisperModel(str(model_dir), device="cpu", compute_type="int8")
    started = time.monotonic()
    segments, info = model.transcribe(
        waveform, language="en", beam_size=5, word_timestamps=True,
        condition_on_previous_text=condition_previous, vad_filter=False,
    )
    output = []
    for item in segments:
        words = item.words or []
        output.append({
            "start_s": round(start + float(item.start), 3),
            "end_s": round(start + float(item.end), 3),
            "text": str(item.text),
            "avg_logprob": round(float(item.avg_logprob), 4),
            "compression_ratio": round(float(item.compression_ratio), 4),
            "no_speech_prob": round(float(item.no_speech_prob), 4),
            "words": [{
                "start": round(start + float(w.start), 3),
                "end": round(start + float(w.end), 3),
                "word": str(w.word),
            } for w in words],
        })
    return {
        "status": "complete", "decode_seconds": round(time.monotonic() - started, 3),
        "segments": output, "source_language": info.language,
    }


def _word_midpoint(word: dict) -> float:
    return (word["start"] + word["end"]) / 2


def _cue_midpoint(cue: dict) -> float:
    """Existing source cues use start/end; bounded worker uses start_s/end_s."""
    start_key, end_key = ("start_s", "end_s") if "start_s" in cue else ("start", "end")
    return (cue[start_key] + cue[end_key]) / 2


def window_comparison(window: dict, fresh: list[dict],
                      source_cues: list[dict]) -> dict:
    """Compare unique time-owned words, not overlapping duplicated windows."""
    left, right = window["core_start_s"], window["core_end_s"]
    source_owned = [
        cue for cue in source_cues
        if left <= _cue_midpoint(cue) < right
        or (right == window["end_s"] and _cue_midpoint(cue) == right)
    ]
    fresh_owned_words = [
        word for cue in fresh for word in cue.get("words", [])
        if left <= _word_midpoint(word) < right
        or (right == window["end_s"] and _word_midpoint(word) == right)
    ]
    fresh_owned_segments = [
        cue for cue in fresh if left <= _cue_midpoint(cue) < right
        or (right == window["end_s"] and _cue_midpoint(cue) == right)
    ]
    all_fresh_words = [word for cue in fresh for word in cue.get("words", [])]
    fresh_text = "".join(word["word"] for word in fresh_owned_words).strip()
    if not fresh_owned_words:
        fresh_text = " ".join(cue["text"].strip() for cue in fresh_owned_segments)
    source_text = " ".join(cue["text"].strip() for cue in source_owned)
    source_time = [cue_timing_metrics(cue) for cue in source_owned]
    zero_source = sum(x["zero_duration_words"] for x in source_time)
    return {
        "core_start_s": left, "core_end_s": right,
        "source_cues": len(source_owned),
        "source_word_timestamps": sum(x["word_count"] for x in source_time),
        "source_zero_duration_words": zero_source,
        "fresh_owned_segments": len(fresh_owned_segments),
        "fresh_owned_words": len(fresh_owned_words),
        "fresh_zero_duration_words": sum(
            w["end"] <= w["start"] + 0.001 for w in fresh_owned_words
        ),
        "overlap_words_not_owned_here": len(all_fresh_words) - len(fresh_owned_words),
        "ordered_source_word_coverage": ordered_reference_coverage(
            source_text, fresh_text
        ),
        "source_transcript_text": source_text,
        "fresh_source_audio_text": fresh_text,
        "comparison_semantic_ground_truth": False,
        "comparison_is_word_error_rate": False,
    }


def _normalize_alphabet_runs(tokens: list[str]) -> list[str]:
    """Treat 'A B C D' and 'ABCD' alike for a vocal exercise.

    Only join at least three strictly ascending single-letter names. Do not
    remove a missing note, merge arbitrary spelled words, or change the ASR.
    """
    result = []
    i = 0
    while i < len(tokens):
        j = i + 1
        while (j < len(tokens) and len(tokens[j]) == 1
               and len(tokens[j - 1]) == 1
               and tokens[j].isascii() and tokens[j].isalpha()
               and tokens[j - 1].isascii() and tokens[j - 1].isalpha()
               and ord(tokens[j]) == ord(tokens[j - 1]) + 1):
            j += 1
        if j - i >= 3:
            result.append("".join(tokens[i:j]))
            i = j
        else:
            result.append(tokens[i])
            i += 1
    return result


def overlap_diagnostic(left: dict, right: dict,
                       left_chunk: dict, right_chunk: dict) -> dict:
    """Compare the same source seconds decoded in adjacent windows.

    This is a lexical consistency probe, not proof the English speech was
    recognized accurately or the original singing event was preserved.
    """
    start, end = right["start_s"], left["end_s"]
    if start >= end:
        raise ValueError("Expected an overlapping pair of source windows")

    def select_words(chunk):
        return [
            word["word"]
            for cue in chunk["segments"] for word in cue.get("words", [])
            if start <= _word_midpoint(word) <= end
        ]

    words_left = select_words(left_chunk)
    words_right = select_words(right_chunk)
    text_left, text_right = "".join(words_left), "".join(words_right)
    tokens_left = _normalize_alphabet_runs(re.findall(
        r"[a-z0-9]+(?:'[a-z0-9]+)?", text_left.casefold()
    ))
    tokens_right = _normalize_alphabet_runs(re.findall(
        r"[a-z0-9]+(?:'[a-z0-9]+)?", text_right.casefold()
    ))
    if not tokens_left and not tokens_right:
        status, ratio = "no_observed_words", None
    elif not tokens_left or not tokens_right:
        status, ratio = "needs_review_one_sided", 0.0
    else:
        ratio = round(SequenceMatcher(
            None, tokens_left, tokens_right, autojunk=False
        ).ratio(), 4)
        status = (
            "needs_review_different_words"
            if len(tokens_left) >= 2 and len(tokens_right) >= 2
            and ratio < 0.6 else "observed_not_human_verified"
        )
    return {
        "left_window": left["index"], "right_window": right["index"],
        "start_s": start, "end_s": end,
        "left_word_count": len(tokens_left),
        "right_word_count": len(tokens_right),
        "lexical_ratio": ratio, "status": status,
        "left_source_decode": text_left.strip(),
        "right_source_decode": text_right.strip(),
        "verified_source_text": False,
    }


def _atomic_write(path: Path, report: dict) -> None:
    pending = path.with_name(path.name + ".part")
    try:
        with pending.open("w", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


def make_context(media: Path, transcript: Path, model_dir: Path,
                 window: float, overlap: float, condition_previous: bool,
                 timeout: float) -> dict:
    for file in (media, transcript, model_dir / "config.json",
                 model_dir / "model.bin"):
        if not file.is_file():
            raise FileNotFoundError("Missing required input: " + str(file))
    saved = json.loads(transcript.read_text(encoding="utf-8"))
    if not isinstance(saved, dict) or not isinstance(saved.get("cues"), list):
        raise ValueError("Original transcript must contain source cues")
    source_quality = summarize_source_timing(saved)
    duration = _media_duration(media)
    settings = {
        "model": "faster-whisper-large-v3-installed",
        "library_version": importlib.metadata.version("faster-whisper"),
        "cpu_int8": True, "language": "en", "beam_size": 5,
        "word_timestamps": True, "condition_on_previous_text": condition_previous,
        "vad_filter": False, "window_seconds": window, "overlap_seconds": overlap,
        "timeout_seconds": timeout,
    }
    identity = {
        "source_media_sha256": sha256(media),
        "source_transcript_sha256": sha256(transcript),
        "model_bin_sha256": sha256(model_dir / "model.bin"),
        "model_config_sha256": sha256(model_dir / "config.json"),
        "settings": settings,
        "source_duration_s": round(duration, 3),
    }
    return {
        "schema_version": SCHEMA_VERSION, "identity": identity,
        "source_word_timing": source_quality,
        "planned": plan_windows(duration, window, overlap),
        "chunks": [],
        "observational_only": True, "asr_gold": False,
        "translation_adequacy_verified": False,
    }


def _owned_summary(report: dict, source_cues: list[dict]) -> dict:
    results = {x["index"]: x for x in report["chunks"]}
    completed = []
    for window in report["planned"]:
        item = results.get(window["index"])
        if item is None or item["status"] != "complete":
            continue
        item["comparison"] = window_comparison(
            window, item["segments"], source_cues
        )
        completed.append(item)
    raw_fresh = [
        word for chunk in completed
        for cue in chunk["segments"] for word in cue.get("words", [])
    ]
    report["overlap_diagnostics"] = [
        overlap_diagnostic(left, right, results[left["index"]],
                           results[right["index"]])
        for left, right in zip(report["planned"], report["planned"][1:])
        if left["index"] in results and right["index"] in results
        and results[left["index"]]["status"] == "complete"
        and results[right["index"]]["status"] == "complete"
    ]
    return {
        "planned": len(report["planned"]),
        "completed": len(completed),
        "timeouts": sum(x["status"] == "timeout" for x in report["chunks"]),
        "errors": sum(x["status"] == "error" for x in report["chunks"]),
        "not_run": len(report["planned"]) - len(report["chunks"]),
        "source_owned_zero_duration_words": sum(
            x["comparison"]["source_zero_duration_words"] for x in completed
        ),
        "fresh_owned_zero_duration_words": sum(
            x["comparison"]["fresh_zero_duration_words"] for x in completed
        ),
        "fresh_owned_word_count": sum(
            x["comparison"]["fresh_owned_words"] for x in completed
        ),
        "fresh_raw_word_count_with_overlap": len(raw_fresh),
        "fresh_raw_zero_duration_words_with_overlap": sum(
            word["end"] <= word["start"] + 0.001 for word in raw_fresh
        ),
        "fresh_overlap_words_not_owned_in_chunk": sum(
            x["comparison"]["overlap_words_not_owned_here"] for x in completed
        ),
        "overlap_pairs_observed": len(report["overlap_diagnostics"]),
        "overlap_pairs_needing_review": sum(
            x["status"].startswith("needs_review")
            for x in report["overlap_diagnostics"]
        ),
    }


def run_probe(media: Path, transcript: Path, model_dir: Path, output: Path,
              *, window: float = MAX_WINDOW_S, overlap: float = 5.0,
              timeout: float = 70, condition_previous: bool = True,
              max_new_chunks: int | None = None,
              only_indices: set[int] | None = None,
              retry_failed: bool = False, runner=subprocess.run) -> dict:
    if timeout < 10 or timeout > 600 or not math.isfinite(timeout):
        raise ValueError("Chunk timeout out of bounds")
    if max_new_chunks is not None and max_new_chunks < 1:
        raise ValueError("max_new_chunks must be positive")
    media, transcript, model_dir = (
        media.resolve(), transcript.resolve(), model_dir.resolve()
    )
    output = output.resolve()
    if output.parent in (media.parent, model_dir, transcript.parent):
        raise ValueError("Private report must be outside original job and model")
    report = make_context(
        media, transcript, model_dir, window, overlap,
        condition_previous, timeout,
    )
    if output.exists():
        saved = json.loads(output.read_text(encoding="utf-8"))
        if (saved.get("schema_version") != report["schema_version"]
                or saved.get("identity") != report["identity"]
                or saved.get("planned") != report["planned"]):
            raise ValueError("Checkpoint identity differs from source/model/settings")
        prior = saved.get("chunks")
        if not isinstance(prior, list) or any(
            type(x) is not dict or type(x.get("index")) is not int
            or x["index"] < 0 or x["index"] >= len(report["planned"])
            for x in prior
        ) or len({x["index"] for x in prior}) != len(prior):
            raise ValueError("Malformed checkpoint chunks")
        report["chunks"] = prior
    raw_source = json.loads(transcript.read_text(encoding="utf-8"))["cues"]
    if only_indices is not None and (
        not only_indices or any(type(index) is not int or index < 0
                                or index >= len(report["planned"])
                                for index in only_indices)
    ):
        raise ValueError("Requested source window index is invalid")
    new_count = 0
    for window_item in report["planned"]:
        i = window_item["index"]
        if only_indices is not None and i not in only_indices:
            continue
        existing = next((row for row in report["chunks"] if row["index"] == i), None)
        if existing and (existing["status"] == "complete" or not retry_failed):
            continue
        if max_new_chunks is not None and new_count >= max_new_chunks:
            break
        command = [
            sys.executable, "-m", "benchmarks.persodub.chunked_source_probe",
            "--worker", "--source-media", str(media), "--model-dir",
            str(model_dir), "--start", str(window_item["start_s"]),
            "--end", str(window_item["end_s"]), "--condition-previous",
            str(int(condition_previous)),
        ]
        start = time.monotonic()
        try:
            proc = runner(
                command, check=False, capture_output=True,
                text=True, timeout=timeout,
            )
            if proc.returncode:
                item = {"status": "error", "error": "worker_exit_%d" % proc.returncode}
            else:
                decoded = json.loads(proc.stdout)
                if (decoded.get("status") != "complete"
                        or not isinstance(decoded.get("segments"), list)):
                    raise ValueError("Invalid ASR worker response")
                item = decoded
        except subprocess.TimeoutExpired:
            item = {"status": "timeout", "timeout_seconds": timeout}
        except (ValueError, json.JSONDecodeError):
            item = {"status": "error", "error": "invalid_worker_response"}
        item["index"] = i
        item["start_s"] = window_item["start_s"]
        item["end_s"] = window_item["end_s"]
        item["wall_seconds"] = round(time.monotonic() - start, 2)
        if existing is not None:
            report["chunks"].remove(existing)
        report["chunks"].append(item)
        report["chunks"].sort(key=lambda entry: entry["index"])
        report["summary"] = _owned_summary(report, raw_source)
        _atomic_write(output, report)
        print(json.dumps({
            "index": i, "status": item["status"], "seconds": item["wall_seconds"],
            "completed": report["summary"]["completed"],
        }), flush=True)
        new_count += 1
    report["summary"] = _owned_summary(report, raw_source)
    _atomic_write(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source-media", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--start", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--end", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--condition-previous", type=int, choices=(0, 1),
                        default=1)
    parser.add_argument("--original-transcript", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--window-seconds", type=float, default=MAX_WINDOW_S)
    parser.add_argument("--overlap-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=70)
    parser.add_argument("--max-new-chunks", type=int)
    parser.add_argument("--only-indices", help="Comma-separated, zero-based window IDs")
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()

    if args.worker:
        if args.start is None or args.end is None:
            raise ValueError("Worker requires source audio bounds")
        result = _worker(
            args.source_media, args.model_dir, args.start, args.end,
            bool(args.condition_previous),
        )
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0

    if args.original_transcript is None or args.report is None:
        raise ValueError("Parent requires transcript and report paths")
    report = run_probe(
        args.source_media, args.original_transcript, args.model_dir,
        args.report, window=args.window_seconds, overlap=args.overlap_seconds,
        timeout=args.timeout_seconds,
        condition_previous=bool(args.condition_previous),
        max_new_chunks=args.max_new_chunks,
        only_indices=(
            {int(item) for item in args.only_indices.split(",")}
            if args.only_indices is not None else None
        ),
        retry_failed=args.retry_failed,
    )
    print("SUMMARY " + json.dumps(report["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
