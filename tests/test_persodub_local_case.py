"""Completed-job benchmark preparation and native-Russian listener validity."""

import json
import struct
import wave

import pytest

from benchmarks.persodub.local_case import prepare_case
from benchmarks.persodub.runner import run_chain


def _write_wav(path, seconds=1.0):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(struct.pack("<h", 4000) * round(16000 * seconds))


def _write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _completed(tmp_path):
    work = tmp_path / "completed"
    work.mkdir()
    (work / "input.mp4").write_bytes(b"private video, no copies")
    (work / "dubbed.mp4").write_bytes(b"output video, no copies")
    _write_json(work / "job.json", {
        "id": "test-job", "status": "done", "result": {"duration": 2.0},
    })
    _write_json(work / "speakers.json", [
        {"start": 0.1, "end": 1.0, "speaker": "S0"},
    ])
    _write_json(work / "lines.json", {"lines": [
        {"i": 0, "start": 0.1, "speaker": "S0", "text": "Пример"},
    ]})
    _write_wav(work / "qwen_line_0.wav", seconds=0.8)
    return work


def test_preparation_never_copies_source_media_or_claims_oracles(tmp_path):
    completed = _completed(tmp_path)
    prepared = tmp_path / "benchmark"
    manifest_path = prepare_case(completed, prepared, "overdub")
    manifest = json.loads(manifest_path.read_text())
    assert manifest["suite_id"] == "local-completed-dub-test-job"
    assert [x["id"] for x in manifest["cases"][:3]] == [
        "final-media", "output-audit", "pre-placement-timing-proxy",
    ]
    assert manifest["cases"][2]["oracle_kind"] == "source_derived_proxy"
    assert len(manifest["cases"]) == 8
    assert {entry.name for entry in prepared.iterdir()} == {
        "source_timing_proxy.json", "dub_timing_proxy.json", "manifest.json",
    }
    assert not list(prepared.glob("*.wav"))
    assert not list(prepared.glob("*.mp4"))
    assert json.loads((prepared / "source_timing_proxy.json").read_text()) == {
        "utterances": [{"start": 0.1, "end": 1.0}],
    }
    assert manifest["cases"][0]["expected_mode"] == "overdub"


def test_running_job_not_accepted_as_completed_case(tmp_path):
    job = _completed(tmp_path)
    record = json.loads((job / "job.json").read_text())
    record["status"] = "running"
    _write_json(job / "job.json", record)
    with pytest.raises(ValueError, match="completed"):
        prepare_case(job, tmp_path / "new", "overdub")
    assert not (tmp_path / "new").exists()


def test_human_accent_requires_three_russian_native_evaluators(tmp_path):
    source = tmp_path / "ratings.json"
    manifest = tmp_path / "cases.json"

    def rank(native_flags):
        _write_json(source, {"ratings": [
            {"rater_id": "native-%d" % i, "native_ru": flag,
             "russian_accent": 5, "voice_likeness": 4,
             "pause_naturalness": 3, "original_mix_audibility": 2}
            for i, flag in enumerate(native_flags)
        ]})
        _write_json(manifest, {"schema_version": 1, "suite_id": "native-listeners",
                               "cases": [{
                                   "id": "listening", "stage": "human_review",
                                   "oracle_kind": "human_gold",
                                   "reference": "ratings.json",
                                   "thresholds": {"russian_accent_mos": {"min": 4}},
                               }]})
        return run_chain(manifest)

    assert rank([True, True])["cases"][0]["status"] == "ERROR"
    report = rank([True, True, False])
    assert report["cases"][0]["status"] == "ERROR"
    report = rank([True, True, True])
    assert report["cases"][0]["status"] == "PASS"
    assert report["cases"][0]["metrics"]["voice_likeness_mos"] == 4
    assert report["production_quality_verified"] is False
    _write_json(source, {"ratings": [
        {"rater_id": "same", "native_ru": True,
         "russian_accent": 5, "voice_likeness": 4,
         "pause_naturalness": 3, "original_mix_audibility": 2}
        for _ in range(3)
    ]})
    assert run_chain(manifest)["cases"][0]["status"] == "ERROR"


def test_identical_asset_cannot_serve_as_own_asr_oracle(tmp_path):
    transcript = tmp_path / "sample.txt"
    transcript.write_text("источник", encoding="utf-8")
    manifest = tmp_path / "cases.json"
    _write_json(manifest, {"schema_version": 1, "suite_id": "self-score",
                           "cases": [{
                               "id": "same", "stage": "asr",
                               "oracle_kind": "human_gold",
                               "reference": "sample.txt",
                               "candidate": "sample.txt",
                           }]})
    report = run_chain(manifest)
    assert report["overall"] == "FAIL"
    assert report["cases"][0]["status"] == "ERROR"
