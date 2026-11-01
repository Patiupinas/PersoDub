"""COMET probe contracts without loading or downloading checkpoints."""
import hashlib
import json

import pytest

from benchmarks.persodub.translation_comet_probe import (
    assemble_comet_probe,
    verify_inputs,
)
from benchmarks.persodub.translation_controls import evaluate_scores


def _setup(tmp_path):
    fixture = tmp_path / "controls.json"
    cases = [
        {
            "id": f"c{i}",
            "kind": "negation",
            "source": "Sing softly.",
            "faithful": "Пойте тихо.",
            "altered": f"Пойте громко. {i}",
        }
        for i in range(2)
    ]
    fixture.write_text(json.dumps({
        "schema_version": 1, "suite_id": "unit",
        "cases": cases,
    }), encoding="utf-8")
    report = evaluate_scores(
        cases, [0.5, 0.4, 0.8, 0.6],
        embedding_meta={"model": "test"},
        nli_scores=[
            {"symmetric_entailment": x} for x in (0.8, 0.2, 0.7, 0.1)
        ],
        nli_meta={"model": "test"},
    )
    report["inputs"] = {
        "controls_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest()
    }
    return fixture, report


def test_comet_respects_frozen_control_ids_and_scores(tmp_path):
    fixture, original = _setup(tmp_path)
    cases, real = verify_inputs(original, fixture)
    assert len(cases) == 2
    assert not real
    result = assemble_comet_probe(
        original, fixture, [0.9, 0.1, 0.3, 0.7],
        {"model": "fixture"},
    )
    assert result["status"] == "OBSERVED"
    assert result["translation_quality_verified"] is False
    assert result["summary"]["comet_pairwise_wins"] == 1
    assert result["summary"]["comet_missed_control_ids"] == ["c1"]
    assert result["control_cases"][0]["nli_prefers_faithful"] is True


def test_comet_rejects_stale_fixture_and_modified_controls(tmp_path):
    fixture, original = _setup(tmp_path)
    fixture.write_text(fixture.read_text() + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_inputs(original, fixture)
    fixture, original = _setup(tmp_path)
    original["control_cases"][0]["source"] = "Changed"
    with pytest.raises(ValueError, match="identity mismatch"):
        verify_inputs(original, fixture)


def test_comet_rejects_missing_scores_and_nonfinite(tmp_path):
    fixture, original = _setup(tmp_path)
    for scores in ([], [0.1, 0.2, 0.3],
                   [0.1, 0.2, 0.3, float("nan")]):
        with pytest.raises(ValueError, match="score count/value"):
            assemble_comet_probe(original, fixture, scores, {})


def test_comet_stays_unverified_on_real_rows(tmp_path):
    fixture, original = _setup(tmp_path)
    original["real_rows"].append({
        "start_s": 2.0, "end_s": 4.0,
        "source_cues": [1], "translation_cues": [1],
        "source_text": "Hello", "translation_text": "Привет",
        "embedding_score": 0.8,
        "nli": {"symmetric_entailment": 0.75},
    })
    result = assemble_comet_probe(
        original, fixture,
        [0.9, 0.1, 0.5, 0.4, -0.25], {"model": "test"},
    )
    assert result["summary"]["real_scored"] == 1
    assert result["real_rows"][0]["comet_qe_score"] == -0.25
    assert result["real_rows"][0]["nli_symmetric_entailment"] == 0.75
    assert result["translation_quality_verified"] is False
