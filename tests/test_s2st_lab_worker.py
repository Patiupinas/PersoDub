"""Real FFmpeg and model-session-isolated S2ST worker verification."""
import json
import shutil
import subprocess
import wave

import pytest

from app.experimental.s2st_lab_worker import execute
from app.experimental.seamless_batch import run_batch
from app.experimental.seamless_s2st import REQUIRED_FILES, sha256_file


class FakeSession:
    starts = 0
    calls = 0
    closes = 0

    def __init__(self, model_dir, device):
        type(self).starts += 1

    def __call__(self, audio, model_dir, device):
        import numpy as np

        type(self).calls += 1
        signal = (0.12 * np.sin(
            np.arange(16000, dtype=np.float32) * (2 * np.pi * 400 / 16000)
        )).astype(np.float32)
        return signal, 16000

    def close(self):
        type(self).closes += 1


@pytest.fixture(autouse=True)
def session_count():
    FakeSession.starts = 0
    FakeSession.calls = 0
    FakeSession.closes = 0


@pytest.fixture
def media_job(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required for source-bound rendering")
    job = tmp_path / "completed"
    job.mkdir()
    subprocess.run([
        "ffmpeg", "-nostdin", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s=120x80:r=12:d=4",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "mpeg4", "-c:a", "aac", "-t", "4", str(job / "input.mp4"),
    ], capture_output=True, check=True, timeout=30)
    (job / "speakers.json").write_text(json.dumps([
        {"start": 0.4, "end": 2.4, "speaker": "SPK0"},
        {"start": 2.6, "end": 3.5, "speaker": "SPK1"},
    ]))
    return job


@pytest.fixture
def fake_model(tmp_path):
    root = tmp_path / "model"
    root.mkdir()
    for name in REQUIRED_FILES:
        (root / name).write_bytes(b"model-stub")
    (root / "config.json").write_text('{"model_type":"seamless_m4t_v2"}')
    return root


def test_worker_produces_source_preserving_two_track_preview_only_for_timing_pass(
    media_job, fake_model, tmp_path,
):
    outer = tmp_path / "run"
    outer.mkdir()
    dest = outer / "data"
    sha = sha256_file(media_job / "input.mp4")

    def batch_with_stub(folder, model_dir, device):
        return run_batch(folder, model_dir, device,
                         session_factory=FakeSession)

    outcome = execute(
        media_job, [0, 1], dest, fake_model, device="cpu",
        batch_fn=batch_with_stub,
    )
    assert outcome["state"] == "done"
    assert outcome["completed_segments"] == 2
    assert outcome["generated_previews"] == [0]
    assert outcome["skipped_previews"] == [1]
    assert outcome["review_required"] == 1
    assert (FakeSession.starts, FakeSession.calls, FakeSession.closes) == (1, 2, 1)
    assert sha256_file(media_job / "input.mp4") == sha
    assert json.loads((outer / "worker-state.json").read_text())["state"] == "done"
    assert (dest / "ru-001.wav").exists()
    assert not (dest / "preview-001.mp4").exists()
    assert (dest / "preview-000.mp4").stat().st_size > 2000
    record = json.loads((dest / "preview-000.json").read_text())
    assert record["tracks"] == ["Overdub", "Original"]
    r = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
        "-of", "json", str(dest / "preview-000.mp4"),
    ], capture_output=True, text=True, check=True)
    assert [s["codec_type"] for s in json.loads(r.stdout)["streams"]].count("audio") == 2
    with wave.open(str(dest / "ru-000.wav"), "rb") as decoded:
        assert decoded.getframerate() == 16000


def test_preparation_failure_remains_visible_in_persistent_worker_status(
    media_job, fake_model, tmp_path,
):
    outer = tmp_path / "run"
    outer.mkdir()
    dest = outer / "data"

    def failing_prepare(*args):
        raise ValueError("Simulated source version changed")

    with pytest.raises(ValueError, match="source version changed"):
        execute(media_job, [0], dest, fake_model, device="cpu",
                prepare_fn=failing_prepare)
    status = json.loads((outer / "worker-state.json").read_text())
    assert status["state"] == "error"
    assert status["error_type"] == "ValueError"
    assert status["finished_at"] > 0
    assert not dest.exists()
    with pytest.raises(FileExistsError, match="Worker state already"):
        execute(media_job, [0], dest, fake_model, device="cpu",
                prepare_fn=failing_prepare)


def test_preview_error_never_discards_completed_russian_audio(
    media_job, fake_model, tmp_path,
):
    outer = tmp_path / "run"
    outer.mkdir()
    dest = outer / "data"

    def batch_stub(folder, model_dir, device):
        return run_batch(folder, model_dir, device,
                         session_factory=FakeSession)

    def failed_preview(*args):
        raise RuntimeError("Simulated FFmpeg preview error")

    result = execute(media_job, [0], dest, fake_model, device="cpu",
                     batch_fn=batch_stub, preview_fn=failed_preview)
    assert result["state"] == "done"
    assert result["generated_previews"] == []
    assert result["skipped_previews"] == [0]
    assert (dest / "ru-000.wav").exists()
    assert (dest / "quality-triage.json").exists()
