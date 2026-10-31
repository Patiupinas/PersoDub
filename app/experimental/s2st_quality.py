"""Objective S2ST timing triage before a translated voice enters the Overdub.

Duration gates are intentionally not semantic quality judgments. The model
could create a fluent but inaccurate Russian sentence whose timings still
fit. Vocal exercise protection requires independent human/approved labels.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

MAX_SLOT_EXTRA_SECONDS = 0.05
MIN_RELIABLE_SOURCE_SECONDS = 2.0
EXTREME_EXPANSION_MULTIPLIER = 3.0


def assess_candidate(source_seconds, translated_seconds) -> dict:
    """Return observable reasons to withhold automated S2ST audio placement."""
    for label, value in (("source", source_seconds), ("translated", translated_seconds)):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("Non-finite or non-positive %s duration" % label)
    reasons = []
    if source_seconds < MIN_RELIABLE_SOURCE_SECONDS:
        reasons.append("short_source_needs_event_and_speaker_review")
    if translated_seconds > source_seconds + MAX_SLOT_EXTRA_SECONDS:
        reasons.append("translation_overruns_source_slot")
    if translated_seconds > source_seconds * EXTREME_EXPANSION_MULTIPLIER:
        reasons.append("extreme_duration_expansion")
    return {
        "state": "REVIEW_REQUIRED" if reasons else "TIMING_CANDIDATE_ONLY",
        "source_seconds": round(source_seconds, 5),
        "translated_seconds": round(translated_seconds, 5),
        "ratio": round(translated_seconds / source_seconds, 5),
        "reasons": reasons,
        "translation_accuracy_verified": False,
        "native_russian_accent_verified": False,
        "speaker_similarity_verified": False,
        "singing_translation_approved": False,
    }


def evaluate_experiment(path: str | Path) -> dict:
    """Score the existing source-bound receipts without re-running inference."""
    root = Path(path).resolve()
    plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    if plan.get("schema_version") != 1:
        raise ValueError("Unsupported experiment plan")
    cases = []
    for entry in plan.get("entries", []):
        report = root / entry["output_report"]
        if report.parent != root or not report.is_file():
            cases.append({"index": entry["index"], "state": "NOT_RUN"})
            continue
        value = json.loads(report.read_text(encoding="utf-8"))
        if value.get("source_sha256") != entry["source_sha256"]:
            raise ValueError("S2ST result does not match selected source")
        assessment = assess_candidate(
            value["source_seconds"], value["output_seconds"],
        )
        cases.append({"index": entry["index"], **assessment})
    return {
        "schema_version": 1,
        "suite": "seamless-s2st-duration-triage",
        "cases": cases,
        "review_required": sum(x["state"] == "REVIEW_REQUIRED" for x in cases),
        "not_run": sum(x["state"] == "NOT_RUN" for x in cases),
        "acceptance_status": "NOT_CERTIFIED",
        "policy_is_calibration_candidate": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = evaluate_experiment(args.experiment_dir)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as file:
            file.write(encoded)
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
