"""A short source causing 33s of made-up speech cannot pass placement QA."""
import json
import math

import pytest

from app.experimental.s2st_quality import assess_candidate, evaluate_experiment


def test_short_utterance_and_hallucination_duration_block_placement():
    result = assess_candidate(1.08, 33.06)
    assert result["state"] == "REVIEW_REQUIRED"
    assert set(result["reasons"]) == {
        "short_source_needs_event_and_speaker_review",
        "translation_overruns_source_slot",
        "extreme_duration_expansion",
    }
    assert not result["translation_accuracy_verified"]
    assert not result["singing_translation_approved"]


def test_provisional_timing_pass_does_not_certify_speech_or_voice():
    result = assess_candidate(8.14, 6.7)
    assert result["state"] == "TIMING_CANDIDATE_ONLY"
    assert result["reasons"] == []
    assert not result["native_russian_accent_verified"]
    assert not result["speaker_similarity_verified"]
    assert not result["translation_accuracy_verified"]


def test_slight_overrun_and_short_source_both_needs_review():
    assert assess_candidate(6.9, 7.46)["reasons"] == [
        "translation_overruns_source_slot",
    ]
    assert assess_candidate(1.4, 1.1)["reasons"] == [
        "short_source_needs_event_and_speaker_review",
    ]


@pytest.mark.parametrize("a,b", [
    (math.nan, 5), (1, math.inf), (1, 0),
    (-1, 1), (None, 1), (True, 3), (1, False),
])
def test_rejects_invalid_clock(a, b):
    with pytest.raises(ValueError):
        assess_candidate(a, b)


def test_research_receipts_do_not_become_ground_truth(tmp_path):
    raw = tmp_path / "clips"
    raw.mkdir()
    (raw / "plan.json").write_text(json.dumps({
        "schema_version": 1,
        "entries": [
            {"index": 3, "source_sha256": "abc", "output_report": "ru-003.json"},
            {"index": 4, "source_sha256": "def", "output_report": "ru-004.json"},
            {"index": 5, "source_sha256": "ghi", "output_report": "ru-005.json"},
        ],
    }))
    (raw / "ru-003.json").write_text(json.dumps({
        "source_sha256": "abc",
        "source_seconds": 5.0,
        "output_seconds": 4.0,
    }))
    (raw / "ru-004.json").write_text(json.dumps({
        "source_sha256": "def",
        "source_seconds": 1.08,
        "output_seconds": 33.06,
    }))
    result = evaluate_experiment(raw)
    assert result["review_required"] == 1
    assert result["not_run"] == 1
    assert result["acceptance_status"] == "NOT_CERTIFIED"
    assert [x["state"] for x in result["cases"]] == [
        "TIMING_CANDIDATE_ONLY", "REVIEW_REQUIRED", "NOT_RUN",
    ]
    (raw / "ru-004.json").write_text(json.dumps({
        "source_sha256": "altered",
        "source_seconds": 1.08,
        "output_seconds": 33.06,
    }))
    with pytest.raises(ValueError, match="does not match"):
        evaluate_experiment(raw)
