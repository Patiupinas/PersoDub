"""Model-free synthetic WAV tests: never modify a protected vocal frame."""

import hashlib
import json
import os
import struct
import subprocess
import sys
import wave

import pytest

from app.vocal_decisions import DecisionValidationError
from app.vocal_pcm import (
    CHUNK_FRAMES,
    PCMAssemblyError,
    assemble_vocal_wav,
    verify_preserved_wav,
)


def frames(n, channels=2, seed=0):
    return b"".join(struct.pack("<" + "h" * channels, *(
        (((i + seed) * (37 + ch * 19)) % 60000) - 30000 for ch in range(channels)
    )) for i in range(n))


def save(path, data, *, rate=48000, channels=2, width=2):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(data)
    return path


def load(path):
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes(), wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.readframes(wav.getnframes())


def t(start, end, name):
    return {"segment_id": name, "start_sample": start, "end_sample": end,
            "action": "TRANSLATE", "source_language": "de", "source_text": "Bitte nachsingen."}


def p(start, end, name):
    return {"segment_id": name, "start_sample": start, "end_sample": end,
            "action": "PRESERVE", "reason": "sung vowel"}


def r(start, end, name):
    return {"segment_id": name, "start_sample": start, "end_sample": end,
            "action": "REVIEW", "reason": "unclassified vocal transition"}


def decisions(raw_audio, parts, *, rate=48000, **overrides):
    manifest = {"schema_version": 1, "source_sha256": "c" * 64,
                "pcm_sha256": hashlib.sha256(raw_audio).hexdigest(),
                "sample_rate": rate, "total_samples": len(raw_audio) // 4,
                "segments": parts, "model_revisions": {"classifier": "synthetic-only"}}
    manifest.update(overrides)
    return manifest


@pytest.fixture
def sample(tmp_path):
    source_data = frames(290)
    source = save(tmp_path / "source.wav", source_data)
    first_tts = frames(50, seed=1500)
    second_tts = frames(80, seed=2000)
    first = save(tmp_path / "spoken1.wav", first_tts)
    second = save(tmp_path / "spoken2.wav", second_tts)
    label = decisions(source_data, [t(0, 80, "s1"), p(80, 160, "vowel"),
                                    t(160, 240, "s2"), r(240, 290, "uncertain")])
    return source, tmp_path / "mixed.wav", label, {"s1": first, "s2": second}, source_data, first_tts, second_tts


def test_preserve_review_exact_pcm_and_translate_zero_pad(sample):
    src, out, manifest, tts, original, a, b = sample
    original_container = src.read_bytes()
    report = assemble_vocal_wav(src, out, manifest, tts)
    count, rate, channels, width, mixed = load(out)
    assert (count, rate, channels, width) == (290, 48000, 2, 2)
    assert mixed[:80 * 4] == a + b"\x00" * (30 * 4)
    assert mixed[80 * 4:160 * 4] == original[80 * 4:160 * 4]
    assert mixed[160 * 4:240 * 4] == b
    assert mixed[240 * 4:] == original[240 * 4:]
    assert verify_preserved_wav(src, out, manifest) == 130
    assert src.read_bytes() == original_container
    assert report.protected_samples == 130
    assert report.translated_samples == 160
    assert report.tts_audio_samples == 130
    assert report.silence_padding_samples == 30
    assert report.output_pcm_sha256 == hashlib.sha256(mixed).hexdigest()


def test_byte_determinism_without_timestamps_or_randomness(sample, tmp_path):
    src, out, manifest, tts, *_ = sample
    assemble_vocal_wav(src, out, manifest, tts)
    second = tmp_path / "duplicate.wav"
    assemble_vocal_wav(src, second, manifest, tts)
    assert out.read_bytes() == second.read_bytes()


def test_mixed_phrase_children_assembled_without_touching_middle(sample):
    src, out, manifest, tts, original, *_ = sample
    manifest["segments"] = [{"segment_id": "phrase", "start_sample": 0,
                             "end_sample": 290, "action": "MIXED",
                             "children": manifest["segments"]}]
    assemble_vocal_wav(src, out, manifest, tts)
    assert load(out)[-1][80 * 4:160 * 4] == original[80 * 4:160 * 4]


def test_review_only_needs_no_tts_and_copies_every_frame(tmp_path):
    pcm = frames(100, channels=1)
    src = save(tmp_path / "src.wav", pcm, rate=8000, channels=1)
    manifest = decisions(pcm, [r(0, 100, "review")], rate=8000)
    manifest["total_samples"] = 100
    out = tmp_path / "out.wav"
    result = assemble_vocal_wav(src, out, manifest, {})
    assert load(out)[-1] == pcm
    assert result.protected_samples == 100
    assert result.translated_samples == 0


def test_translate_only_has_no_original_voice_and_no_protected_regions(tmp_path):
    original = frames(100)
    src = save(tmp_path / "src.wav", original)
    voice = save(tmp_path / "voice.wav", frames(100, seed=2000))
    manifest = decisions(original, [t(0, 100, "line")])
    result = assemble_vocal_wav(src, tmp_path / "out.wav", manifest, {"line": voice})
    assert load(tmp_path / "out.wav")[-1] == load(voice)[-1]
    assert result.protected_samples == 0
    assert verify_preserved_wav(src, tmp_path / "out.wav", manifest) == 0


def test_mono_and_44100hz_without_float_timing(tmp_path):
    original = frames(99, channels=1)
    src = save(tmp_path / "source.wav", original, rate=44100, channels=1)
    voice = save(tmp_path / "tts.wav", frames(21, channels=1, seed=20), rate=44100, channels=1)
    manifest = decisions(original, [p(0, 33, "vowel"), t(33, 55, "line"),
                                    r(55, 99, "unknown")], rate=44100)
    manifest["total_samples"] = 99
    report = assemble_vocal_wav(src, tmp_path / "out.wav", manifest, {"line": voice})
    assert load(tmp_path / "out.wav")[-1][:33 * 2] == original[:33 * 2]
    assert load(tmp_path / "out.wav")[-1][55 * 2:] == original[55 * 2:]
    assert report.silence_padding_samples == 1


def test_large_streaming_spans_cross_chunk_boundaries(tmp_path):
    n = CHUNK_FRAMES * 2 + 51
    original = frames(n)
    src = save(tmp_path / "src.wav", original)
    voice = save(tmp_path / "tts.wav", frames(1, seed=5))
    manifest = decisions(original, [p(0, n - 2, "performance"), t(n - 2, n, "last")])
    out = tmp_path / "rendered.wav"
    assert assemble_vocal_wav(src, out, manifest, {"last": voice}).protected_samples == n - 2
    assert verify_preserved_wav(src, out, manifest) == n - 2


@pytest.mark.parametrize("bad", ["missing", "extra"])
def test_missing_or_extra_tts_fails_without_creating_output(sample, bad):
    src, out, manifest, tts, *_ = sample
    if bad == "missing":
        tts.pop("s1")
    else:
        tts["vowel"] = tts["s1"]
    with pytest.raises(PCMAssemblyError, match="missing|unexpected"):
        assemble_vocal_wav(src, out, manifest, tts)
    assert not out.exists()


def test_source_pcm_hash_mismatch_never_overwrites_existing_output(sample):
    src, out, manifest, tts, *_ = sample
    out.write_bytes(b"existing output")
    manifest["pcm_sha256"] = "f" * 64
    with pytest.raises(PCMAssemblyError, match="SHA-256"):
        assemble_vocal_wav(src, out, manifest, tts)
    assert out.read_bytes() == b"existing output"


def test_input_header_frame_count_mismatch(sample):
    src, out, manifest, tts, *_ = sample
    manifest["total_samples"] += 1
    manifest["segments"][-1]["end_sample"] += 1
    with pytest.raises(PCMAssemblyError, match="format disagrees"):
        assemble_vocal_wav(src, out, manifest, tts)
    assert not out.exists()


@pytest.mark.parametrize("modify,match", [
    (lambda m: m.__setitem__("sample_rate", 16000), "format disagrees"),
    (lambda m: m["segments"][1].__setitem__("start_sample", 81), "gap"),
    (lambda m: m["segments"][1].__setitem__("start_sample", 79), "overlap"),
    (lambda m: m["segments"][1].__setitem__("action", "INVALID"), "unknown"),
])
def test_bad_manifest_rejected(sample, modify, match):
    src, out, manifest, tts, *_ = sample
    modify(manifest)
    with pytest.raises((PCMAssemblyError, DecisionValidationError), match=match):
        assemble_vocal_wav(src, out, manifest, tts)
    assert not out.exists()


@pytest.mark.parametrize("format_change,match", [
    ("channels", "mismatch"), ("rate", "mismatch"),
    ("width", "16-bit"), ("overlong", "1.."), ("zero", "1.."),
])
def test_bad_tts_format_or_size_fails_safely(sample, tmp_path, format_change, match):
    src, out, manifest, tts, *_ = sample
    replacement = tmp_path / "bad_tts.wav"
    if format_change == "channels":
        save(replacement, frames(10, channels=1), channels=1)
    elif format_change == "rate":
        save(replacement, frames(10), rate=32000)
    elif format_change == "width":
        save(replacement, bytes([128] * 20), width=1)
    elif format_change == "overlong":
        save(replacement, frames(81))
    else:
        save(replacement, b"")
    tts["s1"] = replacement
    with pytest.raises(PCMAssemblyError, match=match):
        assemble_vocal_wav(src, out, manifest, tts)
    assert not out.exists()


def test_source_mono_stereo_16bit_required(sample, tmp_path):
    src, out, manifest, tts, *_ = sample
    bad = save(tmp_path / "bad_source.wav", bytes([123, 45] * 290), width=1)
    with pytest.raises(PCMAssemblyError, match="16-bit"):
        assemble_vocal_wav(bad, out, manifest, tts)


def test_output_cannot_overwrite_original_or_tts(sample):
    src, out, manifest, tts, *_ = sample
    before = src.read_bytes()
    with pytest.raises(PCMAssemblyError, match="overwrite source"):
        assemble_vocal_wav(src, src, manifest, tts)
    with pytest.raises(PCMAssemblyError, match="overwrite TTS"):
        assemble_vocal_wav(src, tts["s1"], manifest, tts)
    assert src.read_bytes() == before


def test_missing_parent_directory_rejected(sample, tmp_path):
    src, out, manifest, tts, *_ = sample
    with pytest.raises(PCMAssemblyError, match="parent directory"):
        assemble_vocal_wav(src, tmp_path / "does-not-exist" / "dub.wav", manifest, tts)


def test_truncated_wav_data_detected_during_preflight(sample):
    src, out, manifest, tts, *_ = sample
    src.write_bytes(src.read_bytes()[:-7])
    with pytest.raises(PCMAssemblyError, match="truncated"):
        assemble_vocal_wav(src, out, manifest, tts)
    assert not out.exists()


def test_protected_integrity_validator_detects_modified_output(sample):
    src, out, manifest, tts, *_ = sample
    assemble_vocal_wav(src, out, manifest, tts)
    n, rate, channels, width, mixed = load(out)
    tampered = bytearray(mixed)
    tampered[80 * 4 + 10] ^= 0xFF
    save(out, bytes(tampered))
    with pytest.raises(PCMAssemblyError, match="protected PCM was modified"):
        verify_preserved_wav(src, out, manifest)


def test_atomic_failure_preserves_old_output_and_cleans_temp(sample, monkeypatch):
    src, out, manifest, tts, *_ = sample
    out.write_bytes(b"previous good output")
    def integrity_failure(*_args):
        raise PCMAssemblyError("injected verification failure")
    monkeypatch.setattr("app.vocal_pcm._check_protected", integrity_failure)
    with pytest.raises(PCMAssemblyError, match="injected verification failure"):
        assemble_vocal_wav(src, out, manifest, tts)
    assert out.read_bytes() == b"previous good output"
    assert list(out.parent.glob(f".{out.name}.*.wav.tmp")) == []


def test_cli_model_free_complete_run(sample, tmp_path):
    src, out, manifest, tts, *_ = sample
    decisions_file = tmp_path / "decisions.json"
    decisions_file.write_text(json.dumps(manifest), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(__import__("pathlib").Path(__file__).resolve().parents[1]),
                                                      os.environ.get("PYTHONPATH", "")]))
    proc = subprocess.run([sys.executable, "-m", "app.vocal_pcm", "--source", str(src),
                           "--output", str(out), "--decisions", str(decisions_file),
                           "--tts", f"s1={tts['s1']}", "--tts", f"s2={tts['s2']}"],
                          capture_output=True, text=True, env=env, check=False)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["protected_samples"] == 130
    assert out.exists()


def test_cli_refuses_missing_voice_without_modifying_output(sample, tmp_path):
    src, out, manifest, tts, *_ = sample
    decisions_file = tmp_path / "decisions.json"
    decisions_file.write_text(json.dumps(manifest), encoding="utf-8")
    proc = subprocess.run([sys.executable, "-m", "app.vocal_pcm", "--source", str(src),
                           "--output", str(out), "--decisions", str(decisions_file)],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 2
    assert "missing" in proc.stderr
    assert not out.exists()
