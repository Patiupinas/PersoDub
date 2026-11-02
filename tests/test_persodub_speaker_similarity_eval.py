"""Frozen-pair speaker similarity, with explicit negative controls and no model weights."""
import copy
import json
import math
import struct
import wave

import pytest

from benchmarks.persodub.speaker_similarity_eval import (
    _cosine,
    evaluate,
    load_manifest,
)


def _wav(path, frequency, seconds=1.0):
    rate = 16000
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"".join(
            struct.pack("<h", int(1000 * math.sin(
                2 * math.pi * frequency * (n / rate)
            ))) for n in range(round(seconds * rate))
        ))


def fixture(tmp_path):
    media = []
    for i, name in enumerate((
        "old", "clean", "negative",
        "b-old", "b-clean", "b-icl",
        "c-old", "c-clean", "c-icl",
    )):
        path = tmp_path / (name + ".wav")
        _wav(path, 190 + 22 * i, seconds=1.15 if name == "b-clean" else 0.8)
        media.append(path)
    entries = []
    for case in ("b", "c"):
        for name in ("old", "clean", "icl"):
            entries.append({
                "id": case + "_" + name,
                "case_id": case, "variant": name,
                "file": case + "-" + name + ".wav",
                "target": "Та же фраза", "seed": 42,
                "slot_seconds": 1.0,
            })
    manifest = {
        "schema_version": 1,
        "source_language": "en",
        "target_language": "ru",
        "anchors": [{"id": "source_old", "file": "old.wav"},
                    {"id": "source_clean", "file": "clean.wav"}],
        "unrelated_control": {"id": "other_person", "language": "ru",
                              "file": "negative.wav"},
        "candidates": entries,
    }
    filename = tmp_path / "manifest.json"
    filename.write_text(json.dumps(manifest, ensure_ascii=False))
    return filename, manifest


def encoder_map(loaded):
    vectors = {}
    for row in loaded["anchors"]:
        vectors[row["file"]] = [1.0, 0.0, 0.0] if row["id"] == "source_old" else [0.8, 0.6, 0.0]
    vectors[loaded["unrelated_control"]["file"]] = [0, 0, 1]
    for row in loaded["candidates"]:
        vectors[row["file"]] = {
            "old": [1, 0, 0],
            "clean": [0.8, 0.6, 0],
            "icl": [0.9, 0.3, 0],
        }[row["variant"]]
    return lambda path: vectors[path]


def test_controlled_cases_keep_text_seed_and_stable_clock(tmp_path):
    filename, _ = fixture(tmp_path)
    manifest = load_manifest(filename)
    report = evaluate(manifest, encoder_map(manifest))
    assert report["status"] == "OBSERVED"
    assert report["official_cv3_eval_run"] is False
    assert report["human_native_russian_accent_verified"] is False
    assert report["calibrated_similarity_acceptance"] is False
    assert report["speaker_similarity_model_selection_validated"] is False
    assert report["cross_language_control_result"] == "UNVERIFIED_SINGLE_CONTROL"
    assert report["unrelated_control_closer_cases"] == 0
    assert report["target_cases"] == 2
    assert report["two_source_anchors_cosine"] == 0.8
    assert all(x == 0.0 for x in report["source_vs_unrelated_cosines"].values())
    assert set(report["by_variant"]) == {"old", "clean", "icl"}
    assert all(record["samples"] == 2 for record in report["by_variant"].values())
    assert report["by_variant"]["old"]["mean_source_cosine"] == 0.9
    assert report["by_variant"]["clean"]["mean_source_cosine"] == 0.9
    assert report["by_variant"]["clean"]["source_slot_overruns"] == 1
    assert report["by_variant"]["icl"]["source_slot_overruns"] == 0
    assert all(record["file_sha256"] for record in report["cases"])
    assert len({record["id"] for record in report["cases"]}) == 6


@pytest.mark.parametrize(("field", "change", "match"), [
    ("version", lambda d: d.update(schema_version=2), "version"),
    ("missing_lang", lambda d: d.pop("source_language"), "source, RU target"),
    ("wrong_lang", lambda d: d.update(source_language="ru"), "source, RU target"),
    ("wrong_control", lambda d: d["unrelated_control"].update(language="en"), "RU control"),
    ("one_anchor", lambda d: d["anchors"].pop(), "two"),
    ("dup_anchor", lambda d: d["anchors"][1].update(file="old.wav"), "multiple independent"),
    ("dup_control", lambda d: d["unrelated_control"].update(file="old.wav"), "multiple independent"),
    ("missing", lambda d: d["candidates"][0].update(file="gone.wav"), "gone.wav"),
    ("mismatched_text", lambda d: d["candidates"][0].update(target="Новый текст"), "identical target"),
    ("mismatched_seed", lambda d: d["candidates"][0].update(seed=43), "identical target"),
    ("mismatched_slot", lambda d: d["candidates"][0].update(slot_seconds=3.0), "identical target"),
    ("duplicate_variant", lambda d: d["candidates"][0].update(variant="clean"), "distinct variants"),
    ("unequal_variants", lambda d: d["candidates"][-1].update(variant="other"), "same controlled variants"),
    ("overlong_source", lambda d: d["anchors"][0].update(file="manifest.json"), "WAV files only"),
])
def test_rejects_inconsistent_or_nonindependent_benchmarks(tmp_path, field, change, match):
    filename, raw = fixture(tmp_path)
    modified = copy.deepcopy(raw)
    change(modified)
    filename.write_text(json.dumps(modified, ensure_ascii=False))
    with pytest.raises((ValueError, FileNotFoundError), match=match):
        load_manifest(filename)


def test_bad_embedding_dimensions_nan_and_zero_norm_rejected():
    assert _cosine([1, 0, 0], [1, 0, 0]) == 1.0
    assert _cosine([1, 0, 0], [0, 1, 0]) == 0.0
    for left, right in [
        ([1], [1]), ([1, 1], [1]), ([0, 0], [0, 1]),
        ([1, float("nan")], [0, 1]),
        ([1, float("inf")], [1, 0]),
    ]:
        with pytest.raises(ValueError):
            _cosine(left, right)


def test_control_has_no_vocal_human_pass_even_for_perfect_encoder(tmp_path):
    filename, _ = fixture(tmp_path)
    manifest = load_manifest(filename)
    output = evaluate(manifest, lambda file: [0.5, 0.5, 0.5])
    assert output["human_speaker_likeness_verified"] is False
    assert output["two_source_anchors_cosine"] == 1.0
    assert output["source_vs_unrelated_cosines"]["source_clean"] == 1.0
    assert output["calibrated_similarity_acceptance"] is False
    assert output["speaker_similarity_model_selection_validated"] is False
    assert output["cross_language_control_result"] == "CONFLICTING_LANGUAGE_OR_SPEAKER_PROXY"
    assert output["unrelated_control_closer_cases"] == 6
