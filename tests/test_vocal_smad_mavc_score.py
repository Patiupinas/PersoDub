"""Deterministic replay and rejection of broken source-clock evidence."""
import copy
import json
from pathlib import Path

import pytest

from app.vocal_smad_mavc_score import SMADScoringError, score_clip, score_snapshot

SNAPSHOT = Path(__file__).resolve().parents[1] / "docs/vocal-mavc100-smad-pilot/observations.json"


def load():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_actual_model_selected_source_clips_replay():
    result = score_snapshot(load())
    total = result["aggregate"]
    assert total["gold_speech_samples"] == 1009680
    assert total["gold_singing_samples"] == 2364768
    assert total["gold_singing_predicted_speech_samples"] == 0
    assert total["gold_singing_predicted_singing_samples"] == 1559088
    assert total["gold_speech_predicted_speech_samples"] == 121056
    assert total["gold_speech_predicted_singing_samples"] == 367008
    assert total["singing_events"] == 13
    assert total["singing_events_touched_by_predicted_speech"] == 0
    assert total["clipped_published_silence_tail_samples"] == 4320
    assert total["speech_recall"] == 0.1198954
    assert total["singing_recall"] == 0.6592985
    assert total["speech_mislabeled_singing_rate"] == 0.3634894
    assert len(result["clips"]) == 3
    assert sum(len(clip["smad_cells"]) for clip in load()["clips"]) == 90


def test_half_open_sample_boundary():
    case = {"total_samples": 3000,
            "smad_cells": ["speech_music", "singing_music", "none"],
            "gold_events_ms": [["speech", 500, 1500], ["singing", 1500, 2500]]}
    result = score_clip(case, 1000)
    assert result["gold_speech_predicted_speech_samples"] == 500
    assert result["gold_speech_predicted_singing_samples"] == 500
    assert result["gold_singing_predicted_singing_samples"] == 500


@pytest.mark.parametrize("bad", [
    [["speech", 0, 1000], ["singing", 900, 2000]],
    [["singing", 1000, 2000], ["speech", 0, 1000]],
    [["speech", 0, 1000], ["singing", 1000, 3001]],
    [["speech", 0, 1000], ["singing", 1000, 1000]],
    [["speech", True, 1000], ["singing", 1000, 2000]],
    [["speech", 0, 1000], ["silence", 1000, 3200]],
])
def test_invalid_gold_rejected(bad):
    item = {"total_samples": 3000, "smad_cells": ["speech_noise", "singing_music", "none"],
            "gold_events_ms": bad}
    with pytest.raises(SMADScoringError):
        score_clip(item, 1000)


@pytest.mark.parametrize("field,bad", [
    ("schema_version", 2), ("model", "unknown"),
    ("source", "model-self-generated-gold"),
    ("grid_seconds", 4), ("receptive_field_seconds", 1),
    ("model_sha256", "missing"), ("model_revision", "missing"),
    ("clips", []),
])
def test_invalid_manifest_rejected(field, bad):
    manifest = load()
    manifest[field] = bad
    with pytest.raises(SMADScoringError):
        score_snapshot(manifest)


def test_duplicate_source_not_counted_twice():
    manifest = load()
    manifest["clips"][1] = copy.deepcopy(manifest["clips"][0])
    with pytest.raises(SMADScoringError):
        score_snapshot(manifest)


def test_unknown_model_cell_rejected():
    manifest = load()
    manifest["clips"][0]["smad_cells"][0] = "invented-class"
    with pytest.raises(SMADScoringError):
        score_snapshot(manifest)
