"""Source-bound, real-FFmpeg voice-loudness calibration regressions."""
import audioop
import hashlib
import json
import math
import shutil
import struct
import wave

import pytest

from app.audio.loudness import (
    VOICE_REFERENCE_LUFS,
    SourceLoudnessError,
    measure_overdub_voice_loudness,
)
from app.audio.overdub import OverdubLevels, create_review_plan, render_overdub

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg"), reason="FFmpeg R128 meter required"
)


def tone(path, amplitude, length_s=3, frequency=219):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(48000)
        for offset in range(0, int(length_s * 48000), 4800):
            count = min(4800, int(length_s * 48000) - offset)
            data = b"".join(
                struct.pack(
                    "<hh",
                    int(round(amplitude * math.sin(
                        2 * math.pi * frequency * (offset + i) / 48000
                    ))),
                    int(round(amplitude * math.sin(
                        2 * math.pi * frequency * (offset + i) / 48000
                    ))),
                ) for i in range(count)
            )
            f.writeframesraw(data)
    return path


def voice_rms_db(path, start=0.5, end=2.5):
    with wave.open(str(path), "rb") as f:
        f.setpos(round(start * 48000))
        data = f.readframes(round((end - start) * 48000))
    return 20 * math.log10(max(1.0, audioop.rms(data, 2)) / 32768)


def build_a4(path, source, *, speech_seconds=3):
    plan = create_review_plan(source, path)
    total = plan["total_frames"]
    if speech_seconds * 48000 < total:
        plan["events"] = [
            {"start_frame": 0, "end_frame": speech_seconds * 48000,
             "action": "TRANSLATE"},
            {"start_frame": speech_seconds * 48000,
             "end_frame": total, "action": "PRESERVE"},
        ]
    else:
        plan["events"] = [
            {"start_frame": 0, "end_frame": total, "action": "TRANSLATE"},
        ]
    path.write_text(json.dumps(plan))
    return path


def test_10db_quieter_source_voice_becomes_equally_audible_at_same_requested_gain(tmp_path):
    original = tone(tmp_path / "original.wav", amplitude=0)
    event_plan = build_a4(tmp_path / "a4.json", original)
    baseline_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    levels = OverdubLevels(-16, -16, 25)
    rendered = []
    receipts = []
    for label, amplitude in (("quiet", 4000), ("normal", 12649)):
        voice = tone(tmp_path / f"{label}.wav", amplitude=amplitude)
        before = hashlib.sha256(voice.read_bytes()).hexdigest()
        measured = measure_overdub_voice_loudness(
            voice, tmp_path / f"{label}-voice.json"
        )
        output = tmp_path / f"out-{label}.wav"
        receipt = render_overdub(
            original, voice, event_plan, output,
            levels=levels, voice_calibration=measured,
        )
        assert hashlib.sha256(voice.read_bytes()).hexdigest() == before
        assert receipt["levels"]["dub_under_speech_db"] == -16
        assert receipt["voice_loudness_calibration"]["requested_dub_db"] == -16
        assert receipt["voice_loudness_calibration"]["sum_gain_ceiling_respected"]
        assert measured["reference_voice_lufs"] == VOICE_REFERENCE_LUFS
        rendered.append(voice_rms_db(output))
        receipts.append(measured)
    assert receipts[0]["input_voice_lufs"] < receipts[1]["input_voice_lufs"] - 9
    assert receipts[0]["gain_offset_db"] > receipts[1]["gain_offset_db"] + 9
    assert abs(rendered[0] - rendered[1]) < 0.6
    assert hashlib.sha256(original.read_bytes()).hexdigest() == baseline_hash


def test_voice_loudness_measurement_reused_and_invalidated_on_tts_edit(tmp_path):
    voice = tone(tmp_path / "tts.wav", amplitude=7000)
    cache = tmp_path / "voice-level.json"
    first = measure_overdub_voice_loudness(voice, cache)
    mtime = cache.stat().st_mtime_ns
    assert measure_overdub_voice_loudness(voice, cache) == first
    assert cache.stat().st_mtime_ns == mtime
    tone(voice, amplitude=5000)
    next_value = measure_overdub_voice_loudness(voice, cache)
    assert first["voice_wav_sha256"] != next_value["voice_wav_sha256"]
    assert next_value["voice_wav_sha256"] == hashlib.sha256(voice.read_bytes()).hexdigest()


def test_reject_voice_calibration_bound_to_another_tts_take(tmp_path):
    source = tone(tmp_path / "original.wav", amplitude=4000)
    voice = tone(tmp_path / "voice.wav", amplitude=6000)
    other = tone(tmp_path / "other.wav", amplitude=8000)
    a4 = build_a4(tmp_path / "a4.json", source)
    other_level = measure_overdub_voice_loudness(other, tmp_path / "other.json")
    with pytest.raises(SourceLoudnessError, match="does not match"):
        render_overdub(
            source, voice, a4, tmp_path / "mixed.wav",
            voice_calibration=other_level,
        )
    assert not (tmp_path / "mixed.wav").exists()


def test_no_source_only_voice_is_left_unboosted(tmp_path):
    source = tone(tmp_path / "original.wav", amplitude=5000)
    silent = tone(tmp_path / "silent.wav", amplitude=0)
    calibration = measure_overdub_voice_loudness(
        silent, tmp_path / "silent.json",
    )
    assert calibration["status"] == "NO_MEASURABLE_VOICE"
    assert calibration["gain_offset_db"] == 0
    source_plan = create_review_plan(source, tmp_path / "plan.json")
    assert source_plan["events"][0]["action"] == "REVIEW"
    result = render_overdub(
        source, silent, tmp_path / "plan.json", tmp_path / "out.wav",
        voice_calibration=calibration,
    )
    assert result["voice_loudness_calibration"]["applied_compensation_db"] == 0
    assert hashlib.sha256(source.read_bytes()).hexdigest() == hashlib.sha256(
        (tmp_path / "out.wav").read_bytes()
    ).hexdigest()


def test_gain_ceiling_limits_excess_voice_boost_without_clipping(tmp_path):
    source = tone(tmp_path / "original.wav", amplitude=18000)
    voice = tone(tmp_path / "quiet.wav", amplitude=1000)
    plan = build_a4(tmp_path / "a4.json", source)
    measured = measure_overdub_voice_loudness(voice, tmp_path / "quiet.json")
    assert measured["gain_offset_db"] > 8
    result = render_overdub(
        source, voice, plan, tmp_path / "out.wav",
        levels=OverdubLevels(-16, -2, 25), voice_calibration=measured,
    )
    cal = result["voice_loudness_calibration"]
    assert cal["effective_dub_db"] < 0
    assert cal["applied_compensation_db"] < measured["gain_offset_db"]
    assert cal["sum_gain_ceiling_respected"]
    assert result["levels"]["dub_under_speech_db"] == -2
    with wave.open(str(tmp_path / "out.wav")) as f:
        peak = audioop.max(f.readframes(f.getnframes()), 2)
    assert peak < 32767


def test_corrupt_matching_voice_cache_is_recomputed(tmp_path):
    voice = tone(tmp_path / "tts.wav", amplitude=8000)
    receipt = tmp_path / "voice-level.json"
    first = measure_overdub_voice_loudness(voice, receipt)
    tampered = dict(first)
    tampered["input_voice_lufs"] = 100.0
    receipt.write_text(json.dumps(tampered))
    refreshed = measure_overdub_voice_loudness(voice, receipt)
    assert refreshed == first
    assert json.loads(receipt.read_text()) == first
