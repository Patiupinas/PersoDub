"""Contracts for timestamp-backed multi-ASR review without model inference."""
import csv

import pytest

from benchmarks.persodub.source_asr_evidence import (
    _cue_stats,
    _repetition_hint,
    assemble,
    export_review_csv,
)


def _report(model_sha, heard, coverage, start=145.64):
    return {
        "status": "OBSERVED",
        "independent_ground_truth": False,
        "source": {
            "media_sha256": "fixture-input",
            "review_csv_sha256": "fixture-review",
        },
        "crosscheck_asr": {"checkpoint_sha256": model_sha},
        "rows": [{
            "start_s": start, "end_s": 146.72,
            "source_cues": "20",
            "original_english_asr":
                "sing each note steadily and keep your shoulders loose "
                "while practicing your breathing exercises",
            "independent_asr_text": heard,
            "russian_translation": "Пой мягко и ровно.",
            "ordered_source_word_coverage": coverage,
        }],
    }


def _transcript(zero_words=16):
    words = [
        {"start": 146.72, "end": 146.72, "word": f"w{i}"}
        for i in range(zero_words)
    ]
    words.extend([
        {"start": 145.64, "end": 145.98, "word": "if"},
        {"start": 145.98, "end": 146.72, "word": "you"},
    ])
    return {"cues": [{
        "start": 145.64,
        "end": 146.72,
        "text": "sing each note steadily and keep your shoulders loose "
                "while practicing your breathing exercises",
        "words": words,
    }]}


def test_zero_duration_word_timing_is_detected():
    stats = _cue_stats(_transcript()["cues"][0])
    assert stats["word_count"] == 18
    assert stats["zero_duration_words"] == 16
    assert stats["cue_words_per_second"] > 6


def test_corroborated_source_mismatch_routes_to_source_first(tmp_path):
    small = _report("small-sha", "And then work it through a song.", 0.0)
    base = _report("base-sha", "And then work it to a song.", 0.05556)
    result = assemble(small, base, _transcript())
    assert result["status"] == "OBSERVED"
    assert result["source_transcript_certified"] is False
    assert result["translation_adequacy_certified"] is False
    assert result["summary"]["source_transcript_timing_review"] == 1
    assert result["summary"]["all_original_zero_duration_words"] == 16
    row = result["rows"][0]
    assert row["source_timestamp_zero_duration"] == 16
    assert row["priority_route"] == "SOURCE_TRANSCRIPT_AND_TIMING_REVIEW_FIRST"
    assert "both_crosschecks_disagree_review" in row["diagnostic_flags"]
    assert "source_word_timestamps_collapsed_review" in row["diagnostic_flags"]
    assert row["independent_human_translation_adequacy"] is None

    out = tmp_path / "review.csv"
    export_review_csv(out, result)
    with out.open(encoding="utf-8-sig", newline="") as file:
        items = list(csv.DictReader(file))
    assert len(items) == 1
    assert items[0]["human_corrected_en_source"] == ""
    assert items[0]["human_translation_adequacy_0_to_4"] == ""


def test_different_model_checkpoints_but_same_whisper_family():
    result = assemble(
        _report("a", "And then work it through a song.", 0.0),
        _report("b", "And then work it to a song.", 0.03),
        _transcript(),
    )
    assert result["model_independence"].endswith("same_architecture_family")


def test_no_auto_translation_or_a4_decision_on_repetition():
    assert _repetition_hint("brrrrrrrrrrrrrrrrrrrrrrrrrrrrrr")
    assert _repetition_hint("your abs your abs your abs your abs")
    assert not _repetition_hint("The instructor shows a vocal trill.")

    transcript = {"cues": [{
        "start": 145.64, "end": 146.72,
        "text": "Sing softly.",
        "words": [
            {"start": 145.64, "end": 146.1, "word": "Sing"},
            {"start": 146.1, "end": 146.72, "word": "softly"},
        ],
    }]}
    small = _report("small", "Brrrrrrrrrrrrrrrrrrrrrrrrrrrrrr", 0.5)
    base = _report("base", "Sing softly.", 0.5)
    result = assemble(small, base, transcript)
    assert result["rows"][0]["priority_route"] == "SOURCE_AUDIO_EVENT_REVIEW_FIRST"
    assert "possible_sustained_vocalization_review" in (
        result["rows"][0]["diagnostic_flags"]
    )
    assert result["rows"][0]["translation_adequacy_certified"] is False


def test_stale_source_media_and_inconsistent_rows_rejected():
    small = _report("a", "hello", 0.8)
    base = _report("b", "hello", 0.8)
    base["source"]["media_sha256"] = "changed"
    with pytest.raises(ValueError, match="identity mismatch"):
        assemble(small, base, _transcript())

    base = _report("b", "hello", 0.8)
    base["rows"][0]["russian_translation"] = "Changed"
    with pytest.raises(ValueError, match="identity mismatch"):
        assemble(small, base, _transcript())


def test_cannot_self_compare_same_whisper_checkpoint():
    with pytest.raises(ValueError, match="separately identified"):
        assemble(
            _report("same", "x", 0.8),
            _report("same", "y", 0.8),
            _transcript(),
        )


def test_missing_source_cues_and_bad_probabilities_rejected():
    with pytest.raises(ValueError, match="no source cues"):
        assemble(_report("a", "x", 0.8), _report("b", "x", 0.8), {"cues": []})
    small = _report("a", "x", 0.8)
    base = _report("b", "x", 0.8)
    base["rows"][0]["ordered_source_word_coverage"] = float("nan")
    with pytest.raises(ValueError, match="invalid"):
        assemble(small, base, _transcript())


def test_transcript_with_missing_timing_overlap_is_invalid():
    transcript = {"cues": [{
        "start": 10, "end": 11, "text": "Hello", "words": [],
    }]}
    with pytest.raises(ValueError, match="no original transcript"):
        assemble(_report("a", "x", 0.8), _report("b", "x", 0.8), transcript)


def test_single_decoder_loop_is_not_misclassified_as_vocal_event():
    transcript = {"cues": [{
        "start": 145.64, "end": 146.72,
        "text": "And then work it through a song.",
        "words": [
            {"start": 145.64, "end": 145.93, "word": "And"},
            {"start": 145.93, "end": 146.72, "word": "then"},
        ],
    }]}
    small = _report("small", "And then work it through a song.", 0.9)
    base = _report("base", "your abs your abs your abs your abs", 0.03)
    result = assemble(small, base, transcript)
    row = result["rows"][0]
    assert row["priority_route"] == "ASR_PROBE_DISAGREEMENT_REVIEW_FIRST"
    assert "crosscheck_decoder_repetition_review" in row["diagnostic_flags"]
    assert "possible_sustained_vocalization_review" not in row["diagnostic_flags"]
    assert result["summary"]["audio_event_review"] == 0
    assert result["summary"]["asr_probe_disagreement_review"] == 1
