"""Source timing review must be read-only and never report translation PASS."""
import json

import pytest

from app.source_transcript_quality import (
    cue_timing_metrics,
    summarize_source_timing,
)


def _cue(start=145.64, end=146.72, n=18, zeros=16):
    words = [
        {"start": end, "end": end, "word": f"word{i}"}
        for i in range(zeros)
    ]
    words.extend([
        {"start": start, "end": start + 0.25, "word": "hello"}
        for _ in range(n - zeros)
    ])
    return {
        "start": start, "end": end,
        "text": " ".join(f"word{i}" for i in range(n)),
        "words": words,
    }


def test_source_timestamp_collapse_is_review_not_certified():
    report = summarize_source_timing({"cues": [_cue()]})
    assert report["status"] == "review_required"
    assert report["source_cues_total"] == 1
    assert report["word_timestamps_total"] == 18
    assert report["zero_duration_words"] == 16
    assert report["review_cue_count"] == 1
    assert "collapsed_word_timestamps" in report["review_cues"][0]["flags"]
    assert report["semantic_accuracy_verified"] is False
    assert report["acoustic_accuracy_verified"] is False
    assert "word1" not in json.dumps(report)


def test_normal_timestamps_are_observed_without_review_flag():
    cue = {
        "start": 0.0, "end": 3.0,
        "text": "Speak gently and slowly.",
        "words": [
            {"start": 0.1, "end": 0.4, "word": "Speak"},
            {"start": 0.5, "end": 1.0, "word": "gently"},
            {"start": 1.1, "end": 1.5, "word": "and"},
            {"start": 1.7, "end": 2.3, "word": "slowly"},
        ],
    }
    stats = cue_timing_metrics(cue)
    assert stats["zero_duration_words"] == 0
    report = summarize_source_timing({"cues": [cue]})
    assert report["status"] == "observed_no_timing_flags"
    assert report["review_cue_count"] == 0


def test_no_word_timestamps_does_not_create_false_pass():
    assert summarize_source_timing(None)["status"] == "not_measured"
    report = summarize_source_timing({"cues": [{
        "start": 0, "end": 1, "text": "Hello", "words": [],
    }]})
    assert report["status"] == "not_measured"
    assert report["word_timestamps_total"] == 0


def test_malformed_original_timing_not_silently_accepted():
    with pytest.raises(ValueError, match="Invalid"):
        summarize_source_timing({"cues": [{
            "start": 4, "end": 2, "text": "A", "words": [],
        }]})
    with pytest.raises(ValueError, match="Invalid"):
        summarize_source_timing({"cues": [_cue(n=2, zeros=0), "not a cue"]})


def test_word_timing_outside_cue_is_reviewable_not_ground_truth():
    cue = {
        "start": 10.0, "end": 12.0, "text": "Hello world",
        "words": [
            {"start": 9.0, "end": 10.2, "word": "Hello"},
            {"start": 10.2, "end": 11.1, "word": "world"},
        ],
    }
    report = summarize_source_timing({"cues": [cue]})
    assert report["review_cue_count"] == 1
    assert "word_timing_outside_cue" in report["review_cues"][0]["flags"]
