"""S2ST lab API only accepts reviewed bounded original speech segments."""
import io
import json
import shutil
import subprocess
import wave

import pytest
from fastapi.testclient import TestClient

from app import state
from app.api import s2st_lab
from app.main import app

REAL_POPEN = subprocess.Popen
client = TestClient(app, base_url="http://127.0.0.1")


class FakeProcess:
    pid = 424242
    returncode = None
    commands = []

    def __init__(self, command, **options):
        self.commands.append((command, options))

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15


@pytest.fixture
def project(tmp_path, monkeypatch):
    work = tmp_path / "completed_job"
    work.mkdir()
    (work / "input.mp4").write_bytes(b"original-video-unchanged")
    cues = [
        {"start": 0.0, "end": 2.0, "speaker": "SPK0"},
        {"start": 2.0, "end": 7.0, "speaker": "SPK0"},
        {"start": 7.0, "end": 8.1, "speaker": "SPK1"},
    ]
    (work / "speakers.json").write_text(json.dumps(cues), encoding="utf-8")
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text('{"model_type":"seamless_m4t_v2"}')
    for name in ("model.safetensors.index.json", "model-00001-of-00002.safetensors",
                 "model-00002-of-00002.safetensors"):
        (model / name).write_bytes(b"test-checkpoint")
    python = tmp_path / "python"
    python.write_bytes(b"executable-test-stub")
    settings = {
        "PERSODUB_S2ST_MODEL_DIR": str(model),
        "PERSODUB_S2ST_PYTHON": str(python),
    }
    monkeypatch.setattr(s2st_lab.settings_env, "current_value", lambda key: settings.get(key, ""))
    job = {
        "id": "test-accepted", "kind": "dub", "status": "done", "dub_mode": "local",
        "work_dir": str(work), "result": {"out_path": str(work / "dubbed.mp4")},
    }
    monkeypatch.setattr(state.job_store, "get", lambda jid: job if jid == job["id"] else None)
    fake = FakeProcess
    fake.commands = []
    fake.returncode = None
    monkeypatch.setattr(s2st_lab.subprocess, "Popen", fake)
    monkeypatch.setattr(s2st_lab, "_RUNNING", {})
    return work, settings


def _info():
    response = client.get("/api/dub/jobs/test-accepted/s2st")
    assert response.status_code == 200, response.text
    return response.json()


def _start(source_token, indices=(0, 1), confirmed=True):
    return client.post("/api/dub/jobs/test-accepted/s2st/start", json={
        "source_token": source_token, "indices": list(indices),
        "speech_review_confirmed": confirmed,
    })


def test_unknown_and_nonfinished_projects_have_no_lab(project, monkeypatch):
    assert client.get("/api/dub/jobs/absent/s2st").status_code == 404
    assert client.get("/api/dub/jobs/absent/s2st/status").status_code == 404
    monkeypatch.setattr(state.job_store, "get", lambda jid: {
        "id": jid, "kind": "dub", "status": "running", "work_dir": str(project[0]),
    })
    assert client.get("/api/dub/jobs/running/s2st").status_code == 409


def test_unapproved_source_cues_are_read_only_until_start(project):
    info = _info()
    assert info["model_available"] is True
    assert info["total_cues"] == 3
    assert info["page_size"] == 50
    assert info["max_clips"] == 6
    assert all("action" not in row and "approved" not in row for row in info["cues"])
    assert info["run"] is None
    assert client.get("/api/dub/jobs/test-accepted/s2st?page=1").status_code == 422
    assert client.get("/api/dub/jobs/test-accepted/s2st?page=-1").status_code == 422
    assert not (project[0] / "s2st-lab").exists()


def test_must_explicitly_review_speech_and_bind_to_current_source(project):
    token = _info()["source_token"]
    assert _start(token, confirmed=False).status_code == 422
    assert _start("outdated", confirmed=True).status_code == 409
    assert _start(token, indices=()).status_code == 422
    assert _start(token, indices=(1, 1)).status_code == 422
    assert _start(token, indices=tuple(range(7))).status_code == 422
    assert _start(token, indices=(99,)).status_code == 422
    assert client.post("/api/dub/jobs/test-accepted/s2st/start", json={
        "indices": [True], "source_token": token, "speech_review_confirmed": True,
    }).status_code == 422
    assert not (project[0] / "s2st-lab").exists()
    (project[0] / "speakers.json").write_text(
        json.dumps([{"start": 0, "end": 33.0, "speaker": "SPK0"}]))
    updated = _info()["source_token"]
    assert updated != token
    assert _start(updated, indices=(0,)).status_code == 422


def test_starts_one_child_process_with_offline_weights_and_records_run(project):
    work, _ = project
    original = (work / "input.mp4").read_bytes()
    token = _info()["source_token"]
    response = _start(token, indices=(0, 2))
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "running"
    assert len(run["run_id"]) == 12
    command, options = FakeProcess.commands[0]
    assert command[0].endswith("python")
    assert command[1:4] == ["-u", "-m", "app.experimental.s2st_lab_worker"]
    assert command[command.index("--indices") + 1] == "0,2"
    assert command[command.index("--experiment-dir") + 1].endswith("/data")
    assert options["env"]["HF_HUB_OFFLINE"] == "1"
    assert options["env"]["TRANSFORMERS_OFFLINE"] == "1"
    assert options["start_new_session"] is True
    assert (work / "input.mp4").read_bytes() == original
    state_file = work / "s2st-lab" / "latest.json"
    assert json.loads(state_file.read_text())["run_id"] == run["run_id"]
    status = client.get("/api/dub/jobs/test-accepted/s2st/status").json()["run"]
    assert status["run_id"] == run["run_id"] and status["status"] == "running"
    assert _start(token, indices=(1,)).status_code == 409
    assert len(FakeProcess.commands) == 1


def test_status_recovery_and_only_whitelisted_job_result_downloads(project):
    work, _ = project
    response = _start(_info()["source_token"], indices=(0,))
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    folder = work / "s2st-lab" / run_id
    data = folder / "data"
    data.mkdir()
    (data / "plan.json").write_text(json.dumps({
        "entries": [{"index": 0, "source_clip": "source-000.wav"}],
    }))
    (data / "progress.json").write_text(json.dumps({"total": 1, "done": 1, "state": "done"}))
    (data / "quality-triage.json").write_text(json.dumps({
        "cases": [{"index": 0, "state": "TIMING_CANDIDATE_ONLY"}],
    }))
    (folder / "worker-state.json").write_text('{"state":"done"}')
    for filename in ("source-000.wav", "ru-000.wav", "preview-000.mp4"):
        (data / filename).write_bytes(b"file-" + filename.encode())
    status = client.get("/api/dub/jobs/test-accepted/s2st/status").json()["run"]
    assert status["status"] == "done" and status["progress"]["done"] == 1
    case = status["results"][0]
    assert all(k in case for k in (
        "original_audio_url", "russian_audio_url", "preview_video_url",
    ))
    for key in ("original_audio_url", "russian_audio_url", "preview_video_url"):
        download = client.get(case[key])
        assert download.status_code == 200
        assert download.content.startswith(b"file-")
    assert client.get(
        "/api/dub/jobs/test-accepted/s2st/files/%s/input.mp4" % run_id
    ).status_code == 404
    assert client.get(
        "/api/dub/jobs/test-accepted/s2st/files/%s/ru-001.wav" % run_id
    ).status_code == 404
    assert client.get(
        "/api/dub/jobs/test-accepted/s2st/files/nonsense/source-000.wav"
    ).status_code == 404
    assert not (work / "s2st-lab" / run_id / "input.mp4").exists()


def test_failed_child_process_is_reported_after_restart(project):
    response = _start(_info()["source_token"], indices=(1,))
    assert response.status_code == 200
    FakeProcess.returncode = 1
    s2st_lab._RUNNING.clear()
    result = client.get("/api/dub/jobs/test-accepted/s2st/status").json()["run"]
    assert result["status"] == "error"


def test_model_is_off_until_local_weights_and_runtime_exist(project):
    _, settings = project
    settings["PERSODUB_S2ST_MODEL_DIR"] = "/nonexistent-s2st-model-dir"
    data = _info()
    assert data["model_available"] is False
    assert _start(data["source_token"]).status_code == 409



def test_preview_original_speech_is_current_bounded_real_wav(project, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    work, _ = project
    monkeypatch.setattr(subprocess, "Popen", REAL_POPEN)
    subprocess.run([
        "ffmpeg", "-nostdin", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s=64x64:d=10",
        "-f", "lavfi", "-i", "sine=frequency=400:duration=10",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "mpeg4", "-c:a", "aac", "-t", "10",
        str(work / "actual.mp4"),
    ], check=True, capture_output=True, timeout=30)
    (work / "actual.mp4").replace(work / "input.mp4")
    original_bytes = (work / "input.mp4").read_bytes()
    token = _info()["source_token"]
    path = "/api/dub/jobs/test-accepted/s2st/source/0"
    result = client.get(path, params={"source_token": token})
    assert result.status_code == 200, result.text[:300]
    assert result.headers["cache-control"] == "no-store"
    with wave.open(io.BytesIO(result.content), "rb") as output:
        assert output.getnchannels() == 1
        assert output.getframerate() == 16000
        assert output.getnframes() / 16000 == pytest.approx(2.0, abs=0.1)
    assert (work / "input.mp4").read_bytes() == original_bytes
    assert client.get(path, params={"source_token": "old"}).status_code == 409
    assert client.get(path.replace("/0", "/99"),
                      params={"source_token": token}).status_code == 404
    assert client.get(path).status_code == 422
