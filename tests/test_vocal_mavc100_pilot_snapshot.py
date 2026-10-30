"""Frozen model predictions are metadata, not permission to dub vocal lessons."""

import json
from pathlib import Path

import pytest

from app.vocal_mavc100_score import combine_mavc_scores

ROOT = Path(__file__).resolve().parents[1] / "docs" / "vocal-mavc100-pilot"


def _read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("mode", ["smn", "sm"])
def test_frozen_acoustic_score_recomputes_from_frame_counts(mode):
    score = _read(f"ina-{mode}-scores.json")
    assert score["aggregate"] == combine_mavc_scores(score["results"])
    assert score["aggregate"]["clips"] == 3
    assert score["aggregate"]["singing_events"] == 13
    assert score["aggregate"]["clipped_published_silence_tail_samples"] == 3 * 1440
    assert score["aggregate"]["gold_speech_samples"] == 1009680
    assert score["aggregate"]["gold_singing_samples"] == 2364768


@pytest.mark.parametrize("mode", ["smn", "sm"])
def test_frozen_predictions_match_selected_video_and_label_hashes(mode):
    audit = _read("source-label-audit.json")
    pcm = _read("pcm-provenance.json")
    pred = _read(f"ina-{mode}-predictions.json")
    score = _read(f"ina-{mode}-scores.json")

    selected = {entry["clip_id"]: entry for entry in audit["selected"]}
    original = {entry["clip_id"]: entry for entry in pcm}
    predicted = {entry["clip_id"]: entry for entry in pred["clips"]}
    scored = {entry["clip_id"]: entry for entry in score["results"]}
    assert len(selected) == len(original) == len(predicted) == len(scored) == 3
    assert set(selected) == set(original) == set(predicted) == set(scored)
    assert len({entry["source_id"] for entry in audit["selected"]}) == 3
    assert pred["model_sha256"] == score["model_sha256"]
    for clip_id, gold in selected.items():
        assert predicted[clip_id]["source_sha256"] == original[clip_id]["source_mp4_sha256"]
        assert scored[clip_id]["label_sha256"] == gold["annotation_sha256"]
        assert original[clip_id]["decoded_pcm_48000_s16le_stereo_frames"] == 1440000
        assert original[clip_id]["audio_stream"]["start_time"] == "0.000000"
        assert "path" not in original[clip_id]


def test_smn_protects_selected_singing_at_the_expense_of_speech_recall():
    smn = _read("ina-smn-scores.json")["aggregate"]
    assert smn["gold_singing_predicted_speech_samples"] == 0
    assert smn["singing_events_touched_by_predicted_speech"] == 0
    assert smn["gold_speech_predicted_speech_samples"] == 300288


def test_alternate_sm_adds_a_real_singing_false_speech_error():
    smn = _read("ina-smn-scores.json")["aggregate"]
    sm = _read("ina-sm-scores.json")["aggregate"]
    assert sm["gold_singing_predicted_speech_samples"] == 52416
    assert sm["singing_events_touched_by_predicted_speech"] == 1
    assert sm["gold_speech_predicted_speech_samples"] - smn["gold_speech_predicted_speech_samples"] == 12816
    assert sm["gold_speech_samples"] == smn["gold_speech_samples"]
    assert sm["gold_singing_samples"] == smn["gold_singing_samples"]
