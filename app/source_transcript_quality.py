"""Read-only source-ASR word timing audit for completed local dubbing jobs.

Only objective timing anomalies are reported. A cue with an implausibly high
word rate or collapsed Whisper timestamps is REVIEW, not evidence that the
translation, acoustic speech, or original media is wrong.
"""
from __future__ import annotations

import math
import re

SOURCE_WPS_REVIEW = 6.0
ZERO_WORD_RATIO_REVIEW = 0.25
MAX_CUES = 100_000
MAX_CUE_DETAILS = 20
MAX_WORDS = 1_000_000


def cue_timing_metrics(cue: dict) -> dict:
    """Count deterministic word timing anomalies without exposing cue text."""
    if not isinstance(cue, dict):
        raise ValueError("Invalid source transcript cue")
    start = cue.get("start")
    end = cue.get("end")
    if (type(start) not in (int, float)
            or type(end) not in (int, float)
            or not all(math.isfinite(v) for v in (start, end))
            or start < 0 or end <= start):
        raise ValueError("Invalid transcript cue timing")
    words = cue.get("words") or []
    if not isinstance(words, list) or len(words) > MAX_WORDS:
        raise ValueError("Invalid transcript word list")
    zero = 0
    outside = 0
    for word in words:
        if not isinstance(word, dict):
            raise ValueError("Invalid transcript word")
        left, right = word.get("start"), word.get("end")
        if (type(left) not in (int, float)
                or type(right) not in (int, float)
                or not all(math.isfinite(v) for v in (left, right))):
            raise ValueError("Invalid transcript word timing")
        if right <= left + 0.001:
            zero += 1
        if left < start - 0.25 or right > end + 0.25:
            outside += 1
    text = cue.get("text")
    if not isinstance(text, str):
        raise ValueError("Invalid transcript text")
    word_rate = len(re.findall(r"\b[\w']+\b", text)) / (end - start)
    return {
        "start_s": start,
        "end_s": end,
        "word_count": len(words),
        "zero_duration_words": zero,
        "words_outside_cue": outside,
        "cue_words_per_second": round(word_rate, 3),
    }


def summarize_source_timing(transcript) -> dict:
    """Observational QA, with no automatic correction or PASS semantics."""
    if transcript is None:
        return {
            "status": "not_measured",
            "source_cues_total": 0,
            "word_timestamps_total": 0,
            "zero_duration_words": 0,
            "review_cue_count": 0,
            "review_cues": [],
        }
    if not isinstance(transcript, dict) or not isinstance(
            transcript.get("cues"), list):
        raise ValueError("Invalid source transcript format")
    cues = transcript["cues"]
    if len(cues) > MAX_CUES:
        raise ValueError("Source transcript cue limit exceeded")
    review = []
    total = 0
    zero_count = 0
    count = 0
    last_start = -1.0
    for i, cue in enumerate(cues, 1):
        item = cue_timing_metrics(cue)
        if item["start_s"] < last_start:
            raise ValueError("Unsorted original transcript cues")
        last_start = item["start_s"]
        total += item["word_count"]
        zero_count += item["zero_duration_words"]
        if total > MAX_WORDS:
            raise ValueError("Source transcript word limit exceeded")
        flags = []
        if (item["word_count"] > 0
                and item["zero_duration_words"] >= 2
                and item["zero_duration_words"] / item["word_count"]
                >= ZERO_WORD_RATIO_REVIEW):
            flags.append("collapsed_word_timestamps")
        if (item["word_count"] > 0
                and item["cue_words_per_second"] > SOURCE_WPS_REVIEW):
            flags.append("high_words_per_second")
        if item["words_outside_cue"]:
            flags.append("word_timing_outside_cue")
        if flags:
            count += 1
            if len(review) < MAX_CUE_DETAILS:
                review.append({
                    "cue": i,
                    "start_s": item["start_s"],
                    "end_s": item["end_s"],
                    "zero_duration_words": item["zero_duration_words"],
                    "word_count": item["word_count"],
                    "cue_words_per_second": item["cue_words_per_second"],
                    "flags": flags,
                })
    return {
        "status": (
            "not_measured" if not total
            else "review_required" if count else "observed_no_timing_flags"
        ),
        "source_cues_total": len(cues),
        "word_timestamps_total": total,
        "zero_duration_words": zero_count,
        "review_cue_count": count,
        "review_cues": review,
        "semantic_accuracy_verified": False,
        "acoustic_accuracy_verified": False,
    }
