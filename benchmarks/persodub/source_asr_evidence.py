"""Source-first, read-only triage: Whisper timestamps plus two audio reruns.

Do not treat Whisper-vs-Whisper agreement as independent ground truth.
This module does not change A4 decisions, original speech, translations,
or user media. It only builds evidence and a local bilingual review worksheet.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

from app.source_transcript_quality import SOURCE_WPS_REVIEW, ZERO_WORD_RATIO_REVIEW
from app.source_transcript_quality import cue_timing_metrics as _cue_stats

ASR_COVERAGE_REVIEW = 0.30


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _repetition_hint(text: str) -> bool:
    """Flag decoder loops and sustained brrrr, not automatically singing."""
    lower = text.casefold()
    if re.search(r"(?i)(?:br{8,}|r{30,})", lower):
        return True
    tokens = re.findall(r"\w+", lower)
    for phrase_size in (1, 2, 3):
        for i in range(len(tokens) - 4 * phrase_size + 1):
            chunk = tokens[i:i + phrase_size]
            if chunk * 4 == tokens[i:i + 4 * phrase_size]:
                return True
    return False


def _vocalization_hint(text: str) -> bool:
    """Surface possible sustained /brrr/ exercises separately from ASR loops."""
    return bool(re.search(r"(?i)(?:br{8,}|r{30,})", text))


def _match_rows(small: dict, base: dict) -> list[tuple[dict, dict]]:
    """Reject stale, differently scoped cross-check evidence."""
    if (small.get("status") != "OBSERVED"
            or base.get("status") != "OBSERVED"
            or small.get("independent_ground_truth") is not False
            or base.get("independent_ground_truth") is not False):
        raise ValueError("ASR reports must be observed, not ground truth")
    if small.get("source") != base.get("source"):
        raise ValueError("ASR source/media identity mismatch")
    model_a = small.get("crosscheck_asr", {})
    model_b = base.get("crosscheck_asr", {})
    if (model_a.get("checkpoint_sha256") ==
            model_b.get("checkpoint_sha256")):
        raise ValueError("Two separately identified ASR checkpoints are required")
    left, right = small.get("rows", []), base.get("rows", [])
    if not left or len(left) != len(right):
        raise ValueError("ASR reports have different interval counts")
    pairs = []
    for a, b in zip(left, right):
        for key in (
            "start_s", "end_s", "original_english_asr",
            "russian_translation", "source_cues"
        ):
            if a.get(key) != b.get(key):
                raise ValueError("ASR interval/text identity mismatch")
        for row in (a, b):
            value = row.get("ordered_source_word_coverage")
            if (type(value) not in (int, float)
                    or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("ASR coverage metric is missing or invalid")
        pairs.append((a, b))
    return pairs


def assemble(
    small: dict, base: dict, transcript: dict,
) -> dict:
    pairs = _match_rows(small, base)
    cues = transcript.get("cues", [])
    if not isinstance(cues, list) or not cues:
        raise ValueError("Original transcript has no source cues")

    reviewed = []
    for small_row, base_row in pairs:
        a, b = small_row["start_s"], small_row["end_s"]
        touched = [
            _cue_stats(c) for c in cues
            if min(float(c["end"]), b) - max(float(c["start"]), a) > 0.025
        ]
        if not touched:
            raise ValueError("Source interval has no original transcript cue")
        word_count = sum(c["word_count"] for c in touched)
        zero = sum(c["zero_duration_words"] for c in touched)
        count_bad = sum(c["words_outside_cue"] for c in touched)
        max_wps = max(c["cue_words_per_second"] for c in touched)
        cov_small = small_row["ordered_source_word_coverage"]
        cov_base = base_row["ordered_source_word_coverage"]
        small_loop = _repetition_hint(small_row["independent_asr_text"])
        base_loop = _repetition_hint(base_row["independent_asr_text"])
        vocalization = (
            _vocalization_hint(small_row["independent_asr_text"])
            or _vocalization_hint(base_row["independent_asr_text"])
        )

        flags = []
        if (word_count > 0 and zero >= 2
                and zero / word_count >= ZERO_WORD_RATIO_REVIEW):
            flags.append("source_word_timestamps_collapsed_review")
        if max_wps > SOURCE_WPS_REVIEW:
            flags.append("source_words_per_second_review")
        if count_bad:
            flags.append("source_words_outside_cue_review")
        if cov_small < ASR_COVERAGE_REVIEW and cov_base < ASR_COVERAGE_REVIEW:
            flags.append("both_crosschecks_disagree_review")
        elif min(cov_small, cov_base) < ASR_COVERAGE_REVIEW:
            flags.append("one_crosscheck_disagrees_review")
        if vocalization:
            flags.append("possible_sustained_vocalization_review")
        if small_loop or base_loop:
            flags.append("crosscheck_decoder_repetition_review")

        if ("both_crosschecks_disagree_review" in flags or
                "source_word_timestamps_collapsed_review" in flags):
            route = "SOURCE_TRANSCRIPT_AND_TIMING_REVIEW_FIRST"
        elif vocalization:
            route = "SOURCE_AUDIO_EVENT_REVIEW_FIRST"
        elif "one_crosscheck_disagrees_review" in flags:
            route = "ASR_PROBE_DISAGREEMENT_REVIEW_FIRST"
        else:
            route = "BILINGUAL_TRANSLATION_REVIEW_WITH_AUDIO_CONTEXT"

        reviewed.append({
            "start_s": a,
            "end_s": b,
            "source_cues": small_row["source_cues"],
            "source_original_asr": small_row["original_english_asr"],
            "source_whisper_small": small_row["independent_asr_text"],
            "source_whisper_base": base_row["independent_asr_text"],
            "translation_ru": small_row["russian_translation"],
            "whisper_small_lexical_coverage": cov_small,
            "whisper_base_lexical_coverage": cov_base,
            "touched_source_cues": touched,
            "source_timestamp_words_total": word_count,
            "source_timestamp_zero_duration": zero,
            "source_timestamp_outside_cue": count_bad,
            "diagnostic_flags": flags,
            "priority_route": route,
            "independent_human_transcript_check": None,
            "independent_human_translation_adequacy": None,
            "translation_adequacy_certified": False,
        })

    all_cues = [_cue_stats(c) for c in cues]
    return {
        "schema_version": 1,
        "status": "OBSERVED",
        "source_transcript_certified": False,
        "translation_adequacy_certified": False,
        "model_independence": "two_whisper_checkpoints_same_architecture_family",
        "method": {
            "source_audio_decode": "source_mp4_independently_transcribed",
            "word_timing": "original_large_v3_transcript_json",
            "automatic_review_thresholds_are_calibrated": False,
            "meaning_review_is_human_verified": False,
        },
        "summary": {
            "review_intervals": len(reviewed),
            "source_transcript_timing_review": sum(
                x["priority_route"] == "SOURCE_TRANSCRIPT_AND_TIMING_REVIEW_FIRST"
                for x in reviewed
            ),
            "audio_event_review": sum(
                x["priority_route"] == "SOURCE_AUDIO_EVENT_REVIEW_FIRST"
                for x in reviewed
            ),
            "asr_probe_disagreement_review": sum(
                x["priority_route"] == "ASR_PROBE_DISAGREEMENT_REVIEW_FIRST"
                for x in reviewed
            ),
            "translation_review_with_audio": sum(
                x["priority_route"]
                == "BILINGUAL_TRANSLATION_REVIEW_WITH_AUDIO_CONTEXT"
                for x in reviewed
            ),
            "all_original_cues": len(all_cues),
            "all_original_zero_duration_words": sum(
                x["zero_duration_words"] for x in all_cues
            ),
            "all_original_words_with_timestamps": sum(
                x["word_count"] for x in all_cues
            ),
        },
        "rows": reviewed,
    }


def export_review_csv(path: Path, report: dict) -> None:
    """Output private review text locally with empty adjudication fields."""
    columns = [
        "start_s", "end_s", "priority_route", "diagnostic_flags",
        "source_original_asr", "source_whisper_small",
        "source_whisper_base", "translation_ru",
        "whisper_small_lexical_coverage", "whisper_base_lexical_coverage",
        "source_timestamp_zero_duration", "source_timestamp_words_total",
        "human_corrected_en_source", "human_translation_adequacy_0_to_4",
        "human_notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for item in report["rows"]:
            writer.writerow({
                **{key: item.get(key) for key in columns},
                "diagnostic_flags": ";".join(item["diagnostic_flags"]),
                "human_corrected_en_source": "",
                "human_translation_adequacy_0_to_4": "",
                "human_notes": "",
            })


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--small-report", type=Path, required=True)
    parser.add_argument("--base-report", type=Path, required=True)
    parser.add_argument("--original-transcript", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--review-csv-out", type=Path, required=True)
    args = parser.parse_args(argv)

    small = json.loads(args.small_report.read_text(encoding="utf-8"))
    base = json.loads(args.base_report.read_text(encoding="utf-8"))
    transcript = json.loads(args.original_transcript.read_text(encoding="utf-8"))
    result = assemble(small, base, transcript)
    result["inputs_sha256"] = {
        "small_report": _hash(args.small_report),
        "base_report": _hash(args.base_report),
        "original_transcript": _hash(args.original_transcript),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.review_csv_out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    export_review_csv(args.review_csv_out, result)
    print(json.dumps({
        "status": result["status"], "summary": result["summary"],
        "json": str(args.out), "csv": str(args.review_csv_out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
