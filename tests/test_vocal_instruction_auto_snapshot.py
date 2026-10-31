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



def test_numeric_model_observations_exactly_regenerate_selected_lesson_proposals():
    from app.vocal_annotation_candidates import (
        EventObservation,
        suggest_annotation_candidates,
    )

    evidence_path = PILOT.with_name("navy-observations-numeric.json")
    input_data = json.loads(evidence_path.read_text(encoding="utf-8"))
    expected = load()
    assert input_data["artifact_kind"] == "machine_observation_inputs_without_content"
    assert input_data["pcm_sha256"] == expected["decoded_pcm_sha256"]
    assert input_data["smad_weights_sha256"] == expected["model_sources"][0]["weights_sha256"]
    assert input_data["ina_weights_sha256"] == expected["model_sources"][1]["weights_sha256"]
    assert input_data["whisper_weights_sha256"] == expected["model_sources"][2]["weights_sha256"]

    def observations(items):
        return tuple(EventObservation(**item) for item in items)

    recomputed = suggest_annotation_candidates(
        sample_rate=input_data["sample_rate"],
        total_samples=input_data["total_samples"],
        source_offset_samples=input_data["source_offset_samples"],
        boundary_review_seconds=input_data["boundary_review_seconds"],
        smad=observations(input_data["smad"]),
        ina=observations(input_data["ina"]),
        asr_words=observations(input_data["asr_words"]),
    )
    assert len(recomputed) == len(expected["candidate_events"])
    for actual, archived in zip(recomputed, expected["candidate_events"]):
        assert actual.start_sample == archived["start_sample"]
        assert actual.end_sample == archived["end_sample"]
        assert actual.candidate == archived["candidate"]
        assert actual.evidence == tuple(archived["evidence"])


def test_numeric_observation_bundle_contains_no_transcribed_words_or_audio():
    data = json.loads(PILOT.with_name("navy-observations-numeric.json").read_text())
    assert len(data["smad"]) == 60
    assert len(data["ina"]) == 9
    assert len(data["asr_words"]) == 92
    assert set(data["asr_words"][0]) == {"start_sample", "end_sample", "label"}
    assert set(x["label"] for x in data["asr_words"]) == {"asr_word"}
    assert all(0 <= x["start_sample"] < x["end_sample"] <= data["total_samples"]
               for x in data["asr_words"])
