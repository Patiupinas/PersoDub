"""Stage benchmarking: independent gold, correct clocks and no fabricated PASS."""

import json
import math
import shutil
import struct
import subprocess
import wave

import pytest

from benchmarks.persodub.metrics import (
    asr_metrics,
    edit_distance,
    event_metrics,
    mix_metrics,
    normalize_text,
    stem_metrics,
    timing_metrics,
)
from benchmarks.persodub.runner import main, run_chain


def _wav(path, samples, rate=16000):
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(b"".join(struct.pack("<h", x) for x in samples))


def _json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _manifest(root, cases):
    path = root / "suite.json"
    _json(path, {"schema_version": 1, "suite_id": "deterministic-fixture",
                 "cases": cases})
    return path


def test_russian_asr_casefold_cer_and_word_errors():
    assert normalize_text("Ёж, ПРИВЕТ!   Как дела?") == "еж привет как дела"
    score = asr_metrics("Ёж, привет! Как дела?", "еж привет как")
    assert score["reference_words"] == 4
    assert score["word_errors"] == 1
    assert score["wer"] == 0.25
    assert score["cer"] > 0
    assert edit_distance([], []) == 0
    with pytest.raises(ValueError, match="empty"):
        asr_metrics(" ? ", "привет")


def test_protected_singing_not_translated_and_review_is_abstention():
    gold = [
        {"start": 0, "end": 2, "label": "TRANSLATE"},
        {"start": 2, "end": 5, "label": "PRESERVE"},
        {"start": 5, "end": 6, "label": "TRANSLATE"},
    ]
    bad = [
        {"start": 0, "end": 4, "action": "TRANSLATE"},
        {"start": 4, "end": 5, "action": "REVIEW"},
        {"start": 5, "end": 6, "action": "TRANSLATE"},
    ]
    metrics = event_metrics(gold, bad, 6)
    assert metrics["protected_seconds"] == 3
    assert metrics["exercise_wrongly_translated_seconds"] == 2
    assert metrics["unreviewed_seconds"] == 1
    assert metrics["speech_recall"] == 1
    assert metrics["speech_precision"] == 0.6
    assert metrics["speech_f1"] == 0.75
    assert event_metrics(gold, gold, 6)["speech_f1"] == 1


def test_event_oracles_reject_holes_reversed_spans_and_fake_ground_truth():
    gold = [{"start": 0, "end": 1, "action": "PRESERVE"}]
    with pytest.raises(ValueError, match="REVIEW"):
        event_metrics([{"start": 0, "end": 1, "action": "REVIEW"}], gold, 1)
    with pytest.raises(ValueError, match="cover"):
        event_metrics(gold, [{"start": 0, "end": 0.5, "action": "PRESERVE"}], 1)
    with pytest.raises(ValueError, match="overlap|gaps"):
        event_metrics(gold, [
            {"start": 0, "end": 0.8, "action": "PRESERVE"},
            {"start": 0.7, "end": 1, "action": "PRESERVE"},
        ], 1)


def test_timing_detects_truncated_pauses_and_late_speech():
    source = [
        {"start": 0.0, "end": 1.0},
        {"start": 2.0, "end": 3.0},
        {"start": 4.0, "end": 5.0},
    ]
    output = [
        {"start": 0.0, "end": 1.7},
        {"start": 2.0, "end": 4.2},
        {"start": 4.1, "end": 5.2},
    ]
    result = timing_metrics(source, output)
    assert result["source_pauses"] == 2
    assert result["total_missing_pause_s"] == pytest.approx(1.8)
    assert result["max_missing_pause_s"] == pytest.approx(1.1)
    assert result["dub_overlapping_pairs"] == 1
    assert result["start_mae_s"] == pytest.approx(0.033333, abs=1e-6)


def test_streamed_stem_si_sdr_correct_vs_wrong(tmp_path):
    samples = [int(9500 * math.sin(i * 0.063)) for i in range(8000)]
    original, same, noisy = (tmp_path / name for name in ("src.wav", "same.wav", "noise.wav"))
    _wav(original, samples)
    _wav(same, samples)
    _wav(noisy, [
        max(-30000, min(30000, x + round(1500 * math.sin(i * 0.031))))
        for i, x in enumerate(samples)
    ])
    assert stem_metrics(str(original), str(same))["perfect_reconstruction"]
    measured = stem_metrics(str(original), str(noisy))
    assert measured["perfect_reconstruction"] is False
    assert measured["si_sdr_db"] < 30
    _wav(noisy, [0] * len(samples))
    with pytest.raises(ValueError, match="Non-silent"):
        stem_metrics(str(original), str(noisy))


def test_zero_mean_stem_metric_is_invariant_to_constant_offset(tmp_path):
    baseline = [round(5000 * math.sin(i * math.pi * 2 / 100)) for i in range(10000)]
    ref, shifted = tmp_path / "src.wav", tmp_path / "shifted.wav"
    _wav(ref, baseline)
    _wav(shifted, [x + 6000 for x in baseline])
    result = stem_metrics(str(ref), str(shifted))
    assert result["perfect_reconstruction"] is True


def test_mix_synthetic_source_projection_restored_vs_ducked(tmp_path):
    rate = 16000
    original = [round(6000 * math.sin(2 * math.pi * 440 * i / rate))
                for i in range(rate * 2)]
    # Frequencies are orthogonal within 1s: source projection is an oracle.
    dubbed = [original[i] if i < rate else round(
        0.158489 * original[i] + 2500 * math.sin(2 * math.pi * 880 * i / rate)
    ) for i in range(rate * 2)]
    a, b = tmp_path / "original.wav", tmp_path / "overdub.wav"
    _wav(a, original, rate)
    _wav(b, dubbed, rate)
    metrics = mix_metrics(str(a), str(b), [
        {"start": 0, "end": 1, "action": "PRESERVE"},
        {"start": 1, "end": 2, "action": "TRANSLATE"},
    ])
    assert metrics["windows"][0]["source_gain_db"] == pytest.approx(0.0)
    assert metrics["windows"][0]["relative_difference_db"] is None
    assert metrics["windows"][1]["source_gain_db"] == pytest.approx(-16.0, abs=0.01)
    _wav(b, [0] * (rate * 2), rate)
    missing = mix_metrics(str(a), str(b), [{"start": 0, "end": 2, "action": "PRESERVE"}])
    assert missing["windows"][0]["source_gain_db"] is None


def test_chain_blocks_missing_oracle_and_optional_assets(tmp_path):
    (tmp_path / "gold.txt").write_text("Привет, мир!", encoding="utf-8")
    (tmp_path / "result.txt").write_text("привет мир", encoding="utf-8")
    _json(tmp_path / "annotations.json", [{"start": 0, "end": 1, "action": "PRESERVE"}])
    _json(tmp_path / "wrong.json", [{"start": 0, "end": 1, "action": "TRANSLATE"}])
    report = run_chain(_manifest(tmp_path, [
        {
            "id": "asr-gold", "stage": "asr", "oracle_kind": "dataset_ground_truth",
            "reference": "gold.txt", "candidate": "result.txt",
            "thresholds": {"wer": {"max": 0.0}},
        },
        {
            "id": "exercise-fail", "stage": "events", "oracle_kind": "human_gold",
            "reference": "annotations.json", "candidate": "wrong.json", "duration_s": 1,
            "thresholds": {"exercise_wrongly_translated_seconds": {"max": 0.0}},
        },
        {
            "id": "pending", "stage": "asr", "oracle_kind": "dataset_ground_truth",
            "reference": "gold.txt", "candidate": "not-installed.txt",
            "optional": True, "thresholds": {"wer": {"max": 0.2}},
        },
        {
            "id": "proxy", "stage": "asr", "oracle_kind": "source_derived_proxy",
            "reference": "gold.txt", "candidate": "result.txt",
            "thresholds": {"wer": {"max": 0.0}},
        },
    ]))
    assert report["overall"] == "FAIL"
    assert [row["status"] for row in report["cases"]] == [
        "PASS", "FAIL", "NOT_RUN", "OBSERVED",
    ]
    assert report["production_quality_verified"] is False
    assert "gold.txt" not in json.dumps(report["cases"])


def test_translation_never_claims_semantics_from_character_match(tmp_path):
    (tmp_path / "ref.txt").write_text("Этот голос ужасен.", encoding="utf-8")
    (tmp_path / "pred.txt").write_text("Этот голос ужасен.", encoding="utf-8")
    report = run_chain(_manifest(tmp_path, [{
        "id": "literal-copy", "stage": "translation",
        "oracle_kind": "human_gold", "reference": "ref.txt",
        "candidate": "pred.txt", "thresholds": {},
    }]))
    assert report["overall"] == "INCOMPLETE"
    assert report["cases"][0]["status"] == "OBSERVED"


def test_cannot_overwrite_evidence_and_strict_fails_incomplete(tmp_path):
    manifest = _manifest(tmp_path, [{
        "id": "unavailable", "stage": "asr", "oracle_kind": "dataset_ground_truth",
        "reference": "unknown.txt", "candidate": "unknown2.txt",
        "optional": True,
    }])
    dest = tmp_path / "report.json"
    assert main(["--manifest", str(manifest), "--out", str(dest), "--strict"]) == 2
    assert dest.is_file()
    with pytest.raises(FileExistsError):
        main(["--manifest", str(manifest), "--out", str(dest)])


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="FFmpeg/ffprobe required")
def test_export_two_track_wiring_measured_by_ffprobe(tmp_path):
    video = tmp_path / "source.mp4"
    translated = tmp_path / "overdub.mp4"
    source_cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=blue:size=64x64:r=5:d=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(video),
    ]
    subprocess.run(source_cmd, check=True, capture_output=True, timeout=45)
    dub_cmd = [
        "ffmpeg", "-y", "-v", "error", "-i", str(video),
        "-map", "0:v:0", "-map", "0:a:0", "-map", "0:a:0",
        "-c:v", "copy", "-c:a", "aac", str(translated),
    ]
    subprocess.run(dub_cmd, check=True, capture_output=True, timeout=45)
    report = run_chain(_manifest(tmp_path, [
        {"id": "tracks", "stage": "export", "oracle_kind": "synthetic_invariant",
         "source": "source.mp4", "candidate": "overdub.mp4",
         "expected_mode": "overdub"},
    ]))
    assert report["overall"] == "PASS_MEASURED_CASES_ONLY"
    assert report["cases"][0]["metrics"]["output_audio_streams"] == 2
    assert report["production_quality_verified"] is False
    report = run_chain(_manifest(tmp_path, [
        {"id": "tracks", "stage": "export", "oracle_kind": "synthetic_invariant",
         "source": "source.mp4", "candidate": "source.mp4",
         "expected_mode": "overdub"},
    ]))
    assert report["cases"][0]["status"] == "FAIL"
