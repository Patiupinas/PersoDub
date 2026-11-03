"""Local Russian fixed-voice engine uses TTS presets, never source clone prompts."""
import json

import httpx
import pytest

from app.engines.base import SynthesisRequest
from app.engines.silero_ru import SileroRuEngine


def test_assigns_five_fixed_voices_and_writes_job_local_assignment(tmp_path):
    engine = SileroRuEngine(base_url="http://127.0.0.1:3901")
    assigned = engine.assign_voices({}, ["VOICE_01", "VOICE_02", "VOICE_03", "VOICE_04", "VOICE_05"],
                                    str(tmp_path), lambda x: None)
    assert assigned == {
        "VOICE_01": "aidar", "VOICE_02": "baya", "VOICE_03": "kseniya",
        "VOICE_04": "xenia", "VOICE_05": "eugene",
    }
    saved = json.loads((tmp_path / "russian_voice_assignments.json").read_text())
    assert saved["engine"] == "silero_ru"
    assert saved["speaker_to_voice"] == assigned
    assert not list(tmp_path.glob("qwen_ref*.wav"))


def test_same_voice_group_stays_on_same_preset_after_long_timeline(tmp_path):
    engine = SileroRuEngine(base_url="http://127.0.0.1:3901")
    assigned = engine.assign_voices({}, ["VOICE_01", "SPK0", "SPK1"],
                                    str(tmp_path), lambda x: None)
    assert assigned["VOICE_01"] == "aidar"
    assert assigned["SPK0"] != assigned["SPK1"]


def test_synthesize_posts_to_ru_route_without_reference_audio(monkeypatch):
    captured = []

    def mock_post(url, data, timeout):
        captured.append({"url": url, "data": data, "timeout": timeout})
        return httpx.Response(200, content=b"RIFF_SILERO_WAV",
                              headers={"x-audio-duration": "2.500"},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", mock_post)
    engine = SileroRuEngine(base_url="http://127.0.0.1:3901")
    result = engine.synthesize(SynthesisRequest(text="Здравствуйте!", language="Russian",
                                                voice_id="kseniya", duration=2.0))
    assert result.audio_bytes == b"RIFF_SILERO_WAV"
    assert result.duration == 2.5
    assert result.engine_id == "silero_ru"
    assert captured[0]["url"].endswith("/silero/generate")
    assert captured[0]["data"] == {"text": "Здравствуйте!", "speaker": "kseniya"}
    assert captured[0]["timeout"] > 0


def test_engine_rejects_non_russian_requests_and_unknown_preset():
    engine = SileroRuEngine(base_url="http://127.0.0.1:3901")
    with pytest.raises(ValueError, match="Russian"):
        engine.synthesize(SynthesisRequest(text="hello", voice_id="aidar", language="English"))
    with pytest.raises(ValueError, match="voice"):
        engine.synthesize(SynthesisRequest(text="Привет", voice_id="unknown", language="Russian"))


def test_legacy_qwen_stays_independent_of_fixed_voice_engine():
    assert SileroRuEngine.supports_cloning is False
    assert SileroRuEngine.free_retakes is False
    assert SileroRuEngine.adds_stray_sounds is False


def test_native_voice_does_not_run_four_uncalibrated_source_voice_takes(monkeypatch, tmp_path):
    from app import pipeline

    events = []
    captured = {}
    def fake_run(engine, segments, refs, work_dir, **kwargs):
        captured.update(kwargs)
        return "voice.wav"

    monkeypatch.setattr(pipeline, "run_qwen_dub", fake_run)
    engine = SileroRuEngine(base_url="http://127.0.0.1:3901")
    result = pipeline._stage_synthesize(
        [{"start": 0.0, "end": 2.0, "text": "Привет"}],
        [{"start": 0.0, "end": 2.0, "speaker_id": "SPK0"}],
        str(tmp_path), "vocals.wav", "background.wav",
        "Russian", 4, engine, None, events.append,
    )
    assert result == "voice.wav"
    assert captured["n_takes"] == 1
    assert any("one" in line or "1 take" in line for line in events)
