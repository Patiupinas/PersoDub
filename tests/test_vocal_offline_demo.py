"""Model-free integration tests of decision -> WAV assembly -> benchmark."""

import copy
import hashlib
import json
import subprocess
import sys
import wave
from pathlib import Path

import pytest

from app.vocal_benchmark import score_vocal_decisions
from app.vocal_decisions import parse_decision_manifest
from app.vocal_offline_demo import RATE, create_demo
from app.vocal_pcm import PCMAssemblyError, assemble_vocal_wav, verify_preserved_wav


ROOT = Path(__file__).resolve().parents[1]


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _frames(path, start, length):
    with wave.open(str(path), "rb") as wav:
        wav.setpos(start)
        return wav.readframes(length)


def test_entire_offline_demo_preserves_vocal_and_review_pcm(tmp_path):
    folder = tmp_path / "case"
    report = create_demo(folder)
    assert report["frames"] == 4 * RATE
    assert report["protected_frames_verified"] == 2 * RATE
    assert report["translated_frames"] == 2 * RATE
    assert report["tts_audio_frames"] == RATE // 2 + RATE * 3 // 4
    assert report["silence_padding_frames"] == 2 * RATE - report["tts_audio_frames"]
    assert report["safe_wrongly_translated_vocal_frames"] == 0
    assert report["unsafe_wrongly_translated_vocal_frames"] == 1
    original = folder / "original.synthetic.wav"
    dubbed = folder / "dubbed.synthetic.wav"
    assert original.read_bytes() != dubbed.read_bytes()
    for start in (RATE, 3 * RATE):
        assert _frames(original, start, RATE) == _frames(dubbed, start, RATE)
    gold = _load(folder / "gold.synthetic.json")
    assert verify_preserved_wav(original, dubbed, gold) == 2 * RATE
    assert parse_decision_manifest(gold).total_samples == 4 * RATE


def test_synthetic_translation_is_tts_and_silence_not_original(tmp_path):
    folder = tmp_path / "one"
    create_demo(folder)
    dubbed = folder / "dubbed.synthetic.wav"
    for start, tts, frames in ((0, "speech-de.synthetic.wav", RATE // 2),
                               (2 * RATE, "speech-en.synthetic.wav", RATE * 3 // 4)):
        assert _frames(dubbed, start, frames) == _frames(folder / tts, 0, frames)
        assert _frames(dubbed, start + frames, RATE - frames) == b"\x00" * ((RATE - frames) * 4)


def test_unsafe_single_sample_is_detected_as_one_affected_vocal_event(tmp_path):
    folder = tmp_path / "three"
    create_demo(folder)
    score = score_vocal_decisions(_load(folder / "gold.synthetic.json"),
                                  _load(folder / "predicted-unsafe.synthetic.json"))
    assert score["vocal_preservation"]["wrongly_translated_samples"] == 1
    assert score["vocal_preservation"]["affected_gold_segments"] == 1
    assert score["vocal_preservation"]["zero_corrupted_vocal_segments"] is False
    assert score["speech_utility"]["recall"] == 1
    assert score["confusion_samples"]["PRESERVE"]["TRANSLATE"] == 1


def test_safe_and_unsafe_cli_guards_use_real_generated_manifests(tmp_path):
    folder = tmp_path / "four"
    create_demo(folder)
    gold = str(folder / "gold.synthetic.json")
    safe = str(folder / "predicted-safe.synthetic.json")
    unsafe = str(folder / "predicted-unsafe.synthetic.json")
    def run(pred):
        return subprocess.run([sys.executable, "-m", "app.vocal_benchmark", "--gold", gold,
                               "--pred", pred, "--fail-on-unsafe"], cwd=ROOT,
                              capture_output=True, text=True, check=False)
    okay = run(safe)
    assert okay.returncode == 0, okay.stderr
    assert _load(folder / "report.synthetic.json")["unsafe_wrongly_translated_vocal_frames"] == 1
    failed = run(unsafe)
    assert failed.returncode == 1, failed.stderr
    assert json.loads(failed.stdout)["vocal_preservation"]["wrongly_translated_samples"] == 1


def test_prediction_review_everywhere_cannot_fake_translation_recall(tmp_path):
    folder = tmp_path / "five"
    create_demo(folder)
    gold = _load(folder / "gold.synthetic.json")
    all_review = copy.deepcopy(gold)
    all_review["segments"] = [{"segment_id": "all-review", "start_sample": 0,
                               "end_sample": 4 * RATE, "action": "REVIEW", "reason": "model unsure"}]
    result = score_vocal_decisions(gold, all_review)
    assert result["vocal_preservation"]["wrongly_translated_samples"] == 0
    assert result["speech_utility"]["recall"] == 0
    assert result["predicted_review"]["fraction_of_total"] == 1.0


def test_rejects_overwriting_existing_demo_files(tmp_path):
    folder = tmp_path / "six"
    create_demo(folder)
    prior = hashlib.sha256((folder / "original.synthetic.wav").read_bytes()).hexdigest()
    with pytest.raises(FileExistsError, match="non-empty"):
        create_demo(folder)
    assert hashlib.sha256((folder / "original.synthetic.wav").read_bytes()).hexdigest() == prior


def test_source_mutation_fails_closed_without_publishing(tmp_path):
    folder = tmp_path / "seven"
    create_demo(folder)
    original = folder / "original.synthetic.wav"
    with original.open("r+b") as fh:
        fh.seek(100)
        value = fh.read(1)
        fh.seek(100)
        fh.write(bytes([value[0] ^ 0x01]))
    gold = _load(folder / "gold.synthetic.json")
    with pytest.raises(PCMAssemblyError, match="SHA-256 disagrees"):
        verify_preserved_wav(original, folder / "dubbed.synthetic.wav", gold)
    untouched_output = folder / "cannot-overwrite.wav"
    untouched_output.write_bytes(b"keep-me")
    with pytest.raises(PCMAssemblyError, match="SHA-256 disagrees"):
        assemble_vocal_wav(original, untouched_output, gold,
                           {"speech-de": folder / "speech-de.synthetic.wav",
                            "speech-en": folder / "speech-en.synthetic.wav"})
    assert untouched_output.read_bytes() == b"keep-me"


def test_cli_generates_expected_files_and_refuses_second_run(tmp_path):
    folder = tmp_path / "cli"
    cmd = [sys.executable, "-m", "app.vocal_offline_demo", "--directory", str(folder)]
    first = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    report = json.loads(first.stdout)
    assert report["protected_frames_verified"] == 2 * RATE
    assert sorted(p.name for p in folder.iterdir()) == [
        "dubbed.synthetic.wav", "gold.synthetic.json", "original.synthetic.wav",
        "predicted-safe.synthetic.json", "predicted-unsafe.synthetic.json",
        "report.synthetic.json", "speech-de.synthetic.wav", "speech-en.synthetic.wav"]
    second = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    assert second.returncode == 2
    assert "refusing to overwrite" in second.stderr
