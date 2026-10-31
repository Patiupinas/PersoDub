"""Local S2ST batch: source clock, one model load and resumable receipts."""
import json
import shutil
import subprocess
import wave

import pytest

from app.experimental import seamless_batch as batch
from app.experimental.seamless_s2st import REQUIRED_FILES


@pytest.fixture
def model(tmp_path):
    root = tmp_path / "model"
    root.mkdir()
    for name in REQUIRED_FILES:
        (root / name).write_bytes(b"fixture")
    (root / "config.json").write_text('{"model_type":"seamless_m4t_v2"}')
    return root


@pytest.fixture
def job(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg required")
    project = tmp_path / "job"
    project.mkdir()
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=black:s=64x64:d=8",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=8",
        "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(project / "input.mp4"),
    ], capture_output=True, check=True)
    (project / "speakers.json").write_text(json.dumps([
        {"start": 0.1, "end": 1.7, "speaker": "S0"},
        {"start": 3.5, "end": 4.9, "speaker": "S0"},
    ]))
    return project


class FakeSession:
    starts = 0
    calls = 0
    closes = 0
    crash_on_call = None

    def __init__(self, model_dir, device):
        type(self).starts += 1

    def __call__(self, pcm, model_dir, device):
        import numpy as np
        type(self).calls += 1
        if type(self).calls == type(self).crash_on_call:
            raise RuntimeError("Simulated second clip inference failure")
        return np.ones(16000, dtype="float32") * 0.1, 16000

    def close(self):
        type(self).closes += 1


@pytest.fixture(autouse=True)
def reset_fake():
    FakeSession.starts = FakeSession.calls = FakeSession.closes = 0
    FakeSession.crash_on_call = None


def test_prepares_exact_video_segments_without_copying_video(job, tmp_path):
    out = tmp_path / "run"
    metadata = batch.prepare(job, [0, 1], out)
    assert [x["index"] for x in metadata["entries"]] == [0, 1]
    assert all(x["review_state"] == "REVIEW" for x in metadata["entries"])
    assert metadata["singing_translation_approved"] is False
    assert not (out / "input.mp4").exists()
    assert not list(out.glob("*.txt"))
    assert not list(out.glob("ru-*.wav"))
    for index, expected in enumerate((1.6, 1.4)):
        source = out / ("source-%03d.wav" % index)
        with wave.open(str(source), "rb") as f:
            assert f.getframerate() == 16000
            assert f.getnchannels() == 1
            assert f.getnframes() / 16000 == pytest.approx(expected, abs=0.02)


def test_model_session_reused_with_receipts_and_full_replay(job, model, tmp_path):
    out = tmp_path / "run"
    batch.prepare(job, [0, 1], out)
    first = batch.run_batch(out, model, device="cpu", session_factory=FakeSession)
    assert first["state"] == "done"
    assert first["done"] == 2
    assert (FakeSession.starts, FakeSession.calls, FakeSession.closes) == (1, 2, 1)
    assert all((out / ("ru-%03d.wav" % i)).is_file() for i in (0, 1))
    assert all((out / ("ru-%03d.json" % i)).is_file() for i in (0, 1))
    second = batch.run_batch(out, model, device="cpu", session_factory=FakeSession)
    assert second["done"] == 2
    assert second["reused"] == 2
    assert (FakeSession.starts, FakeSession.calls) == (1, 2)


def test_interrupted_batch_continues_only_missing_utterance(job, model, tmp_path):
    out = tmp_path / "run"
    batch.prepare(job, [0, 1], out)
    FakeSession.crash_on_call = 2
    with pytest.raises(RuntimeError, match="Simulated"):
        batch.run_batch(out, model, "cpu", session_factory=FakeSession)
    progress = json.loads((out / "progress.json").read_text())
    assert (progress["done"], progress["failed"], progress["state"]) == (1, 1, "error")
    assert (out / "ru-000.wav").is_file()
    assert not (out / "ru-001.wav").is_file()
    FakeSession.crash_on_call = None
    resume = batch.run_batch(out, model, "cpu", session_factory=FakeSession)
    assert (resume["done"], resume["reused"]) == (2, 1)
    assert FakeSession.calls == 3
    assert FakeSession.closes == 2


def test_source_clips_and_video_bound_to_exact_sha(job, model, tmp_path):
    out = tmp_path / "run"
    batch.prepare(job, [0], out)
    with (out / "source-000.wav").open("ab") as f:
        f.write(b"not source audio")
    with pytest.raises(ValueError, match="clip hash"):
        batch.run_batch(out, model, "cpu", session_factory=FakeSession)
    assert FakeSession.starts == 0


def test_preparation_rejects_invalid_cues(job, tmp_path):
    with pytest.raises(ValueError, match="distinct"):
        batch.prepare(job, [0, 0], tmp_path / "dup")
    with pytest.raises(ValueError, match="outside"):
        batch.prepare(job, [2], tmp_path / "missing")
    with pytest.raises(FileExistsError, match="new"):
        batch.prepare(job, [0], job)
    (job / "speakers.json").write_text(json.dumps([
        {"start": 0, "end": 60, "speaker": "S0"},
    ]))
    with pytest.raises(ValueError, match="30-second"):
        batch.prepare(job, [0], tmp_path / "long")
