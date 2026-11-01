"""HTTP quality audit for actual finished media and separately reviewed Overdub."""

import json

import pytest
from fastapi.testclient import TestClient

from app import dub_quality_audit as quality
from app import state
from app.main import app

client = TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture
def completed_job(tmp_path, monkeypatch):
    (tmp_path / "dubbed.mp4").write_bytes(b"mock-media")
    (tmp_path / "job.json").write_text(json.dumps({
        "id": "quality-job", "status": "done", "dub_mode": "local",
        "result": {"out_path": str(tmp_path / "dubbed.mp4")},
    }))
    job = {
        "id": "quality-job", "kind": "dub", "status": "done",
        "dub_mode": "local", "work_dir": str(tmp_path),
        "result": {"out_path": str(tmp_path / "dubbed.mp4")},
    }
    monkeypatch.setattr(state.job_store, "get",
                        lambda jid: job if jid == "quality-job" else None)
    monkeypatch.setattr(quality, "_media_streams", lambda path: [
        {"codec_type": "video"}, {"codec_type": "audio"},
    ])
    return tmp_path, job


def test_original_dub_quality_read_only_and_not_perceptual(completed_job):
    root, _ = completed_job
    response = client.get("/api/dub/jobs/quality-job/quality")
    assert response.status_code == 200
    report = response.json()
    assert report["job_id"] == "quality-job"
    assert report["output_file"] == "dubbed.mp4"
    assert report["expected_audio_mode"] == "replace"
    assert report["actual_audio_streams"] == 1
    assert report["status"] == "not_perceptually_verified"
    assert len(report["human_review_remaining"]) == 4
    assert not list(root.glob("*quality-report*"))


def test_separately_reviewed_overdub_has_its_own_audio_mode(completed_job, monkeypatch):
    root, _ = completed_job
    (root / "finished-overdub.mp4").write_bytes(b"reviewed-media")
    monkeypatch.setattr(quality, "_media_streams", lambda path: [
        {"codec_type": "video"},
        {"codec_type": "audio", "tags": {"handler_name": "Overdub"},
         "disposition": {"default": 1}},
        {"codec_type": "audio", "tags": {"handler_name": "Original"},
         "disposition": {"default": 0}},
    ])
    response = client.get("/api/dub/jobs/quality-job/quality?file=finished-overdub.mp4")
    assert response.status_code == 200
    report = response.json()
    assert report["expected_audio_mode"] == "overdub"
    assert report["declared_audio_mode"] == "overdub"
    assert report["output_file"] == "finished-overdub.mp4"
    assert report["issues"] == []
    assert report["status"] == "not_perceptually_verified"


def test_two_wrongly_labelled_streams_are_not_reported_as_valid(completed_job, monkeypatch):
    root, _ = completed_job
    (root / "finished-overdub-2.mp4").write_bytes(b"bad-media")
    monkeypatch.setattr(quality, "_media_streams", lambda path: [
        {"codec_type": "video"},
        {"codec_type": "audio", "tags": {"handler_name": "Original"},
         "disposition": {"default": 1}},
        {"codec_type": "audio", "tags": {"handler_name": "Overdub"},
         "disposition": {"default": 0}},
    ])
    report = client.get(
        "/api/dub/jobs/quality-job/quality?file=finished-overdub-2.mp4"
    ).json()
    assert report["status"] == "review_required"
    assert [issue["code"] for issue in report["issues"]] == [
        "overdub_stream_metadata_mismatch"
    ]


@pytest.mark.parametrize("name", [
    "../dubbed.mp4", "input.mp4", "finished-overdub-foo.mp4",
    "finished-overdub.mp4/../dubbed.mp4",
])
def test_output_name_cannot_escape_allowlisted_reviewed_files(completed_job, name):
    response = client.get("/api/dub/jobs/quality-job/quality", params={"file": name})
    assert response.status_code == 422


def test_disallows_missing_or_unfinished_dubbing(completed_job):
    root, job = completed_job
    assert client.get("/api/dub/jobs/unknown/quality").status_code == 404
    job["status"] = "running"
    assert client.get("/api/dub/jobs/quality-job/quality").status_code == 409
    job["status"] = "done"
    response = client.get(
        "/api/dub/jobs/quality-job/quality?file=finished-overdub.mp4"
    )
    assert response.status_code == 404
    (root / "finished-overdub.mp4").symlink_to(root.parent / "not-in-job.mp4")
    assert client.get(
        "/api/dub/jobs/quality-job/quality?file=finished-overdub.mp4"
    ).status_code == 404
