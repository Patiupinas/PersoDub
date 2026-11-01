"""Optional third-method research probe using a local reference-free COMET checkpoint.

Reuses already frozen control pairs and previously scored real subtitles.
All outputs are research diagnostics and remain uncalibrated. Model weights
are never committed, packaged into the app, or downloaded implicitly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from benchmarks.persodub.translation_controls import load_controls


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def verify_inputs(previous: dict, controls_path: Path) -> tuple[list[dict], list[dict]]:
    """Require the exact controls and pair identities of an earlier run."""
    cases = load_controls(controls_path)
    if previous.get("status") != "OBSERVED" or (
        previous.get("translation_quality_verified") is not False
    ):
        raise ValueError("Prior proxy report is not an observed input")
    if previous.get("inputs", {}).get("controls_sha256") != _sha256(controls_path):
        raise ValueError("Control fixture hash mismatch")
    prior = previous.get("control_cases", [])
    if len(prior) != len(cases):
        raise ValueError("Control count mismatch")
    for case, measured in zip(cases, prior):
        if any(case.get(field) != measured.get(field) for field in
               ("id", "kind", "source", "faithful", "altered")):
            raise ValueError("Control pair identity mismatch")
    real = previous.get("real_rows", [])
    if not isinstance(real, list):
        raise ValueError("Invalid real sample inventory")
    if any(not row.get("source_text") or not row.get("translation_text")
           for row in real):
        raise ValueError("Incomplete real pair")
    return cases, real


def assemble_comet_probe(
    previous: dict,
    controls_path: Path,
    scores: list[float],
    comet_meta: dict,
) -> dict:
    """Compute measured paired preference without declaring human quality."""
    cases, real = verify_inputs(previous, controls_path)
    if (len(scores) != len(cases) * 2 + len(real)
            or any(type(s) not in (float, int) or not math.isfinite(s)
                   for s in scores)):
        raise ValueError("COMET score count/value mismatch")
    controls = []
    for idx, case in enumerate(cases):
        good, bad = float(scores[2 * idx]), float(scores[2 * idx + 1])
        controls.append({
            "id": case["id"],
            "kind": case["kind"],
            "faithful_score": round(good, 6),
            "altered_score": round(bad, 6),
            "margin": round(good - bad, 6),
            "prefers_faithful": good > bad + 1e-7,
            "embedding_prefers_faithful":
                previous["control_cases"][idx]["embedding_prefers_faithful"],
            "nli_prefers_faithful":
                previous["control_cases"][idx].get("nli_prefers_faithful"),
        })
    wins = sum(row["prefers_faithful"] for row in controls)
    real_result = []
    for row, score in zip(real, scores[2 * len(cases):]):
        real_result.append({
            "start_s": row["start_s"],
            "end_s": row["end_s"],
            "source_cues": row["source_cues"],
            "translation_cues": row["translation_cues"],
            "embedding_score": row["embedding_score"],
            "nli_symmetric_entailment":
                row.get("nli", {}).get("symmetric_entailment"),
            "comet_qe_score": round(float(score), 6),
            "source_text": row["source_text"],
            "translation_text": row["translation_text"],
        })
    return {
        "schema_version": 1,
        "status": "OBSERVED",
        "translation_quality_verified": False,
        "control_oracle": "model_authored_synthetic_contrastive_not_human_gold",
        "previous_report_sha256": None,
        "comet_model": comet_meta,
        "summary": {
            "controls": len(controls),
            "comet_pairwise_wins": wins,
            "comet_pairwise_rate": round(wins / len(controls), 6),
            "comet_missed_control_ids": [
                row["id"] for row in controls if not row["prefers_faithful"]
            ],
            "real_scored": len(real_result),
        },
        "control_cases": controls,
        "real_rows": real_result,
    }


def run(controls_path: Path, previous_path: Path,
        checkpoint: Path, output_path: Path) -> dict:
    if not checkpoint.is_file():
        raise ValueError("Existing local COMET checkpoint is required")
    previous = json.loads(previous_path.read_text(encoding="utf-8"))
    cases, real = verify_inputs(previous, controls_path)
    pairs = [
        pair
        for case in cases
        for pair in ((case["source"], case["faithful"]),
                     (case["source"], case["altered"]))
    ]
    pairs.extend((row["source_text"], row["translation_text"]) for row in real)
    from comet import load_from_checkpoint

    model = load_from_checkpoint(str(checkpoint))
    predicted = model.predict(
        [{"src": source, "mt": translation} for source, translation in pairs],
        batch_size=4, gpus=0, num_workers=1, progress_bar=False,
    )
    meta = {
        "method": "wmt20_comet_reference_free_quality_estimation",
        "model": "Unbabel/wmt20-comet-qe-da",
        "checkpoint_sha256": _sha256(checkpoint),
        "local_checkpoint": str(checkpoint),
        "calibrated_on_this_domain": False,
        "higher_is_more_similar": True,
    }
    report = assemble_comet_probe(
        previous, controls_path, [float(x) for x in predicted.scores], meta,
    )
    report["previous_report_sha256"] = _sha256(previous_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controls", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(args.controls, args.previous, args.checkpoint, args.out)
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
