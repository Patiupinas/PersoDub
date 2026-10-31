"""Frozen, research-only public-domain vocal lesson pre-annotation snapshot."""

import json
from collections import Counter
from pathlib import Path

PILOT = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "vocal-instruction-pilot"
    / "navy-auto-suggestions.json"
)


def load():
    return json.loads(PILOT.read_text(encoding="utf-8"))


def test_actual_machine_proposals_fully_cover_one_minute_of_derived_audio():
    report = load()
    assert report["schema_version"] == 1
    assert report["artifact_kind"] == "unreviewed_auto_preannotation_suggestions"
    assert report["source_offset_seconds"] == 60
    assert report["sample_rate"] == 16000
    assert report["total_samples"] == 60 * 16000
    assert len(report["decoded_pcm_sha256"]) == 64
    events = report["candidate_events"]
    assert len(events) == 8
    assert events[0]["start_sample"] == 60 * 16000
    assert events[-1]["end_sample"] == 120 * 16000
    assert all(left["end_sample"] == right["start_sample"]
               for left, right in zip(events, events[1:]))
    totals = Counter()
    for event in events:
        assert event["end_sample"] > event["start_sample"]
        totals[event["candidate"]] += event["end_sample"] - event["start_sample"]
    assert dict(totals) == report["sample_totals_by_candidate"]
    assert report["sample_totals_by_candidate"] == {
        "speech_candidate": 224000,
        "uncertain": 656000,
        "vocal_demo_candidate": 80000,
    }


def test_model_provenance_and_independent_evidence_roles_are_preserved():
    report = load()
    models = report["model_sources"]
    assert [record["role"] for record in models] == [
        "acoustic_singing_candidate", "independent_speech_music", "word_timing_only",
    ]
    assert len({record["weights_sha256"] for record in models}) == 3
    assert report["asr_words_count"] == 92
    for event in report["candidate_events"]:
        assert any(part.startswith("smad:") for part in event["evidence"])
        assert any(part.startswith("ina:") for part in event["evidence"])
        assert any(part.startswith("asr:") for part in event["evidence"])
        if event["candidate"] == "vocal_demo_candidate":
            assert "smad:singing_music" in event["evidence"]
            assert "ina:music" in event["evidence"]
        elif event["candidate"] == "speech_candidate":
            assert "ina:speech" in event["evidence"]
            assert "asr:words" in event["evidence"]


def test_machine_prelabels_are_not_accepted_gold_or_translation_permissions():
    report = load()
    assert report["artifact_kind"].startswith("unreviewed_")
    assert not any(key in report for key in ("gold_events", "decisions", "approved"))
    for event in report["candidate_events"]:
        assert "event_type" not in event
        assert "source_text" not in event
        assert "action" not in event
        assert event["candidate"] in {
            "uncertain", "speech_candidate", "vocal_demo_candidate",
        }
    assert "source_text" not in PILOT.read_text(encoding="utf-8")
