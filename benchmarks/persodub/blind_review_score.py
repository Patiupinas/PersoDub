"""Score offline blinded A/B ratings against the owner's private assignment key.

A three-rater panel is only a minimum intake gate. Aggregates remain OBSERVED,
not evidence that the model's accent or speaker likeness was independently
verified. One video or speaker cannot support generalization or confidence
intervals across recording conditions.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from benchmarks.persodub.review_page import RATING_COLUMNS

METRICS = ("accent_1to5", "voice_1to5", "pauses_1to5",
           "original_audibility_1to5")


def _rating(raw, *, allow_na=False):
    if allow_na and raw == "N/A":
        return None
    if raw not in ("1", "2", "3", "4", "5"):
        raise ValueError("Ratings must be explicit integers 1..5")
    return int(raw)


def summarize(key_path: Path, rating_files: list[Path]) -> dict:
    """Validate independent CSVs and report paired score deltas by comparison."""
    key = json.loads(Path(key_path).read_text(encoding="utf-8"))
    if (type(key) is not dict or key.get("schema_version") != 1
            or not isinstance(key.get("pairs"), list) or not key["pairs"]):
        raise ValueError("Invalid private assignment key")
    profile = key.get("rating_profile", "overdub")
    if profile not in ("voice", "overdub"):
        raise ValueError("Unknown rating profile")
    pairs = {r["id"]: r for r in key["pairs"]}
    if len(pairs) != len(key["pairs"]) or any(
        r.get("A") not in ("baseline", "candidate")
        or r.get("B") not in ("baseline", "candidate")
        or r["A"] == r["B"] for r in pairs.values()
    ):
        raise ValueError("Invalid blinded assignment")
    output = {
        "suite_id": key.get("suite_id"),
        "rating_profile": profile,
        "status": "NOT_RUN",
        "independent_native_russian_identity_verified": False,
        "native_russian_language_self_reported_only": True,
        "rater_count": 0, "native_ru_self_reported_raters": 0,
        "excluded_non_native_raters": 0,
        "pair_count": len(pairs), "groups": {},
        "human_quality_acceptance": False,
        "generalization_across_speakers_or_videos": False,
    }
    if not rating_files:
        return output

    seen_raters = set()
    native_raters = set()
    data = defaultdict(list)
    for item in rating_files:
        with Path(item).open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != RATING_COLUMNS:
                raise ValueError("Rating CSV columns do not match this review pack")
            rows = list(reader)
        if len(rows) != len(pairs):
            raise ValueError("One row per blind comparison is required")
        names = {r.get("rater_id", "").strip() for r in rows}
        if len(names) != 1 or not next(iter(names)):
            raise ValueError("A rating CSV needs one nonempty rater_id")
        rater = names.pop()
        if rater in seen_raters:
            raise ValueError("Duplicate rater IDs are not independent")
        seen_raters.add(rater)
        flags = {r.get("native_ru_self_reported") for r in rows}
        if len(flags) != 1 or next(iter(flags)) not in ("yes", "no"):
            raise ValueError("Native-Russian self-report must be yes or no")
        is_native = flags == {"yes"}
        if is_native:
            native_raters.add(rater)
        ids = [r.get("pair_id") for r in rows]
        if len(ids) != len(set(ids)) or set(ids) != set(pairs):
            raise ValueError("Rating CSV has missing or duplicated blind cases")
        for row in rows:
            pid = row["pair_id"]
            private = pairs[pid]
            if (row.get("A_file") != pid + "/A.wav"
                    or row.get("B_file") != pid + "/B.wav"):
                raise ValueError("Rating CSV references the wrong blinded files")
            if row.get("preference_A_B_tie") not in ("A", "B", "tie"):
                raise ValueError("A, B or tie preference is required")
            metrics = {}
            for dimension in METRICS:
                is_na = profile == "voice" and dimension == "original_audibility_1to5"
                first = _rating(row.get("A_" + dimension), allow_na=is_na)
                second = _rating(row.get("B_" + dimension), allow_na=is_na)
                if is_na and (first is not None or second is not None):
                    raise ValueError("Voice-only samples must mark original bed N/A")
                metrics[dimension] = (
                    (first, second) if private["A"] == "baseline"
                    else (second, first)
                )
            pick = row["preference_A_B_tie"]
            favored = ("tie" if pick == "tie"
                       else private[pick])
            if is_native:
                # Accent and speaker-likeness MOS are valid only within the
                # native-Russian review panel; exclude other rows from MOS.
                data[private.get("comparison", "default")].append({
                    "pair_id": pid, "rater_id": rater, "metrics": metrics,
                    "preference": favored,
                })

    output["rater_count"] = len(seen_raters)
    output["native_ru_self_reported_raters"] = len(native_raters)
    output["excluded_non_native_raters"] = len(seen_raters) - len(native_raters)
    output["status"] = ("OBSERVED_HUMAN_RATINGS" if len(native_raters) >= 3
                        else "INCOMPLETE_REVIEW_PANEL")
    for group, rows in sorted(data.items()):
        report = {
            "case_ratings": len(rows),
            "raters": len({r["rater_id"] for r in rows}),
            "preferences": {choice: sum(r["preference"] == choice for r in rows)
                            for choice in ("baseline", "candidate", "tie")},
            "dimensions": {},
        }
        for dimension in METRICS:
            ratings = [r["metrics"][dimension] for r in rows
                       if r["metrics"][dimension][0] is not None]
            if not ratings:
                report["dimensions"][dimension] = {"status": "NOT_APPLICABLE"}
                continue
            baseline = sum(x[0] for x in ratings) / len(ratings)
            candidate = sum(x[1] for x in ratings) / len(ratings)
            report["dimensions"][dimension] = {
                "status": "OBSERVED",
                "baseline_mos": round(baseline, 3),
                "candidate_mos": round(candidate, 3),
                "candidate_minus_baseline": round(candidate - baseline, 3),
            }
        output["groups"][group] = report
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--ratings", type=Path, nargs="*", default=[])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = summarize(args.private_key, args.ratings)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps({"status": report["status"],
                      "raters": report["rater_count"],
                      "native_self_reported": report["native_ru_self_reported_raters"],
                      "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
