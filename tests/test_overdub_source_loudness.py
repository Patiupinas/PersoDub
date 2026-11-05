"""Real-FFmpeg source loudness tests, plus exact source/A4 mixer invariants."""
import hashlib
import json
import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from app.audio.loudness import (
    SOURCE_LOUDNESS_PROFILE,
    SOURCE_TARGET_LUFS,
    SOURCE_TRUE_PEAK_DBTP,
    SourceLoudnessError,
    normalize_overdub_base,
)
from app.audio.overdub import create_review_plan, render_overdub

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg"), reason="FFmpeg is required for R128 normalization"
)


def wav(path, amplitude=1350, seconds=3, frequency=220):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(48000)
        for start in range(0, seconds * 48000, 4800):
            count = min(4800, seconds * 48000 - start)
            payload = b"".join(
                struct.pack(
                    "<hh", int(amplitude * math.sin(2 * math.pi * frequency * (start + i) / 48000)),
                    int(amplitude * math.sin(2 * math.pi * frequency * (start + i) / 48000)),
                ) for i in range(count)
            )
            output.writeframesraw(payload)
    return path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sample(path, t):
    with wave.open(str(path), "rb") as audio:
        audio.setpos(round(t * 48000))
        return struct.unpack("<hh", audio.readframes(1))[0]


def test_r128_two_pass_normalizes_real_weak_source_without_losing_frames(tmp_path):
    original = wav(tmp_path / "input.wav", amplitude=1050, seconds=4)
    original_sha = digest(original)
    normalized = tmp_path / "normalized.wav"
    receipt_file = tmp_path / "r128.json"

    receipt = normalize_overdub_base(original, normalized, receipt_file)

    assert receipt["profile"] == SOURCE_LOUDNESS_PROFILE
    assert receipt["target_lufs"] == SOURCE_TARGET_LUFS
    assert receipt["true_peak_ceiling_dbtp"] == SOURCE_TRUE_PEAK_DBTP
    assert abs(receipt["normalized_integrated_lufs"] - SOURCE_TARGET_LUFS) <= 0.75
    assert receipt["normalized_true_peak_dbtp"] <= SOURCE_TRUE_PEAK_DBTP + 0.2
    assert receipt["input_integrated_lufs"] < receipt["normalized_integrated_lufs"]
    assert receipt["source_frames"] == 4 * 48000
    with wave.open(str(normalized), "rb") as played:
        assert played.getnframes() == receipt["source_frames"]
    assert digest(original) == original_sha
    assert digest(normalized) == receipt["normalized_wav_sha256"]

    # Repeat an alternate gain render without measuring or normalizing again.
    mtime = normalized.stat().st_mtime_ns
    assert normalize_overdub_base(original, normalized, receipt_file) == receipt
    assert normalized.stat().st_mtime_ns == mtime


def test_r128_cache_is_invalidated_when_original_source_changes(tmp_path):
    original = wav(tmp_path / "input.wav", amplitude=1200, seconds=2)
    normalized = tmp_path / "normalized.wav"
    sidecar = tmp_path / "receipt.json"
    a = normalize_overdub_base(original, normalized, sidecar)
    wav(original, amplitude=2100, seconds=2)
    b = normalize_overdub_base(original, normalized, sidecar)
    assert a["source_wav_sha256"] != b["source_wav_sha256"]
    assert b["source_wav_sha256"] == digest(original)
    assert b["normalized_wav_sha256"] == digest(normalized)


def test_normalized_source_matches_original_a4_plan_and_preserves_selection(tmp_path):
    source = wav(tmp_path / "source.wav", amplitude=1400, seconds=3)
    original_sha = digest(source)
    normalized = tmp_path / "normalized.wav"
    sidecar = tmp_path / "receipt.json"
    receipt = normalize_overdub_base(source, normalized, sidecar)
    voice = wav(tmp_path / "tts.wav", amplitude=5000, seconds=1)
    plan_file = tmp_path / "a4.json"
    plan = create_review_plan(source, plan_file)
    plan["events"] = [
        {"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"},
        {"start_frame": 48000, "end_frame": 96000, "action": "PRESERVE"},
        {"start_frame": 96000, "end_frame": 144000, "action": "REVIEW"},
    ]
    plan_file.write_text(json.dumps(plan))
    output = tmp_path / "out.wav"
    mixed = render_overdub(
        source, voice, plan_file, output,
        normalized_source_wav=normalized, source_normalization=receipt,
    )
    assert mixed["source_wav_sha256"] == original_sha
    assert mixed["base_source_normalization"] == receipt
    assert mixed["preserved_span_pcm_reference"] == "normalized_base_source"
    assert digest(source) == original_sha
    assert sample(source, 1.627) != sample(normalized, 1.627)
    for t in (1.125, 1.625, 2.125, 2.625):
        assert sample(output, t) == sample(normalized, t)
    assert sample(output, 0.127) != sample(normalized, 0.127)


def test_mixing_rejects_normalization_from_a_different_source(tmp_path):
    source = wav(tmp_path / "source.wav", amplitude=1400, seconds=2)
    changed_source = wav(tmp_path / "other.wav", amplitude=1600, seconds=2)
    voice = wav(tmp_path / "tts.wav", amplitude=5000, seconds=2)
    normalized = tmp_path / "normalized.wav"
    receipt = normalize_overdub_base(changed_source, normalized, tmp_path / "other.json")
    plan_file = tmp_path / "a4.json"
    create_review_plan(source, plan_file)
    with pytest.raises(SourceLoudnessError, match="does not match"):
        render_overdub(
            source, voice, plan_file, tmp_path / "mixed.wav",
            normalized_source_wav=normalized, source_normalization=receipt,
        )
    assert not (tmp_path / "mixed.wav").exists()


def test_r128_normalization_respects_source_bit_identity_and_clock(tmp_path):
    source = wav(tmp_path / "src.wav", amplitude=2700, seconds=2, frequency=330)
    digest_before = digest(source)
    result = normalize_overdub_base(source, tmp_path / "norm.wav", tmp_path / "norm.json")
    assert result["source_frames"] == 96000
    assert digest(source) == digest_before
    # The source and normalized speech cannot be shifted to a new audio clock.
    # Two-pass EBU loudnorm must leave its beginning and ending sample count.
    with wave.open(str(tmp_path / "norm.wav"), "rb") as result_audio:
        assert result_audio.getnframes() == 96000


def test_different_original_recording_levels_share_one_lufs_reference(tmp_path):
    low = wav(tmp_path / "low.wav", amplitude=850, seconds=3)
    high = wav(tmp_path / "high.wav", amplitude=5100, seconds=3)
    levels = []
    for label, original in (("low", low), ("high", high)):
        normalized = tmp_path / f"{label}-normalized.wav"
        report = normalize_overdub_base(
            original, normalized, tmp_path / f"{label}.json",
        )
        levels.append(report["normalized_integrated_lufs"])
        with wave.open(str(original)) as a, wave.open(str(normalized)) as b:
            assert a.getnframes() == b.getnframes()
    assert max(levels) - min(levels) <= 0.2


def test_one_normalized_source_is_reused_for_both_voice_gain_choices(tmp_path):
    from app.audio.overdub import OverdubLevels

    source = wav(tmp_path / "source.wav", amplitude=1900, seconds=3)
    translated = wav(tmp_path / "tts.wav", amplitude=6200, seconds=1)
    normalized = tmp_path / "normal.wav"
    sidecar = tmp_path / "base.json"
    normal = normalize_overdub_base(source, normalized, sidecar)
    original_cache_time = normalized.stat().st_mtime_ns
    source_plan = tmp_path / "a4.json"
    plan = create_review_plan(source, source_plan)
    plan["events"] = [
        {"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"},
        {"start_frame": 48000, "end_frame": 144000, "action": "PRESERVE"},
    ]
    source_plan.write_text(json.dumps(plan))

    for voice_db in (-16.0, -20.0):
        candidate = tmp_path / f"overdub{voice_db}.wav"
        render_overdub(
            source, translated, source_plan, candidate,
            levels=OverdubLevels(-16, voice_db, 25),
            normalized_source_wav=normalized, source_normalization=normal,
        )
        assert normalize_overdub_base(source, normalized, sidecar) == normal
    assert normalized.stat().st_mtime_ns == original_cache_time
    assert sample(tmp_path / "overdub-16.0.wav", 0.127) != sample(
        tmp_path / "overdub-20.0.wav", 0.127
    )
    for t in (1.127, 2.627):
        a = sample(tmp_path / "overdub-16.0.wav", t)
        b = sample(tmp_path / "overdub-20.0.wav", t)
        assert a == b == sample(normalized, t)
