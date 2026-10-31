"""Real FastAPI local-job Overdub export with explicit reviewed intervals."""

import json
import shutil
import struct
import subprocess
import wave

import pytest
from fastapi.testclient import TestClient

from app import state
from app.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def _line(path, frames=48000, amplitude=11000):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(48000)
        pulse = struct.pack("<hh", amplitude, amplitude)
        for first in range(0, frames, 4800):
            f.writeframesraw(pulse * min(4800, frames - first))


@pytest.fixture
def local_job(tmp_path, monkeypatch):
    source = tmp_path / "input.mp4"
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is required for real end-to-end media tests")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s=160x90:r=25:d=3",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "mpeg4",
        "-c:a", "aac", "-t", "3", str(source),
    ], check=True, capture_output=True)
    _line(tmp_path / "qwen_line_0.wav", 36000)
    (tmp_path / "lines.json").write_text(json.dumps({
        "language": "Russian",
        "lines": [{"i": 0, "start": 0.2, "gain": 1.0}],
    }))
    (tmp_path / "original.srt").write_text(
        "1\n00:00:00,200 --> 00:00:01,000\nOriginal speech\n",
        encoding="utf-8",
    )
    job = {"id": "bench", "kind": "dub", "status": "done",
           "dub_mode": "local", "work_dir": str(tmp_path),
           "result": {"out_path": str(tmp_path / "dubbed.mp4")}}
    original_get = state.job_store.get
    monkeypatch.setattr(
        state.job_store, "get",
        lambda jid: job if jid == "bench" else original_get(jid),
    )
    monkeypatch.delenv("PERSODUB_AST_PYTHON", raising=False)
    monkeypatch.delenv("PERSODUB_AST_MODEL_DIR", raising=False)
    return job


def test_unknown_and_unfinished_projects_not_exportable(monkeypatch):
    assert client.post("/api/dub/jobs/nope/overdub/prepare", json={}).status_code == 404
    monkeypatch.setattr(state.job_store, "get", lambda jid: {
        "id": jid, "kind": "dub", "status": "running",
    })
    assert client.post("/api/dub/jobs/unfinished/overdub/prepare", json={}).status_code == 409


def test_prepare_shows_only_unapproved_cues_and_original_clock(local_job):
    response = client.post("/api/dub/jobs/bench/overdub/prepare", json={"analyze": False})
    assert response.status_code == 200, response.text
    info = response.json()
    assert len(info["source_wav_sha256"]) == 64
    assert info["sample_rate"] == 48000
    assert info["total_frames"] == 3 * 48000
    assert info["ast_available"] is False
    assert info["analysis"] == "not_requested"
    assert info["requires_review"] is True
    assert info["suggestions"][0]["start_frame"] == 0
    assert info["suggestions"][-1]["end_frame"] == info["total_frames"]
    assert all(row["action"] == "REVIEW" for row in info["suggestions"])
    assert any(row["suggested_action"] == "TRANSLATE" for row in info["suggestions"])
    assert all(row["end_frame"] == later["start_frame"]
               for row, later in zip(info["suggestions"], info["suggestions"][1:]))


def test_unconfigured_ast_keeps_suggestions_unapproved(local_job):
    response = client.post("/api/dub/jobs/bench/overdub/prepare", json={"analyze": True})
    assert response.status_code == 200, response.text
    assert response.json()["analysis"] == "model_not_configured"
    assert all(row["action"] == "REVIEW" for row in response.json()["suggestions"])


def test_requires_explicit_review_and_exact_original_source(local_job):
    info = client.post("/api/dub/jobs/bench/overdub/prepare", json={}).json()
    reviewed = {
        "source_wav_sha256": info["source_wav_sha256"],
        "total_frames": info["total_frames"],
        "events": [
            {"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"},
            {"start_frame": 48000, "end_frame": info["total_frames"], "action": "PRESERVE"},
        ],
    }
    assert client.post("/api/dub/jobs/bench/overdub/export", json=reviewed).status_code == 422
    assert client.post("/api/dub/jobs/bench/overdub/export", json={
        **reviewed, "review_confirmed": True, "source_wav_sha256": "f" * 64,
    }).status_code == 422
    assert client.post("/api/dub/jobs/bench/overdub/export", json={
        **reviewed, "review_confirmed": True,
        "events": [{"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"}],
    }).status_code == 422
    output = client.post("/api/dub/jobs/bench/overdub/export", json={
        **reviewed, "review_confirmed": True,
    })
    assert output.status_code == 200, output.text
    data = output.json()
    assert data["receipt"]["audio_tracks"] == ["Overdub", "Original"]
    assert data["receipt"]["action_frames"]["TRANSLATE"] == 48000
    video = client.get(data["download_url"])
    assert video.status_code == 200
    assert len(video.content) > 2000
    assert client.get("/api/dub/jobs/bench/overdub/files/input.mp4").status_code == 404
    assert client.get("/api/dub/jobs/bench/overdub/files/finished-overdub-999.mp4").status_code == 404
    # A second export gets a new filename, without replacing the first.
    second = client.post("/api/dub/jobs/bench/overdub/export", json={
        **reviewed, "review_confirmed": True, "fade_ms": 200,
    })
    assert second.status_code == 200, second.text
    assert second.json()["file"] != data["file"]


def test_explicit_ast_invocation_is_only_a_source_bound_suggestion(local_job, tmp_path, monkeypatch):
    import hashlib
    from pathlib import Path

    import app.api.overdub as overdub_api

    model_dir = tmp_path / "cached-ast"
    model_dir.mkdir()
    isolated_python = tmp_path / "ml-python"
    isolated_python.write_text("synthetic executable for isolated observer test")
    monkeypatch.setattr(
        overdub_api.settings_env, "current_value",
        lambda key: str(isolated_python) if key == "PERSODUB_AST_PYTHON"
        else str(model_dir) if key == "PERSODUB_AST_MODEL_DIR" else "",
    )
    real_subprocess_run = subprocess.run
    observed_calls = []

    def fake_ast_call(cmd, **kwargs):
        if cmd[0] != str(isolated_python):
            return real_subprocess_run(cmd, **kwargs)
        observed_calls.append((cmd, kwargs))
        original = Path(cmd[cmd.index("--original") + 1])
        output = Path(cmd[cmd.index("--output") + 1])
        with wave.open(str(original), "rb") as f:
            total = f.getnframes()
        scores = {
            "speech": 0.94, "singing": 0.01, "laughing": 0.02,
            "crying_baby": 0.01, "coughing": 0.01,
            "sneezing": 0.01, "breathing": 0.02,
        }
        output.write_text(json.dumps({
            "schema_version": 1, "sample_rate": 48000, "total_frames": total,
            "source_wav_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
            "model": "MIT/ast-finetuned-audioset-12-12-0.447",
            "model_weights_sha256":
                "d87987744d05c134a9f4294568888832b94ad3a9a2d62a3e3a8de5d793eb1918",
            "windows": [{"start_frame": 0, "end_frame": total, "scores": scores}],
        }), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(overdub_api.subprocess, "run", fake_ast_call)
    response = client.post("/api/dub/jobs/bench/overdub/prepare", json={"analyze": True})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ast_available"] is True
    assert result["analysis"] == "ast_observations"
    assert len(observed_calls) == 1
    assert all(row["action"] == "REVIEW" for row in result["suggestions"])
    assert all(row["hint"] == "speech" for row in result["suggestions"])
    assert all(row["suggested_action"] == "TRANSLATE" for row in result["suggestions"])


def test_wrong_ast_source_sha_falls_back_to_unapproved_cues(local_job, tmp_path, monkeypatch):
    import app.api.overdub as overdub_api

    model_dir = tmp_path / "cached-ast"
    model_dir.mkdir()
    isolated_python = tmp_path / "ml-python"
    isolated_python.write_text("synthetic")
    monkeypatch.setattr(
        overdub_api.settings_env, "current_value",
        lambda key: str(isolated_python) if key == "PERSODUB_AST_PYTHON"
        else str(model_dir) if key == "PERSODUB_AST_MODEL_DIR" else "",
    )
    real_subprocess_run = subprocess.run

    def fake_bad_observer(cmd, **kwargs):
        if cmd[0] != str(isolated_python):
            return real_subprocess_run(cmd, **kwargs)
        from pathlib import Path

        path = Path(cmd[cmd.index("--output") + 1])
        path.write_text(json.dumps({
            "schema_version": 1, "sample_rate": 48000,
            "source_wav_sha256": "f" * 64, "total_frames": 144000,
            "model": "MIT/ast-finetuned-audioset-12-12-0.447",
            "model_weights_sha256":
                "d87987744d05c134a9f4294568888832b94ad3a9a2d62a3e3a8de5d793eb1918",
            "windows": [{
                "start_frame": 0, "end_frame": 144000,
                "scores": {
                    "speech": 0.99, "singing": 0.0, "laughing": 0.0,
                    "crying_baby": 0.0, "coughing": 0.0,
                    "sneezing": 0.0, "breathing": 0.0,
                },
            }],
        }), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(overdub_api.subprocess, "run", fake_bad_observer)
    result = client.post(
        "/api/dub/jobs/bench/overdub/prepare", json={"analyze": True}
    )
    assert result.status_code == 200
    assert result.json()["analysis"] == "model_failed"
    assert all(r["action"] == "REVIEW" for r in result.json()["suggestions"])


def test_overdub_download_rejects_symlink_outside_job(local_job, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside.mp4")
    outside.write_bytes(b"OTHER PROJECT SOURCE")
    link = tmp_path / "finished-overdub-99.mp4"
    link.symlink_to(outside)
    response = client.get("/api/dub/jobs/bench/overdub/files/finished-overdub-99.mp4")
    assert response.status_code == 404
    outside.unlink()
