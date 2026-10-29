"""Gold/predicted interval benchmarks without media/model dependencies."""

import json
import os
import subprocess
import sys

import pytest

from app.vocal_benchmark import BenchmarkError, score_vocal_decisions
from app.vocal_decisions import DecisionValidationError


def span(action, start, end, name):
    part = {"segment_id": name, "start_sample": start, "end_sample": end, "action": action}
    if action == "TRANSLATE":
        part.update(source_language="de", source_text="Bitte singen.")
    if action == "REVIEW":
        part.update(reason="ambiguous exercise")
    if action == "PRESERVE":
        part.update(reason="vocal demo")
    return part


def manifest(parts, total=12, **kwargs):
    result = {"schema_version": 1, "source_sha256": "a" * 64,
              "pcm_sha256": "b" * 64, "sample_rate": 48000,
              "total_samples": total, "segments": parts,
              "model_revisions": {"model": "fixed-revision"}}
    result.update(kwargs)
    return result


def reference():
    return manifest([span("TRANSLATE", 0, 4, "speech"),
                     span("PRESERVE", 4, 8, "vowel"),
                     span("REVIEW", 8, 12, "uncertain")])


def test_identical_labels_all_correct_and_empty_predictions_not_inflated():
    same = reference()
    report = score_vocal_decisions(same, same)
    assert report["total_samples"] == 12
    assert report["vocal_preservation"]["zero_corrupted_vocal_segments"] is True
    assert report["vocal_preservation"]["safe_or_review_fraction"] == 1.0
    assert report["speech_utility"]["recall"] == 1.0
    assert report["speech_utility"]["precision"] == 1.0
    assert report["predicted_review"]["samples"] == 4
    assert report["confusion_samples"]["PRESERVE"]["PRESERVE"] == 4
    assert report["confusion_samples"]["REVIEW"]["REVIEW"] == 4


def test_single_sample_wrongly_translated_vowel_detected():
    pred = manifest([span("TRANSLATE", 0, 5, "s"),
                     span("PRESERVE", 5, 8, "v"),
                     span("REVIEW", 8, 12, "r")])
    score = score_vocal_decisions(reference(), pred)
    guard = score["vocal_preservation"]
    assert guard["gold_protected_samples"] == 4
    assert guard["wrongly_translated_samples"] == 1
    assert guard["wrongly_translated_fraction"] == 0.25
    assert guard["safe_or_review_fraction"] == 0.75
    assert guard["affected_gold_segments"] == 1
    assert guard["zero_corrupted_vocal_segments"] is False
    assert score["speech_utility"]["recall"] == 1.0
    assert score["speech_utility"]["precision"] == 4 / 5


def test_ambiguous_audio_wrongly_translated_is_reported_separately():
    predicted = manifest([span("TRANSLATE", 0, 4, "s"),
                          span("PRESERVE", 4, 8, "v"),
                          span("TRANSLATE", 8, 9, "bad"),
                          span("REVIEW", 9, 12, "r")])
    score = score_vocal_decisions(reference(), predicted)
    assert score["ambiguous_safety"]["wrongly_translated_samples"] == 1
    assert score["ambiguous_safety"]["affected_gold_segments"] == 1
    assert score["vocal_preservation"]["zero_corrupted_vocal_segments"] is True
    assert score["speech_utility"]["precision"] == 4 / 5


def test_all_review_is_safe_but_has_zero_translation_coverage():
    pred = manifest([span("REVIEW", 0, 12, "all-uncertain")])
    report = score_vocal_decisions(reference(), pred)
    assert report["vocal_preservation"]["zero_corrupted_vocal_segments"] is True
    assert report["speech_utility"]["recall"] == 0.0
    assert report["speech_utility"]["precision"] is None
    assert report["predicted_review"]["fraction_of_total"] == 1.0


def test_no_protected_gold_produces_undefined_vocal_metric():
    g = manifest([span("TRANSLATE", 0, 12, "all-speech")])
    report = score_vocal_decisions(g, g)
    assert report["vocal_preservation"]["gold_protected_segments"] == 0
    assert report["vocal_preservation"]["safe_or_review_fraction"] is None
    assert report["vocal_preservation"]["zero_corrupted_vocal_segments"] is None


def test_no_speech_gold_produces_undefined_translation_recall():
    g = manifest([span("PRESERVE", 0, 12, "all-vocal")])
    report = score_vocal_decisions(g, g)
    assert report["speech_utility"]["recall"] is None
    assert report["speech_utility"]["precision"] is None
    assert report["predicted_review"]["fraction_of_total"] == 0.0


def test_predicted_revision_provenance_not_confused_with_gold():
    gold = reference()
    pred = reference()
    pred["model_revisions"] = {"classifier": "model@123"}
    report = score_vocal_decisions(gold, pred)
    assert report["predicted_model_revisions"] == {"classifier": "model@123"}


@pytest.mark.parametrize("field,value", [
    ("source_sha256", "c" * 64),
    ("pcm_sha256", "d" * 64),
    ("sample_rate", 44100),
    ("total_samples", 13),
])
def test_mismatched_source_or_timeline_never_scored(field, value):
    wrong = reference()
    wrong[field] = value
    if field == "total_samples":
        wrong["segments"][-1]["end_sample"] = 13
    with pytest.raises(BenchmarkError, match="different source"):
        score_vocal_decisions(reference(), wrong)


def test_preserve_event_count_catches_two_short_segments_touched():
    gold = manifest([span("PRESERVE", 0, 4, "a"),
                     span("TRANSLATE", 4, 8, "speech"),
                     span("PRESERVE", 8, 12, "b")])
    pred = manifest([span("TRANSLATE", 0, 9, "bad"),
                     span("PRESERVE", 9, 12, "rest")])
    report = score_vocal_decisions(gold, pred)
    assert report["vocal_preservation"]["wrongly_translated_samples"] == 5
    assert report["vocal_preservation"]["affected_gold_segments"] == 2
    assert report["speech_utility"]["recall"] == 1.0


def test_mixed_parent_flattening_is_consistent():
    gold = manifest([{"segment_id": "mixed", "start_sample": 0, "end_sample": 12,
                     "action": "MIXED", "children": reference()["segments"]}])
    assert score_vocal_decisions(gold, reference())["speech_utility"]["recall"] == 1.0


def test_uncovered_or_overlapping_prediction_rejected_not_silently_scored():
    pred = reference()
    pred["segments"][1]["start_sample"] = 5
    with pytest.raises(DecisionValidationError, match="gap"):
        score_vocal_decisions(reference(), pred)
    pred["segments"][1]["start_sample"] = 3
    with pytest.raises(DecisionValidationError, match="overlap"):
        score_vocal_decisions(reference(), pred)


def test_many_short_intervals_linear_sweep_and_exact_conservation():
    parts = [span("PRESERVE" if i % 2 else "TRANSLATE", i, i + 1, f"gold-{i}")
             for i in range(1500)]
    gold = manifest(parts, total=len(parts))
    pred = manifest([span("REVIEW", 0, len(parts), "all-review")], total=len(parts))
    report = score_vocal_decisions(gold, pred)
    assert report["total_samples"] == 1500
    assert report["vocal_preservation"]["gold_protected_samples"] == 750
    assert sum(sum(row.values()) for row in report["confusion_samples"].values()) == 1500
    assert report["predicted_review"]["samples"] == 1500


def test_cli_json_output_and_strict_exit_codes(tmp_path):
    gold = tmp_path / "gold.json"
    pred = tmp_path / "pred.json"
    gold.write_text(json.dumps(reference()), encoding="utf-8")
    invalid = manifest([span("TRANSLATE", 0, 5, "s"),
                        span("PRESERVE", 5, 8, "v"),
                        span("REVIEW", 8, 12, "r")])
    pred.write_text(json.dumps(invalid), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(__import__("pathlib").Path(__file__).resolve().parents[1]),
                                                      os.environ.get("PYTHONPATH", "")]))
    args = [sys.executable, "-m", "app.vocal_benchmark", "--gold", str(gold),
            "--pred", str(pred)]
    regular = subprocess.run(args, env=env, capture_output=True, text=True, check=False)
    assert regular.returncode == 0
    assert json.loads(regular.stdout)["vocal_preservation"]["wrongly_translated_samples"] == 1
    strict = subprocess.run(args + ["--fail-on-unsafe"], env=env, capture_output=True, text=True, check=False)
    assert strict.returncode == 1
    pred.write_text(json.dumps(reference()), encoding="utf-8")
    safe = subprocess.run(args + ["--fail-on-unsafe"], env=env, capture_output=True, text=True, check=False)
    assert safe.returncode == 0


def test_strict_cli_with_no_gold_preserve_is_inconclusive(tmp_path):
    payload = manifest([span("TRANSLATE", 0, 12, "all-speech")])
    gold, pred = tmp_path / "gold.json", tmp_path / "pred.json"
    gold.write_text(json.dumps(payload), encoding="utf-8")
    pred.write_text(json.dumps(payload), encoding="utf-8")
    args = [sys.executable, "-m", "app.vocal_benchmark", "--gold", str(gold),
            "--pred", str(pred), "--fail-on-unsafe"]
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    assert proc.returncode == 2
    assert "inconclusive" in proc.stderr
