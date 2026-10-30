"""Measure acoustic-class observations against the MAVC100 timed audio labels.

Scores are model diagnostics, not verified lesson-dubbing decisions. Original
MAVC100 speech means any audible speech, not necessarily explanation.
"""

import argparse
import hashlib
import json
from collections import Counter
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path

from app.vocal_mavc100 import parse_mavc_csv

GOLD_NAMES = {1: "speech", 2: "singing"}
PRED_CODES = {"unclassified": 0, "speech": 1, "music": 2, "noise": 3, "noEnergy": 4}
PRED_NAMES = tuple(PRED_CODES)


class MAVCScoringError(ValueError):
    """Missing provenance or incompatible time clocks make a score invalid."""


def _whole_number(value: object, name: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MAVCScoringError(f"{name}: expected integer >= {minimum}")
    return value


def _model_sample(value: object, rate: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MAVCScoringError(f"{name}: expected numeric seconds")
    try:
        seconds = Decimal(str(value))
    except InvalidOperation as exc:
        raise MAVCScoringError(f"{name}: invalid seconds") from exc
    if not seconds.is_finite() or seconds < 0:
        raise MAVCScoringError(f"{name}: negative/non-finite seconds")
    return int((seconds * rate).to_integral_value(rounding=ROUND_HALF_EVEN))


def _rate(part: int, denominator: int) -> float | None:
    return round(part / denominator, 7) if denominator else None


def score_mavc_clip(
    label_csv: bytes,
    *,
    filename: str,
    predictions: list[dict],
    sample_rate: int,
    total_samples: int,
    max_silence_tail_ms: int = 50,
) -> dict:
    """Return PCM-frame weighted acoustic confusion for one verified clip.

    A short labeled silence tail beyond the last *decoded audio* frame may be
    clipped, but spoken/sung intervals may never be clipped to invent gold.
    Unlabelled intervals are explicit 'other'; absent model predictions are
    'unclassified', not silently speech or music.
    """
    rate = _whole_number(sample_rate, "sample_rate")
    total = _whole_number(total_samples, "total_samples")
    _whole_number(max_silence_tail_ms, "max_silence_tail_ms", minimum=0)
    clip = parse_mavc_csv(label_csv, filename=filename)
    gold = bytearray(total)
    clipped_tail = 0
    singing_intervals = []
    for event in clip.events:
        start = event.start_ms * rate // 1000
        end = (event.end_ms * rate + 999) // 1000
        if end > total:
            excess = end - total
            limit = (max_silence_tail_ms * rate + 999) // 1000
            if event.kind != "silence" or start >= total or excess > limit:
                raise MAVCScoringError("gold voiced interval or long silence tail exceeds decoded PCM")
            clipped_tail += excess
            end = total
        if end <= start:
            continue
        code = {"speech": 1, "singing": 2, "silence": 3}[event.kind]
        if gold[start:end].count(0) != end - start:
            raise MAVCScoringError("overlapping projected gold intervals")
        gold[start:end] = bytes((code,)) * (end - start)
        if code == 2:
            singing_intervals.append((start, end))

    if not isinstance(predictions, list):
        raise MAVCScoringError("predictions must be a list")
    detected = bytearray(total)
    for idx, span in enumerate(predictions):
        if not isinstance(span, dict) or set(span) != {"label", "start_sec", "end_sec"}:
            raise MAVCScoringError(f"prediction {idx}: invalid fields")
        kind = span["label"]
        if kind not in PRED_CODES or kind == "unclassified":
            raise MAVCScoringError(f"prediction {idx}: unsupported label")
        start = _model_sample(span["start_sec"], rate, "prediction.start_sec")
        end = _model_sample(span["end_sec"], rate, "prediction.end_sec")
        if not 0 <= start < end <= total:
            raise MAVCScoringError(f"prediction {idx}: outside decoded PCM")
        if detected[start:end].count(0) != end - start:
            raise MAVCScoringError(f"prediction {idx}: overlapping predictions")
        detected[start:end] = bytes((PRED_CODES[kind],)) * (end - start)

    confusion = {label: Counter() for label in GOLD_NAMES.values()}
    for truth, predicted in zip(gold, detected):
        if truth in GOLD_NAMES:
            confusion[GOLD_NAMES[truth]][PRED_NAMES[predicted]] += 1
    speech = confusion["speech"]
    singing = confusion["singing"]
    speech_total = sum(speech.values())
    singing_total = sum(singing.values())
    events_touched = sum(detected[start:end].count(PRED_CODES["speech"]) > 0
                         for start, end in singing_intervals)
    return {
        "clip_id": clip.clip_id,
        "source_id": clip.source_id,
        "label_sha256": clip.annotation_sha256,
        "sample_rate": rate,
        "total_samples": total,
        "clipped_published_silence_tail_samples": clipped_tail,
        "gold_speech_samples": speech_total,
        "gold_singing_samples": singing_total,
        "singing_events": len(singing_intervals),
        "singing_events_touched_by_predicted_speech": events_touched,
        "gold_singing_predicted_speech_samples": singing["speech"],
        "gold_speech_predicted_speech_samples": speech["speech"],
        "gold_speech_predicted_music_samples": speech["music"],
        "gold_singing_predicted_music_samples": singing["music"],
        "singing_predicted_speech_rate": _rate(singing["speech"], singing_total),
        "speech_detected_rate": _rate(speech["speech"], speech_total),
        "speech_predicted_music_rate": _rate(speech["music"], speech_total),
        "singing_predicted_music_rate": _rate(singing["music"], singing_total),
        "confusion": {label: {category: group[category] for category in PRED_NAMES}
                      for label, group in confusion.items()},
    }


def combine_mavc_scores(results: list[dict]) -> dict:
    """Aggregate counts before computing rates, never average clip fractions."""
    if not results:
        raise MAVCScoringError("no clip scores supplied")
    sums = {name: sum(result[name] for result in results) for name in (
        "gold_speech_samples", "gold_singing_samples", "gold_singing_predicted_speech_samples",
        "gold_speech_predicted_speech_samples", "gold_speech_predicted_music_samples",
        "gold_singing_predicted_music_samples", "singing_events",
        "singing_events_touched_by_predicted_speech", "clipped_published_silence_tail_samples",
    )}
    speech = sums["gold_speech_samples"]
    singing = sums["gold_singing_samples"]
    return {
        "clips": len(results),
        **sums,
        "singing_predicted_speech_rate": _rate(sums["gold_singing_predicted_speech_samples"], singing),
        "speech_detected_rate": _rate(sums["gold_speech_predicted_speech_samples"], speech),
        "speech_predicted_music_rate": _rate(sums["gold_speech_predicted_music_samples"], speech),
        "singing_predicted_music_rate": _rate(sums["gold_singing_predicted_music_samples"], singing),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score precomputed INA observations against MAVC100 labels")
    parser.add_argument("--labels", required=True)
    parser.add_argument("--audit", required=True, help="JSON from app.vocal_mavc100")
    parser.add_argument("--pcm", required=True, help="Exact decoded source audio metadata JSON")
    parser.add_argument("--predictions", required=True, help="Acoustic model prediction JSON")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    expected = json.loads(Path(args.audit).read_text(encoding="utf-8"))["selected"]
    metadata = json.loads(Path(args.pcm).read_text(encoding="utf-8"))
    report = json.loads(Path(args.predictions).read_text(encoding="utf-8"))
    selected = {record["clip_id"]: record for record in expected}
    pcm_map = {record["clip_id"]: record for record in metadata}
    predicted = report["clips"]
    if len(selected) != len(expected) or len(pcm_map) != len(metadata) or len(predicted) != len(selected):
        raise MAVCScoringError("duplicate or mismatched clip inventories")
    if {record["clip_id"] for record in predicted} != set(selected) or set(pcm_map) != set(selected):
        raise MAVCScoringError("predictions, PCM and annotation inventory disagree")
    results = []
    for item in predicted:
        clip_id = item["clip_id"]
        if not isinstance(clip_id, str) or "/" in clip_id or "\\" in clip_id:
            raise MAVCScoringError("invalid clip identifier")
        origin = pcm_map[clip_id]
        if item["source_sha256"] != origin["source_mp4_sha256"]:
            raise MAVCScoringError("source MP4 SHA-256 mismatch")
        if Decimal(origin["audio_stream"]["start_time"]) != 0:
            raise MAVCScoringError("decoded PCM offset relative to label clock is not verified")
        csv_path = Path(args.labels) / (clip_id + ".csv")
        data = csv_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != selected[clip_id]["annotation_sha256"]:
            raise MAVCScoringError("source label SHA-256 mismatch")
        results.append(score_mavc_clip(
            data,
            filename=csv_path.name,
            predictions=item["segments"],
            sample_rate=48000,
            total_samples=origin["decoded_pcm_48000_s16le_stereo_frames"],
        ))
    output = Path(args.output)
    if output.exists():
        raise MAVCScoringError("output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    content = {
        "schema_version": 1,
        "model": report["model"],
        "model_version": report["model_version"],
        "model_sha256": report["model_sha256"],
        "environment": report["device"],
        "evaluation_note": "MAVC100 original speech/singing observations; NOT sample-exact human lesson-dubbing gold",
        "results": results,
        "aggregate": combine_mavc_scores(results),
    }
    output.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
