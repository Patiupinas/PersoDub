"""The Home screen's project-card thumbnail: a small JPEG made from a job's
own video with real ffmpeg (a tiny generated clip, no network, no mocked
subprocess -- the point of this route is what ffmpeg actually draws)."""
import os
import subprocess as sp
import time

import pytest
from fastapi.testclient import TestClient

from app import state
from app.api import _launch as launch_api
from app.api import dub as dub_api
from app.main import app
from tests.marks import needs_ffmpeg

client = TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture(autouse=True)
def _all_engines_available(monkeypatch):
    monkeypatch.setattr(launch_api, "missing_models", lambda *a, **kw: [])


def _tiny_video(tmp_path) -> bytes:
    """A 1-second, 64x64 clip made with ffmpeg's own test source -- real,
    decodable video bytes, fast to generate and tiny to carry around."""
    out = tmp_path / "tiny.mp4"
    r = sp.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=size=64x64:rate=5:duration=1",
                "-pix_fmt", "yuv420p", str(out)],
               capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out.read_bytes()


def _queued_job(monkeypatch, tmp_path):
    """A job whose input.mp4 is a real tiny video, with the (slow, heavy)
    dubbing pipeline itself faked out -- the thumbnail route only ever reads
    the uploaded video, never the finished dub."""
    monkeypatch.setattr(dub_api, "run_dub", lambda **kw: {
        "job_id": "x", "out_path": kw["out_path"], "num_segments": 1})
    video = _tiny_video(tmp_path)
    r = client.post("/api/dub/start", files={"video": ("v.mp4", video, "video/mp4")},
                    data={"language": "Korean", "language_code": "ko"})
    assert r.status_code == 200, r.text
    return r.json()["job_id"]


def test_unknown_job_is_404():
    assert client.get("/api/dub/jobs/nope/thumb").status_code == 404


def test_a_job_with_no_video_yet_is_404(monkeypatch):
    jid = state.job_store.create()
    assert client.get(f"/api/dub/jobs/{jid}/thumb").status_code == 404


@needs_ffmpeg
def test_thumb_is_a_real_jpeg_drawn_from_the_video(monkeypatch, tmp_path):
    jid = _queued_job(monkeypatch, tmp_path)
    r = client.get(f"/api/dub/jobs/{jid}/thumb")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content[:2] == b"\xff\xd8"  # a JPEG's own magic bytes
    assert len(r.content) > 100


@needs_ffmpeg
def test_thumb_is_cached_after_the_first_draw(monkeypatch, tmp_path):
    jid = _queued_job(monkeypatch, tmp_path)
    r1 = client.get(f"/api/dub/jobs/{jid}/thumb")
    made_at = os.path.getmtime(
        os.path.join(state.job_store.get(jid)["work_dir"], "thumb.jpg"))
    time.sleep(0.05)
    r2 = client.get(f"/api/dub/jobs/{jid}/thumb")
    assert r1.content == r2.content
    assert os.path.getmtime(
        os.path.join(state.job_store.get(jid)["work_dir"], "thumb.jpg")) == made_at
