"""Reproduce SMAD's coarse labels against exact MAVC100 source-frame durations.

Research-only selected-performance measurement; no dubbing actions or gold promotion.
"""
import json
from collections import Counter
from pathlib import Path

LABELS = ("speech_noise", "speech_music", "singing_music", "none")
GOLD = ("speech", "singing", "silence")


class SMADScoringError(ValueError):
    """Source-clock evidence is malformed or incomplete."""


def _number(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise SMADScoringError("expected integer source timing")
    return value


def score_clip(clip, sample_rate):
    """Score half-open original-PCM intervals on a frozen one-second model grid."""
    total = _number(clip["total_samples"], 1)
    rate = _number(sample_rate, 1)
    cells = clip["smad_cells"]
    if total % rate or type(cells) is not list or len(cells) != total // rate:
        raise SMADScoringError("incomplete model grid")
    if any(label not in LABELS for label in cells):
        raise SMADScoringError("unknown model class")
    counts = {name: Counter() for name in ("speech", "singing")}
    last = 0
    touches = 0
    sung_events = 0
    clipped = 0
    for record in clip["gold_events_ms"]:
        if type(record) is not list or len(record) != 3:
            raise SMADScoringError("invalid gold interval")
        kind, start_ms, end_ms = record
        if kind not in GOLD:
            raise SMADScoringError("unknown gold class")
        begin = _number(start_ms) * rate // 1000
        finish = (_number(end_ms, 1) * rate + 999) // 1000
        if begin < last or finish <= begin or begin >= total:
            raise SMADScoringError("overlapping or invalid gold")
        if finish > total:
            excess = finish - total
            if kind != "silence" or excess > (50 * rate + 999) // 1000:
                raise SMADScoringError("gold voiced tail exceeds source")
            clipped += excess
            finish = total
        last = finish
        if kind == "silence":
            continue
        sung_events += int(kind == "singing")
        touched = False
        for second in range(begin // rate, (finish - 1) // rate + 1):
            overlap = min(finish, (second + 1) * rate) - max(begin, second * rate)
            label = cells[second]
            counts[kind][label] += overlap
            touched |= kind == "singing" and label in ("speech_noise", "speech_music")
        touches += int(touched)
    speech = sum(counts["speech"].values())
    singing = sum(counts["singing"].values())
    if not speech or not singing:
        raise SMADScoringError("both independently annotated classes are required")
    result = {
        "gold_speech_samples": speech,
        "gold_singing_samples": singing,
        "gold_speech_predicted_speech_samples": sum(counts["speech"][v] for v in LABELS[:2]),
        "gold_speech_predicted_singing_samples": counts["speech"]["singing_music"],
        "gold_singing_predicted_speech_samples": sum(counts["singing"][v] for v in LABELS[:2]),
        "gold_singing_predicted_singing_samples": counts["singing"]["singing_music"],
        "singing_events": sung_events,
        "singing_events_touched_by_predicted_speech": touches,
        "clipped_published_silence_tail_samples": clipped,
    }
    return result


def score_snapshot(snapshot):
    """Replay only observed numeric evidence; do not infer translation permissions."""
    if snapshot.get("schema_version") != 1 or snapshot.get("model") != "duclvQ/smad":
        raise SMADScoringError("unrecognized benchmark")
    if snapshot.get("source") != "MAVC100 audio-stream annotations":
        raise SMADScoringError("unrecognized annotation source")
    if snapshot.get("receptive_field_seconds") != 4 or snapshot.get("grid_seconds") != 1:
        raise SMADScoringError("model clock differs")
    if len(snapshot.get("model_revision", "")) != 40 or len(snapshot.get("model_sha256", "")) != 64:
        raise SMADScoringError("model identity absent")
    clips = snapshot.get("clips")
    if type(clips) is not list or len(clips) != 3:
        raise SMADScoringError("frozen pilot requires three source clips")
    seen = set()
    results = []
    for clip in clips:
        name = clip["clip_id"]
        if not isinstance(name, str) or not name.replace("_", "").isalnum() or name in seen:
            raise SMADScoringError("invalid or duplicate clip identifier")
        seen.add(name)
        if len(clip.get("source_sha256", "")) != 64 or len(clip.get("label_sha256", "")) != 64:
            raise SMADScoringError("source hash missing")
        result = score_clip(clip, snapshot["sample_rate"])
        results.append({"clip_id": name, **result})
    keys = [key for key in results[0] if key != "clip_id"]
    sums = {key: sum(item[key] for item in results) for key in keys}
    speech = sums["gold_speech_samples"]
    singing = sums["gold_singing_samples"]
    sums["speech_recall"] = round(sums["gold_speech_predicted_speech_samples"] / speech, 7)
    sums["singing_recall"] = round(sums["gold_singing_predicted_singing_samples"] / singing, 7)
    sums["singing_to_speech_rate"] = round(sums["gold_singing_predicted_speech_samples"] / singing, 7)
    sums["speech_mislabeled_singing_rate"] = round(sums["gold_speech_predicted_singing_samples"] / speech, 7)
    return {"schema_version": 1, "model": snapshot["model"],
            "model_sha256": snapshot["model_sha256"], "clips": results, "aggregate": sums}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Recalculate frozen SMAD/MAVC100 numeric scores")
    parser.add_argument("--observations", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(score_snapshot(json.loads(args.observations.read_text(encoding="utf-8"))), indent=2))


if __name__ == "__main__":
    main()
