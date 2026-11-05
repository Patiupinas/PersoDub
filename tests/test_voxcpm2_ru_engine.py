"""Contract tests for the opt-in Russian VoxCPM2 engine and existing pipeline."""

import json

import httpx
import pytest

from app.engines.base import SynthesisRequest, register_engine
from app.engines.voxcpm2_ru import VOXCPM2_PROFILE, VoxCPM2RuEngine


def _health(*, kseniya="female-sha", aidar="male-sha"):
    return {
        "ready": True,
        "profile": VOXCPM2_PROFILE,
        "model_id": "openbmb/VoxCPM2",
        "model_revision": "32279effe8c19989596f05d353d1447f51d9e915",
        "sample_rate": 48000,
        "device": "cuda",
        "references": {"kseniya": kseniya, "aidar": aidar},
    }


@pytest.fixture
def pilot(monkeypatch):
    state = {"payload": _health(), "posts": []}

    def get(url, timeout):
        assert url == "http://127.0.0.1:3909/health"
        return httpx.Response(200, json=state["payload"], request=httpx.Request("GET", url))

    def post(url, data, timeout):
        state["posts"].append((url, data, timeout))
        return httpx.Response(
            200, content=b"RIFF_VOXCPM_WAV",
            headers={"x-audio-duration": "4.500"}, request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", post)
    return VoxCPM2RuEngine(base_url="http://127.0.0.1:3909"), state


def test_pilot_not_enabled_without_server_url(monkeypatch):
    monkeypatch.delenv("PERSODUB_VOXCPM2_URL", raising=False)
    assert VoxCPM2RuEngine().is_available() is False


def test_exact_profile_and_reference_bank_required(pilot):
    engine, state = pilot
    assert engine.is_available()
    baseline = engine.fingerprint_identity()
    state["payload"] = _health(kseniya="different-ref")
    assert engine.fingerprint_identity() != baseline
    state["payload"] = {**_health(), "profile": "wrong"}
    assert not engine.is_available()
    with pytest.raises(RuntimeError, match="profile"):
        engine.fingerprint_identity()


def test_preserves_speaker_group_ownership_without_source_cloning(tmp_path, pilot):
    engine, state = pilot
    logged = []
    voices = engine.assign_voices({}, ["VOICE_01", "VOICE_02"], str(tmp_path), logged.append)
    assert voices == {"VOICE_01": "kseniya", "VOICE_02": "aidar"}
    manifest = json.loads((tmp_path / "russian_voice_assignments.json").read_text())
    assert manifest["engine"] == "voxcpm2_ru"
    assert manifest["engine_identity"] == engine.fingerprint_identity()
    assert manifest["source_clone"] is False
    assert not list(tmp_path.glob("qwen_ref*.wav"))
    assert logged


def test_pilot_rejects_unvalidated_third_voice(tmp_path, pilot):
    engine, _ = pilot
    with pytest.raises(ValueError, match="two distinct"):
        engine.assign_voices({}, ["VOICE_01", "VOICE_02", "VOICE_03"], str(tmp_path), lambda _: None)
    with pytest.raises(ValueError, match="clon"):
        engine.assign_voices({"VOICE_01": {"wav_bytes": b"bad"}}, ["VOICE_01"], str(tmp_path), lambda _: None)


def test_requests_match_exact_successful_benchmark_profile(pilot):
    engine, state = pilot
    result = engine.synthesize(SynthesisRequest(
        text="Спокойный вдох и плавный выдох.", voice_id="kseniya",
        language="Russian", duration=3.0,
    ))
    assert result.audio_bytes == b"RIFF_VOXCPM_WAV"
    assert result.engine_id == "voxcpm2_ru"
    assert result.duration == 4.5
    assert state["posts"][0][0] == "http://127.0.0.1:3909/generate"
    assert state["posts"][0][1] == {
        "text": "Спокойный вдох и плавный выдох.", "speaker": "kseniya",
    }


def test_rejects_foreign_target_and_unknown_preset(pilot):
    engine, _ = pilot
    with pytest.raises(ValueError, match="Russian"):
        engine.synthesize(SynthesisRequest(text="hello", language="English", voice_id="kseniya"))
    with pytest.raises(ValueError, match="preset"):
        engine.synthesize(SynthesisRequest(text="Привет", language="Russian", voice_id="unknown"))


def test_native_pilot_has_one_take_and_no_source_timbre_scoring(monkeypatch, pilot, tmp_path):
    from app import pipeline

    engine, _ = pilot
    captured = {}

    def fake_run(engine, *args, **kwargs):
        captured.update(kwargs)
        return "voice.wav"

    monkeypatch.setattr(pipeline, "run_qwen_dub", fake_run)
    done = pipeline._stage_synthesize(
        [{"start": 0.0, "end": 3.0, "text": "Привет"}],
        [{"start": 0.0, "end": 3.0, "speaker_id": "SPK0"}],
        str(tmp_path), "vocals.wav", "background.wav",
        "Russian", 4, engine, None, lambda _: None,
    )
    assert done == "voice.wav"
    assert captured["n_takes"] == 1
    assert engine.supports_cloning is False and engine.free_retakes is False


def test_a4_resume_fingerprint_changes_with_voice_bank(pilot):
    from app.pipeline import _a4_tts_fingerprint

    engine, state = pilot
    params = ("source-sha", "plan-sha", [], [], "Russian")
    args = {"engine_id": "voxcpm2_ru", "engine_identity": engine.fingerprint_identity()}
    a = _a4_tts_fingerprint(*params, **args)
    state["payload"] = _health(kseniya="new-female-reference")
    args["engine_identity"] = engine.fingerprint_identity()
    assert a != _a4_tts_fingerprint(*params, **args)
    with pytest.raises(ValueError, match="requires"):
        _a4_tts_fingerprint(*params, engine_id="voxcpm2_ru")
    assert _a4_tts_fingerprint(*params, engine_id="silero_ru") != a


def test_revoice_rejects_changed_reference_identity(monkeypatch, tmp_path, pilot):
    from app import qwen_pipeline

    engine, state = pilot
    engine.assign_voices({}, ["VOICE_01"], str(tmp_path), lambda _: None)
    register_engine(engine)
    path = tmp_path / "russian_voice_assignments.json"
    receipt = json.loads(path.read_text())
    state["payload"] = _health(kseniya="changed")
    entry = {"i": 0, "speaker": "VOICE_01", "start": 0, "end": 3}
    with pytest.raises(ValueError, match="changed"):
        qwen_pipeline.resynth_one_line(str(tmp_path), entry, "Привет", "Russian")
    state["payload"] = _health()
    called = {}

    def fake_synth(engine, seg, voice_id, language, seed, out_path, log, label, slot):
        called["engine"] = engine.id
        called["voice"] = voice_id
        return "made.wav"

    monkeypatch.setattr(qwen_pipeline, "_synth_one", fake_synth)
    assert qwen_pipeline.resynth_one_line(str(tmp_path), entry, "Привет", "Russian") == "made.wav"
    assert called == {"engine": "voxcpm2_ru", "voice": receipt["speaker_to_voice"]["VOICE_01"]}
