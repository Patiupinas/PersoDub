"""Contract of the source-speaker expressive Russian VoxCPM2 voice mode."""
import hashlib
import io
import json
import wave

import httpx
import pytest

from app.engines.base import SynthesisRequest
from app.engines.voxcpm2_expressive_ru import VoxCPM2ExpressiveRuEngine
from app.voxcpm2_profile import (
    MODEL_ID,
    MODEL_REVISION,
    VOXCPM2_EXPRESSIVE_PROFILE,
    VOXCPM2_PROFILE,
)


def source_wav(*, samples=5 * 16000, sample_rate=16000):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\0\0" * samples)
    return output.getvalue()


def service_health(profile=VOXCPM2_EXPRESSIVE_PROFILE):
    return {
        "ready": True,
        "profile": VOXCPM2_PROFILE,
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "source_voice_clone_profile": profile,
        "sample_rate": 48000,
        "device": "mps",
    }


@pytest.fixture
def engine(monkeypatch):
    state = {"health": service_health(), "requests": []}

    def get(url, timeout):
        assert url == "http://127.0.0.1:3909/health"
        return httpx.Response(200, json=state["health"],
                              request=httpx.Request("GET", url))

    def post(url, data, files, timeout):
        assert url == "http://127.0.0.1:3909/generate-clone"
        state["requests"].append((data, files, timeout))
        source = files["reference_audio"][1]
        assert hashlib.sha256(source).hexdigest() == data["source_sha256"]
        return httpx.Response(
            200, content=b"RIFF_RESULT",
            headers={
                "x-audio-duration": "3.750",
                "x-source-voice-sha256": data["source_sha256"],
            }, request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", post)
    return VoxCPM2ExpressiveRuEngine("http://127.0.0.1:3909"), state


def test_approved_profile_requires_an_updated_pinned_service(monkeypatch, engine):
    provider, state = engine
    assert provider.is_available()
    baseline = provider.fingerprint_identity()
    state["health"] = service_health(profile=None)
    assert not provider.is_available()
    with pytest.raises(RuntimeError, match="profile"):
        provider.fingerprint_identity()
    state["health"] = service_health()
    state["health"]["model_revision"] = "other-checkpoint"
    assert not provider.is_available()
    state["health"] = service_health()
    assert provider.fingerprint_identity() == baseline
    monkeypatch.delenv("PERSODUB_VOXCPM2_URL", raising=False)
    assert not VoxCPM2ExpressiveRuEngine().is_available()


def test_assign_two_source_speakers_and_generate_exact_upload(tmp_path, engine):
    provider, state = engine
    raw = source_wav()
    alternative = source_wav(samples=6 * 16000)
    voices = provider.assign_voices(
        {"SPK1": {"wav_bytes": raw, "ref_text": "hello"},
         "SPK2": {"wav_bytes": alternative, "ref_text": "hola"}},
        ["SPK1", "SPK2"], str(tmp_path), lambda _: None,
    )
    assert voices["SPK1"] != voices["SPK2"]
    receipt = json.loads((tmp_path / "source_voice_clone_assignments.json").read_text())
    assert receipt["engine"] == "voxcpm2_expressive_ru"
    assert receipt["source_clone"] is True
    assert receipt["expression_profile"] == VOXCPM2_EXPRESSIVE_PROFILE
    assert receipt["speaker_to_voice"] == voices
    first = provider.synthesize(SynthesisRequest(
        text="А теперь попробуй ещё раз!", voice_id=voices["SPK1"],
        language="Russian", seed=42, duration=3,
    ))
    assert first.audio_bytes == b"RIFF_RESULT"
    assert first.engine_id == provider.id
    assert first.duration == 3.75
    data, files, _ = state["requests"][0]
    assert data["text"] == "А теперь попробуй ещё раз!"
    assert data["seed"] == "42"
    assert files["reference_audio"][1] == raw
    assert voices["SPK1"] == "source-sha256:" + hashlib.sha256(raw).hexdigest()


def test_no_missing_speaker_voices_and_no_untracked_ref_mutations(tmp_path, engine):
    provider, state = engine
    with pytest.raises(ValueError, match="each speaker"):
        provider.assign_voices({}, ["SPK1"], str(tmp_path), lambda _: None)
    with pytest.raises(ValueError, match="at least one"):
        provider.assign_voices({}, [], str(tmp_path), lambda _: None)
    raw = source_wav()
    ref = tmp_path / "voice.wav"
    ref.write_bytes(raw)
    voice_id = provider.clone(ref)
    ref.write_bytes(source_wav(samples=7 * 16000))
    with pytest.raises(ValueError, match="changed"):
        provider.synthesize(SynthesisRequest(
            text="Сделай вдох.", voice_id=voice_id, language="Russian",
        ))
    assert not state["requests"]


def test_reject_foreign_target_invalid_ref_and_missing_voice(tmp_path, engine):
    provider, _ = engine
    ref = tmp_path / "bad.wav"
    ref.write_bytes(b"not a wave")
    with pytest.raises(ValueError, match="valid WAV"):
        provider.clone(ref)
    ref.write_bytes(source_wav(samples=16000))
    with pytest.raises(ValueError, match="3-15"):
        provider.clone(ref)
    with pytest.raises(ValueError, match="Russian"):
        provider.synthesize(SynthesisRequest(text="Hello", voice_id="unknown",
                                             language="English"))
    with pytest.raises(ValueError, match="Unknown"):
        provider.synthesize(SynthesisRequest(text="Привет", voice_id="unknown",
                                             language="Russian"))


def test_a4_fingerprint_binds_expression_profile_and_requires_identity(engine):
    from app.pipeline import _a4_tts_fingerprint

    provider, state = engine
    args = ("source", "approved-plan", [], [], "Russian")
    selected = _a4_tts_fingerprint(
        *args, engine_id=provider.id, engine_identity=provider.fingerprint_identity(),
    )
    generic = _a4_tts_fingerprint(*args, engine_id="qwen3_tts")
    assert selected != generic
    with pytest.raises(ValueError, match="fingerprint"):
        _a4_tts_fingerprint(*args, engine_id=provider.id)
    state["health"]["model_revision"] = "different"
    assert not provider.is_available()


def test_approved_expression_revoices_existing_job_with_exact_same_reference(
    tmp_path, engine, monkeypatch,
):
    import app.engines.base as registry
    from app import qwen_pipeline

    provider, _ = engine
    raw = source_wav()
    assignments = provider.assign_voices(
        {"SPK1": {"wav_bytes": raw, "ref_text": "A calm lesson."}},
        ["SPK1"], str(tmp_path), lambda _: None,
    )
    (tmp_path / "speaker_refs.json").write_text(
        json.dumps({"SPK1": {"ref_text": "A calm lesson."}})
    )
    selected = []
    monkeypatch.setattr(registry, "get_engine", lambda name: (
        provider if name == provider.id else None
    ))

    def fake_synth(engine, segment, voice, language, seed, output, log,
                   label, slot=None):
        selected.append((engine.id, voice, language, segment["text"]))
        return "selected-voice.wav"

    monkeypatch.setattr(qwen_pipeline, "_synth_one", fake_synth)
    made = qwen_pipeline.resynth_one_line(
        str(tmp_path),
        {"i": 0, "speaker": "SPK1", "start": 0, "end": 5},
        "А теперь попробуй ещё раз!", "Russian",
    )
    assert made == "selected-voice.wav"
    assert selected == [(
        provider.id, assignments["SPK1"], "Russian",
        "А теперь попробуй ещё раз!",
    )]
    # A changed source sample cannot silently remap the persisted voice.
    ref = tmp_path / "qwen_ref_SPK1.wav"
    ref.write_bytes(source_wav(samples=6 * 16000))
    with pytest.raises(ValueError, match="reference changed"):
        qwen_pipeline.resynth_one_line(
            str(tmp_path),
            {"i": 0, "speaker": "SPK1", "start": 0, "end": 5},
            "А теперь попробуй ещё раз!", "Russian",
        )


def test_real_product_24khz_voice_reference_is_valid(tmp_path, engine):
    provider, _ = engine
    # PersoDub cut_vocals_span_local outputs 24 kHz mono, not 16/48 kHz.
    product_sample = source_wav(samples=int(6.5 * 24000), sample_rate=24000)
    path = tmp_path / "real-product-24khz.wav"
    path.write_bytes(product_sample)
    assert provider.clone(path) == "source-sha256:" + hashlib.sha256(product_sample).hexdigest()
