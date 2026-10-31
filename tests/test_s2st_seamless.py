"""Bounded audio-to-audio provider contract, independent of heavyweight weights."""
import json
import math
import shutil
import wave

import pytest

from app.experimental import seamless_s2st as s2st


@pytest.fixture
def fake_model(tmp_path):
    root = tmp_path / "weights"
    root.mkdir()
    for name in s2st.REQUIRED_FILES:
        (root / name).write_bytes(b"simulated local file")
    (root / "config.json").write_text(
        json.dumps({"model_type": "seamless_m4t_v2"}), encoding="utf-8"
    )
    return root


@pytest.fixture
def voice(tmp_path):
    source = tmp_path / "en.wav"
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * (16000 * 2))
    return source


def test_incomplete_or_wrong_model_rejected_before_inference(fake_model):
    data = s2st.verify_model(fake_model)
    assert data["model_id"] == s2st.MODEL_ID
    assert data["revision"] == s2st.MODEL_REVISION
    (fake_model / "model-00002-of-00002.safetensors").unlink()
    with pytest.raises(ValueError, match="Incomplete"):
        s2st.verify_model(fake_model)
    (fake_model / "model-00002-of-00002.safetensors").write_bytes(b"file")
    (fake_model / "config.json").write_text('{"model_type":"other"}')
    with pytest.raises(ValueError, match="architecture"):
        s2st.verify_model(fake_model)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_no_intermediate_text_and_immutable_source(fake_model, voice, tmp_path):
    import numpy as np

    sha = s2st.sha256_file(voice)
    seen = []

    def fake_infer(audio, model_dir, device):
        seen.append((len(audio), model_dir, device))
        return np.ones(24000, dtype=np.float32) * 0.125, 24000

    outfile = tmp_path / "ru.wav"
    report = tmp_path / "result.json"
    result = s2st.run(voice, outfile, fake_model, device="cpu",
                      report=report, infer=fake_infer)
    assert seen == [(32000, fake_model, "cpu")]
    assert result["external_intermediate_text_used"] is False
    assert result["architecture_uses_internal_text_tokens"] is True
    assert result["voice_cloning_performed"] is False
    assert result["source_seconds"] == 2.0
    assert result["output_seconds"] == 1.0
    assert s2st.sha256_file(voice) == sha
    assert json.loads(report.read_text()) == result
    with wave.open(str(outfile), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getnframes()) == (
            24000, 1, 24000,
        )
    with pytest.raises(FileExistsError):
        s2st.run(voice, outfile, fake_model, infer=fake_infer)
    with pytest.raises(FileExistsError):
        s2st.run(voice, voice, fake_model, infer=fake_infer)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_rejects_oversized_and_bad_audio(fake_model, tmp_path):
    long_file = tmp_path / "long.wav"
    with wave.open(str(long_file), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * (8000 * 31))
    with pytest.raises(ValueError, match="30 seconds"):
        s2st.decode_utterance(long_file)
    with pytest.raises(FileNotFoundError):
        s2st.decode_utterance(tmp_path / "missing.wav")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_audio_is_decoded_as_16khz_pcm_from_stereo_48khz(tmp_path):
    file = tmp_path / "test.wav"
    with wave.open(str(file), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(b"\x88\x13\x44\x09" * 48000)
    audio, duration = s2st.decode_utterance(file)
    assert len(audio) == 16000
    assert duration == 1.0
    assert math.isfinite(float(audio.mean()))
    assert 0 < float(audio.mean()) < 0.2


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_invalid_synth_pcm_never_writes_output(fake_model, voice, tmp_path):
    import numpy as np

    bad_cases = [
        (np.array([math.nan], dtype=np.float32), 16000),
        (np.array([math.inf], dtype=np.float32), 16000),
        (np.array([2.0], dtype=np.float32), 16000),
        (np.array([1.0], dtype=np.float32), 1000),
        (np.array([], dtype=np.float32), 16000),
    ]
    for index, pair in enumerate(bad_cases):
        outfile = tmp_path / ("bad-%d.wav" % index)
        with pytest.raises(ValueError):
            s2st.run(voice, outfile, fake_model, device="cpu",
                     infer=lambda *args, value=pair: value)
        assert not outfile.exists()


def test_model_check_cli_is_offline_and_no_run_required(fake_model, capsys):
    assert s2st.main([
        "--source", "/nonexistent.wav", "--out", "/new.wav",
        "--model-dir", str(fake_model), "--check-model",
    ]) == 0
    assert s2st.MODEL_REVISION in capsys.readouterr().out
