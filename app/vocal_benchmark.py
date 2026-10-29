"""Measure selective-dubbing decisions against a manual sample-level reference.

Pure standard-library interval scorer: no media files, models, or downloads.
Avoid counting token/segment accuracy where split lengths vary; every overlap
is measured in decoded PCM frames. A universal REVIEW avoids unsafe changes
but also scores zero useful translation coverage, which is reported separately.
"""

import argparse
import json
from pathlib import Path

from app.vocal_decisions import DecisionManifest, parse_decision_manifest

LABELS = ("TRANSLATE", "PRESERVE", "REVIEW")


class BenchmarkError(ValueError):
    """Cannot compare these predictions with this ground truth."""


def _fraction(part, total):
    """Undefined metrics are null, never a misleading 0% or 100%."""
    return part / total if total else None


def _matched(gold, predicted):
    if not isinstance(gold, DecisionManifest) or not isinstance(predicted, DecisionManifest):
        raise BenchmarkError("expected validated DecisionManifest inputs")
    if (gold.source_sha256 != predicted.source_sha256 or
            gold.pcm_sha256 != predicted.pcm_sha256 or
            gold.sample_rate != predicted.sample_rate or
            gold.total_samples != predicted.total_samples):
        raise BenchmarkError("gold/predicted refer to different source or PCM timeline")


def score_vocal_decisions(gold_raw, predicted_raw):
    """Return exact frame-weighted confusion and safety/coverage report.

    Each input uses vocal_decisions schema v1 and must cover all samples.
    Gold PRESERVE should identify vocal demonstrations; gold REVIEW denotes
    genuinely uncertain source material. This scorer does not audit the
    correctness, independence, or licensing of ground-truth annotations.
    """
    gold = parse_decision_manifest(gold_raw)
    predicted = parse_decision_manifest(predicted_raw)
    _matched(gold, predicted)

    confusion = {g: dict.fromkeys(LABELS, 0) for g in LABELS}
    affected_gold_ids = set()
    ambiguous_affected = set()
    gi = pi = 0
    while gi < len(gold.spans) and pi < len(predicted.spans):
        g = gold.spans[gi]
        p = predicted.spans[pi]
        overlap = min(g.end_sample, p.end_sample) - max(g.start_sample, p.start_sample)
        if overlap > 0:
            confusion[g.action][p.action] += overlap
            if p.action == "TRANSLATE" and g.action == "PRESERVE":
                affected_gold_ids.add(g.segment_id)
            if p.action == "TRANSLATE" and g.action == "REVIEW":
                ambiguous_affected.add(g.segment_id)
        if g.end_sample <= p.end_sample:
            gi += 1
        if p.end_sample <= g.end_sample:
            pi += 1

    counted = sum(sum(row.values()) for row in confusion.values())
    if counted != gold.total_samples:
        raise BenchmarkError("incomplete overlap accounting")

    protected = sum(confusion["PRESERVE"].values())
    ambiguous = sum(confusion["REVIEW"].values())
    speech = sum(confusion["TRANSLATE"].values())
    correct_speech = confusion["TRANSLATE"]["TRANSLATE"]
    predicted_translate = sum(confusion[g]["TRANSLATE"] for g in LABELS)
    predicted_review = sum(confusion[g]["REVIEW"] for g in LABELS)
    protected_events = sum(s.action == "PRESERVE" for s in gold.spans)
    ambiguous_events = sum(s.action == "REVIEW" for s in gold.spans)
    missed_vocal = confusion["PRESERVE"]["TRANSLATE"]
    missed_ambiguous = confusion["REVIEW"]["TRANSLATE"]

    return {
        "schema_version": 1,
        "source_sha256": gold.source_sha256,
        "pcm_sha256": gold.pcm_sha256,
        "sample_rate": gold.sample_rate,
        "total_samples": gold.total_samples,
        "confusion_samples": confusion,
        "vocal_preservation": {
            "gold_protected_segments": protected_events,
            "gold_protected_samples": protected,
            "wrongly_translated_samples": missed_vocal,
            "affected_gold_segments": len(affected_gold_ids),
            "wrongly_translated_fraction": _fraction(missed_vocal, protected),
            "safe_or_review_fraction": _fraction(protected - missed_vocal, protected),
            "zero_corrupted_vocal_segments": (not affected_gold_ids) if protected_events else None,
        },
        "ambiguous_safety": {
            "gold_review_segments": ambiguous_events,
            "gold_review_samples": ambiguous,
            "wrongly_translated_samples": missed_ambiguous,
            "affected_gold_segments": len(ambiguous_affected),
            "wrongly_translated_fraction": _fraction(missed_ambiguous, ambiguous),
        },
        "speech_utility": {
            "gold_speech_samples": speech,
            "correctly_translated_samples": correct_speech,
            "recall": _fraction(correct_speech, speech),
            "precision": _fraction(correct_speech, predicted_translate),
            "gold_speech_preserved_samples": confusion["TRANSLATE"]["PRESERVE"],
            "gold_speech_reviewed_samples": confusion["TRANSLATE"]["REVIEW"],
        },
        "predicted_review": {
            "samples": predicted_review,
            "fraction_of_total": predicted_review / gold.total_samples,
        },
        "predicted_model_revisions": dict(predicted.model_revisions),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Score selective vocal dubbing decisions vs manual ground truth")
    parser.add_argument("--gold", type=Path, required=True, help="Manual reference decisions.json")
    parser.add_argument("--pred", type=Path, required=True, help="Predicted decisions.json")
    parser.add_argument("--fail-on-unsafe", action="store_true",
                        help="Exit 1 for any incorrectly translated gold PRESERVE/REVIEW; 2 if no protected gold")
    args = parser.parse_args(argv)
    try:
        with args.gold.open(encoding="utf-8") as file:
            gold = json.load(file)
        with args.pred.open(encoding="utf-8") as file:
            predicted = json.load(file)
        result = score_vocal_decisions(gold, predicted)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f"Benchmark failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    if args.fail_on_unsafe:
        vocal = result["vocal_preservation"]
        ambiguous = result["ambiguous_safety"]
        if vocal["gold_protected_segments"] == 0:
            parser.exit(2, "Benchmark inconclusive: no protected gold segments\n")
        if vocal["wrongly_translated_samples"] or ambiguous["wrongly_translated_samples"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
