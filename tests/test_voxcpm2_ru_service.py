"""Test the opt-in HTTP boundary without downloading or loading VoxCPM2."""
import io
import wave

import numpy as np
from fastapi.testclient import TestClient

from app.voxcpm2_profile import VOXCPM2_PROFILE
from tools.voxcpm2_ru_server import STYLE_PREFIX, app


class FakeVoiceModel:
    def __init__(self):
        self.calls = []
        self.tts_model = type("TTSModel", (), {"sample_rate": 48000})()

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return np.full(48000, 0.05, dtype=np.float32)


def test_healthy_fixed_voice_service_and_real_wav_response(monkeypatch, tmp_path):
    fake = FakeVoiceModel()
    app.state.model = fake
    app.state.device = "mps"
    app.state.references = {
        "kseniya": tmp_path / "kseniya.wav",
        "aidar": tmp_path / "aidar.wav",
    }
    app.state.reference_sha256 = {"kseniya": "known-sha-a", "aidar": "known-sha-b"}
    try:
        client = TestClient(app)
        status = client.get("/health")
        assert status.status_code == 200
        assert status.json()["profile"] == VOXCPM2_PROFILE
        assert status.json()["ready"] is True
        assert status.json()["references"]["kseniya"] == "known-sha-a"

        wav = client.post("/generate", data={"text": "Сделай вдох.", "speaker": "kseniya"})
        assert wav.status_code == 200
        assert wav.headers["content-type"].startswith("audio/wav")
        assert wav.headers["x-audio-duration"] == "1.000"
        with wave.open(io.BytesIO(wav.content), "rb") as audio:
            assert audio.getnframes() == 48000
            assert audio.getframerate() == 48000
        assert fake.calls[0] == {
            "text": STYLE_PREFIX + "Сделай вдох.",
            "reference_wav_path": str(tmp_path / "kseniya.wav"),
            "cfg_value": 2.0,
            "inference_timesteps": 10,
        }
        assert client.post("/generate", data={"text": "Привет", "speaker": "unknown"}).status_code == 422
        assert client.post("/generate", data={"text": "Привет" * 400, "speaker": "aidar"}).status_code == 422
    finally:
        app.state.model = None


def test_unloaded_optional_service_does_not_claim_ready():
    app.state.model = None
    client = TestClient(app)
    assert client.get("/health").json()["ready"] is False
    assert client.post("/generate", data={"text": "Привет", "speaker": "kseniya"}).status_code == 503
