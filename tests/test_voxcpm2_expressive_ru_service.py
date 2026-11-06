"""FastAPI boundary tests: exact selected style and source WAV upload."""
import hashlib
import io
import sys
import types
import wave

import numpy as np
from fastapi.testclient import TestClient

from app.voxcpm2_profile import (
    VOXCPM2_EXPRESSIVE_PREFIX,
    VOXCPM2_EXPRESSIVE_PROFILE,
)
from tools.voxcpm2_ru_server import app


def wav_bytes(seconds=5, sample_rate=16000):
    dest = io.BytesIO()
    with wave.open(dest, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\0\0" * (sample_rate * seconds))
    return dest.getvalue()


class FakeModel:
    def __init__(self):
        self.tts_model = type("SampleRate", (), {"sample_rate": 48000})()
        self.calls = []

    def generate(self, **kwargs):
        assert "reference_wav_path" in kwargs
        with open(kwargs["reference_wav_path"], "rb") as source:
            self.calls.append({"params": dict(kwargs), "ref_bytes": source.read()})
        return np.full(48000, 0.05, dtype=np.float32)


def test_new_source_voice_endpoint_preserves_the_owner_selected_style(monkeypatch):
    # The test environment intentionally has no torch; the real model service
    # does. Supply only the seeded inference API needed by this fake model.
    seeded = []
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(
        manual_seed=lambda seed: seeded.append(seed),
    ))
    fake = FakeModel()
    app.state.model = fake
    app.state.device = "mps"
    app.state.references = {}
    app.state.reference_sha256 = {}
    source = wav_bytes()
    sha = hashlib.sha256(source).hexdigest()
    try:
        client = TestClient(app)
        health = client.get("/health").json()
        assert health["ready"]
        assert health["source_voice_clone_profile"] == VOXCPM2_EXPRESSIVE_PROFILE
        answer = client.post(
            "/generate-clone",
            data={"text": "А теперь попробуй ещё раз!", "source_sha256": sha,
                  "seed": "42"},
            files={"reference_audio": ("source.wav", source, "audio/wav")},
        )
        assert answer.status_code == 200, answer.text[:250]
        assert answer.headers["x-expression-profile"] == VOXCPM2_EXPRESSIVE_PROFILE
        assert answer.headers["x-source-voice-sha256"] == sha
        assert answer.headers["x-audio-duration"] == "1.000"
        with wave.open(io.BytesIO(answer.content), "rb") as audio:
            assert audio.getframerate() == 48000
            assert audio.getnframes() == 48000
        assert seeded == [42]
        call = fake.calls[0]
        assert call["ref_bytes"] == source
        assert call["params"]["text"] == VOXCPM2_EXPRESSIVE_PREFIX + "А теперь попробуй ещё раз!"
        assert call["params"]["cfg_value"] == 2.0
        assert call["params"]["inference_timesteps"] == 10
    finally:
        app.state.model = None


def test_source_sha_and_audio_validation_do_not_reach_model():
    fake = FakeModel()
    app.state.model = fake
    client = TestClient(app)
    good = wav_bytes()
    sha = hashlib.sha256(good).hexdigest()
    try:
        base = {"text": "Сделай вдох.", "source_sha256": sha}
        assert client.post(
            "/generate-clone", data={**base, "source_sha256": "wrong"},
            files={"reference_audio": ("source.wav", good, "audio/wav")},
        ).status_code == 422
        assert client.post(
            "/generate-clone", data=base,
            files={"reference_audio": ("source.wav", b"corrupt", "audio/wav")},
        ).status_code == 422
        short = wav_bytes(seconds=1)
        assert client.post(
            "/generate-clone",
            data={**base, "source_sha256": hashlib.sha256(short).hexdigest()},
            files={"reference_audio": ("short.wav", short, "audio/wav")},
        ).status_code == 422
        assert not fake.calls
    finally:
        app.state.model = None
    assert client.post(
        "/generate-clone", data=base,
        files={"reference_audio": ("source.wav", good, "audio/wav")},
    ).status_code == 503


def test_real_product_24khz_reference_is_accepted():
    fake = FakeModel()
    app.state.model = fake
    source = wav_bytes(seconds=6, sample_rate=24000)
    digest = hashlib.sha256(source).hexdigest()
    try:
        answer = TestClient(app).post(
            "/generate-clone",
            data={"text": "А теперь попробуй ещё раз!", "source_sha256": digest},
            files={"reference_audio": ("ref24k.wav", source, "audio/wav")},
        )
        assert answer.status_code == 200, answer.text[:250]
        assert fake.calls[0]["ref_bytes"] == source
    finally:
        app.state.model = None
