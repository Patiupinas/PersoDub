"""Replay independently collected MOSS audio hints without model or media."""

import copy
import json
from pathlib import Path

import pytest

from app.vocal_semantic_review import SemanticReviewError, audit_semantic_snapshot

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "docs/vocal-instruction-semantic-pilot/moss-window-observations.json"
PRIOR = ROOT / "docs/vocal-instruction-pilot/navy-auto-suggestions.json"


def load():
    return json.loads(PILOT.read_text(encoding="utf-8"))


def test_real_selected_audio_replay_and_prompt_disagreement_counts():
    report = audit_semantic_snapshot(load())
    assert report["status"] == "unreviewed_machine_evidence_only"
    assert report["windows"] == 10
    assert report["lesson_neutral_agreements"] == 6
    assert report["lesson_neutral_disagreements"] == [
        "uncertain_one", "uncertain_three", "explicit_instruction_hint", "humming_hint"
    ]
    assert report["lesson_alt_context_pairs"] == 6
    assert report["lesson_alt_context_disagreements"] == [
        "control_demo", "uncertain_three", "explicit_instruction_hint", "humming_hint"
    ]
    assert report["repeatability_checks"] == 3
    assert report["nonstandard_first_lines"] == 2
    assert not any(key in report for key in ("action", "decisions", "gold"))


def test_source_identity_and_parent_windows_match_earlier_a1_machine_observations():
    pilot = load()
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    assert pilot["source_raw_pcm_sha256"] == prior["decoded_pcm_sha256"]
    assert pilot["source_wav_sha256"] == prior["wav_sha256"]
    assert pilot["source_offset_samples"] == prior["source_offset_seconds"] * 16000
    assert pilot["sample_rate"] == prior["sample_rate"]
    assert pilot["total_samples"] == prior["total_samples"]
    events = {
        (e["start_sample"], e["end_sample"], e["candidate"])
        for e in prior["candidate_events"]
    }
    uncertain = [
        (a, b) for a, b, label in events if label == "uncertain"
    ]
    parent = [win for win in pilot["windows"] if win["tier"] != "targeted_probe"]
    probes = [win for win in pilot["windows"] if win["tier"] == "targeted_probe"]
    assert len(parent) == 5 and len(probes) == 5
    for win in parent:
        assert (win["start_sample"], win["end_sample"], win["previous_candidate"]) in events
    for win in probes:
        assert any(a <= win["start_sample"] < win["end_sample"] <= b for a, b in uncertain)
    selected_uncertain_samples = sum(
        win["end_sample"] - win["start_sample"]
        for win in parent if win["previous_candidate"] == "uncertain"
    )
    assert selected_uncertain_samples == 40 * 16000


@pytest.mark.parametrize("field,value", [
    ("schema_version", 2),
    ("artifact_kind", "approved_gold"),
    ("status", "Human reviewed gold"),
    ("sample_rate", True),
    ("sample_rate", 0),
    ("source_offset_samples", -1),
    ("total_samples", False),
    ("source_wav_sha256", "not-a-sha"),
])
def test_invalid_root_is_rejected(field, value):
    pilot = load()
    pilot[field] = value
    with pytest.raises(SemanticReviewError):
        audit_semantic_snapshot(pilot)


def test_corrupt_prompt_hash_is_rejected():
    pilot = load()
    pilot["prompts"]["neutral"]["text"] += " extra text"
    with pytest.raises(SemanticReviewError, match="prompt content hash"):
        audit_semantic_snapshot(pilot)


def test_unknown_prompt_or_action_injected_into_window_rejected():
    pilot = load()
    pilot["windows"][0]["action"] = "TRANSLATE"
    with pytest.raises(SemanticReviewError):
        audit_semantic_snapshot(pilot)


def test_invalid_window_clock_is_rejected():
    pilot = load()
    pilot["windows"][0]["start_sample"] = 959999
    with pytest.raises(SemanticReviewError):
        audit_semantic_snapshot(pilot)


def test_duplicate_window_identity_is_rejected():
    pilot = load()
    pilot["windows"][1]["window_id"] = pilot["windows"][0]["window_id"]
    with pytest.raises(SemanticReviewError):
        audit_semantic_snapshot(pilot)


def test_model_label_must_match_first_line():
    pilot = load()
    pilot["windows"][0]["outputs"]["lesson"]["semantic_class"] = "speech"
    with pytest.raises(SemanticReviewError):
        audit_semantic_snapshot(pilot)


def test_non_target_explanation_in_first_line_preserves_format_deviation():
    pilot = load()
    output = pilot["windows"][0]["outputs"]["alt_context"]
    assert output["raw_first_line"] == "NON_TARGET (no human voice)"
    assert not output["format_exact_first_line"]
    output["format_exact_first_line"] = True
    with pytest.raises(SemanticReviewError):
        audit_semantic_snapshot(pilot)


def test_repeatability_result_requires_matching_hash():
    pilot = load()
    pilot["repeatability_checks"][0]["repeat_stdout_sha256"] = "0" * 64
    with pytest.raises(SemanticReviewError):
        audit_semantic_snapshot(pilot)


def test_overlapping_targeted_probes_do_not_become_inferred_pcm_partition():
    pilot = load()
    original = copy.deepcopy(pilot)
    pilot["windows"].reverse()
    assert set(audit_semantic_snapshot(pilot)["lesson_neutral_disagreements"]) == set(
        audit_semantic_snapshot(original)["lesson_neutral_disagreements"]
    )
