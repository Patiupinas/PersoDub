"""Read-only live scorer progress is independent of persisted job state."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app import qwen_scoring, state
from app.main import app

client = TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture
def score_progress(tmp_path):
    path = tmp_path / "qwen_scorer_asr_progress.json"

    def update(**changes):
        payload = {
            "schema_version": 1, "phase": "asr",
            "done": 24, "total": 128, "reused": 16,
            "updated_at": time.time(),
        }
        payload.update(changes)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    update()
    return update, str(tmp_path)


def test_read_progress_only_returns_bounded_counters(score_progress):
    update, folder = score_progress
    assert qwen_scoring.read_asr_progress(folder) == {
        "phase": "asr", "done": 24, "total": 128, "reused": 16,
    }
    update(done=1, reused=2)
    assert qwen_scoring.read_asr_progress(folder) is None
    update(phase="unsupported")
    assert qwen_scoring.read_asr_progress(folder) is None
    update(total=bool(128))
    assert qwen_scoring.read_asr_progress(folder) is None
    update(done=128, total=128, reused=0, updated_at=time.time() - 181)
    assert qwen_scoring.read_asr_progress(folder) is None
    update(done=128, total=128, reused=0, updated_at=time.time() + 60)
    assert qwen_scoring.read_asr_progress(folder) is None


def test_bad_progress_is_not_exposed(score_progress):
    update, folder = score_progress
    path = update()
    with open(path, "w", encoding="utf-8") as f:
        f.write("{truncated")
    assert qwen_scoring.read_asr_progress(folder) is None
    with open(path, "w", encoding="utf-8") as f:
        f.write("a" * 5000)
    assert qwen_scoring.read_asr_progress(folder) is None


def test_running_dub_progress_exposed_only_on_single_job(monkeypatch, score_progress):
    _, folder = score_progress
    job = {
        "id": "deadbeef", "kind": "dub", "status": "running",
        "work_dir": folder, "logs": [],
    }
    monkeypatch.setattr(state.job_store, "get", lambda jid: job if jid == "deadbeef" else None)
    response = client.get("/api/dub/jobs/deadbeef")
    assert response.status_code == 200
    payload = response.json()
    assert payload["scorer_progress"] == {
        "phase": "asr", "done": 24, "total": 128, "reused": 16,
    }
    assert "checkpoint" not in str(payload["scorer_progress"])
    job["status"] = "done"
    assert "scorer_progress" not in client.get("/api/dub/jobs/deadbeef").json()
    job["status"] = "running"
    job["kind"] = "separate"
    assert "scorer_progress" not in client.get("/api/dub/jobs/deadbeef").json()
