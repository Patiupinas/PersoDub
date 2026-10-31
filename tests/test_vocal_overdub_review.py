"""Overdub AST observations cannot silently become translation decisions."""

import hashlib
import json

import pytest

from app.audio.overdub import OverdubError
from app.vocal_overdub_review import (
    approved_plan,
    model_suggestions,
    plan_sha,
    record_plan,
    transcript_suggestions,
)

SOURCE = "1" * 64
MODEL_SHA = "d87987744d05c134a9f4294568888832b94ad3a9a2d62a3e3a8de5d793eb1918"
FRAME = 48000
KINDS = ("speech", "singing", "laughing", "crying_baby", "coughing", "sneezing", "breathing")


def observation():
    scores = []
    for winner in ("speech", "singing", "laughing"):
        values = dict.fromkeys(KINDS, 0.02)
        values[winner] = 0.85
        scores.append(values)
    return {
        "schema_version": 1, "source_wav_sha256": SOURCE,
        "sample_rate": FRAME, "total_frames": 8 * FRAME,
        "model": "MIT/ast-finetuned-audioset-12-12-0.447",
        "model_weights_sha256": MODEL_SHA,
        "windows": [
            {"start_frame": 0, "end_frame": 4 * FRAME, "scores": scores[0]},
            {"start_frame": 2 * FRAME, "end_frame": 6 * FRAME, "scores": scores[1]},
            {"start_frame": 4 * FRAME, "end_frame": 8 * FRAME, "scores": scores[2]},
        ],
    }


def test_real_model_class_schema_builds_only_unapproved_overdub_suggestions():
    rows = model_suggestions(8 * FRAME, SOURCE, observation())
    assert rows[0]["hint"] == "speech"
    assert rows[0]["suggested_action"] == "TRANSLATE"
    assert any(row["hint"] == "singing" and row["suggested_action"] == "PRESERVE"
               for row in rows)
    assert any(row["hint"] == "laughing" and row["suggested_action"] == "PRESERVE"
               for row in rows)
    assert all(row["action"] == "REVIEW" for row in rows)
    assert rows[0]["start_frame"] == 0
    assert rows[-1]["end_frame"] == 8 * FRAME
    assert all(a["end_frame"] == b["start_frame"] for a, b in zip(rows, rows[1:]))


def test_transcription_only_fallback_is_unapproved_and_gap_free():
    rows = transcript_suggestions(4 * FRAME, [(0.4, 1.1), (1.5, 2.0)])
    assert rows[0]["hint"] == "unknown"
    assert any(row["hint"] == "speech-cue" for row in rows)
    assert all(row["action"] == "REVIEW" for row in rows)
    assert rows[0]["start_frame"] == 0 and rows[-1]["end_frame"] == 4 * FRAME
    assert all(a["end_frame"] == b["start_frame"] for a, b in zip(rows, rows[1:]))


@pytest.mark.parametrize("changes", [
    {"source_wav_sha256": "f" * 64},
    {"sample_rate": 16000},
    {"model": "unknown"},
    {"model_weights_sha256": "f" * 64},
    {"windows": []},
])
def test_foreign_or_unverified_inference_is_rejected(changes):
    data = observation()
    data.update(changes)
    with pytest.raises(OverdubError):
        model_suggestions(8 * FRAME, SOURCE, data)


def test_observation_timestamp_or_scores_cannot_be_faked():
    for patch in (
        {"start_frame": -1},
        {"end_frame": 100 * FRAME},
        {"scores": {"speech": 1.0}},
        {"scores": {name: float("nan") for name in KINDS}},
    ):
        data = observation()
        data["windows"][0].update(patch)
        with pytest.raises(OverdubError):
            model_suggestions(8 * FRAME, SOURCE, data)


def test_action_plan_is_only_explicit_user_review_not_machine_fields(tmp_path):
    hints = model_suggestions(8 * FRAME, SOURCE, observation())
    with pytest.raises(OverdubError):
        approved_plan(8 * FRAME, SOURCE, hints)
    rows = [
        {"start_frame": row["start_frame"], "end_frame": row["end_frame"],
         "action": "PRESERVE" if row["hint"] == "singing" else "REVIEW"}
        for row in hints
    ]
    plan = approved_plan(8 * FRAME, SOURCE, rows)
    assert plan["events"] == rows
    name = tmp_path / "approved.json"
    record_plan(name, plan)
    assert json.loads(name.read_text()) == plan
    assert plan_sha(plan) == hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with pytest.raises(FileExistsError):
        record_plan(name, plan)


def test_invalid_review_partition_refused():
    with pytest.raises(OverdubError):
        approved_plan(8 * FRAME, SOURCE, [
            {"start_frame": 0, "end_frame": 3 * FRAME, "action": "TRANSLATE"},
            {"start_frame": 4 * FRAME, "end_frame": 8 * FRAME, "action": "PRESERVE"},
        ])
