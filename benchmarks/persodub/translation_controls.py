"""Controlled contrastive probes for bilingual translation QA.

Known transformations are model-authored synthetic checks, not human gold.
The result is a *paired diagnostic*: does a model prefer a faithful Russian
paraphrase over a deliberately corrupted one for the same English source?

Optional real user subtitles are read-only and never committed to Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from pathlib import Path

from benchmarks.persodub.translation_facts import inspect_en_ru
from benchmarks.persodub.translation_nli import score_nli_pairs
from benchmarks.persodub.translation_quality import _embedding_scores


def _file_hash(path: Path) -> str:
    stream_hash = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            stream_hash.update(block)
    return stream_hash.hexdigest()


def load_controls(path: Path) -> list[dict]:
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if obj.get("schema_version") != 1 or not isinstance(obj.get("cases"), list):
        raise ValueError("Expected schema_version=1 and cases array")
    cases = obj["cases"]
    if len(cases) < 2:
        raise ValueError("Need at least two contrastive controls")
    ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Each contrastive control must be an object")
        for field in ("id", "kind", "source", "faithful", "altered"):
            if not isinstance(case.get(field), str) or not case[field].strip():
                raise ValueError(f"Control must define non-empty {field}")
        if case["id"] in ids:
            raise ValueError("Duplicate control ID")
        ids.add(case["id"])
        if case["faithful"].strip() == case["altered"].strip():
            raise ValueError("Expected changed translation, got identical text")
    return cases


def load_real_groups(path: Path | None) -> list[dict]:
    if path is None:
        return []
    report = json.loads(path.read_text(encoding="utf-8"))
    if (report.get("schema_version") != 1
            or report.get("semantic_quality_certified") is not False
            or report.get("status") != "OBSERVED"):
        raise ValueError("Real input must be a valid observed QE report")
    rows = []
    for group in report.get("groups", []):
        if group.get("source_text") and group.get("translation_text"):
            rows.append(group)
    return rows


def evaluate_scores(
    cases: list[dict],
    embedding_scores: list[float],
    *,
    embedding_meta: dict,
    nli_scores: list[dict] | None = None,
    nli_meta: dict | None = None,
    real_groups: list[dict] | None = None,
) -> dict:
    """Measure paired wins and retain cases that defeat the model."""
    real_groups = real_groups or []
    expected = 2 * len(cases) + len(real_groups)
    if len(embedding_scores) != expected or any(
            type(s) not in (int, float) or not math.isfinite(s)
            for s in embedding_scores):
        raise ValueError("Embedding score count/value mismatch")
    if nli_scores is not None and len(nli_scores) != expected:
        raise ValueError("NLI score count mismatch")

    rows = []
    for i, case in enumerate(cases):
        pos, neg = (float(embedding_scores[2 * i]),
                    float(embedding_scores[2 * i + 1]))
        row = {
            "id": case["id"],
            "kind": case["kind"],
            "source": case["source"],
            "faithful": case["faithful"],
            "altered": case["altered"],
            "embedding_good": round(pos, 6),
            "embedding_altered": round(neg, 6),
            "embedding_margin": round(pos - neg, 6),
            "embedding_prefers_faithful": pos > neg + 1e-7,
        }
        faithful_facts = inspect_en_ru(case["source"], case["faithful"])
        altered_facts = inspect_en_ru(case["source"], case["altered"])
        row["fact_flags_faithful"] = faithful_facts["review_flags"]
        row["fact_flags_altered"] = altered_facts["review_flags"]
        row["fact_discriminates"] = (
            not faithful_facts["review_flags"]
            and bool(altered_facts["review_flags"])
        )
        if nli_scores is not None:
            first, second = nli_scores[2 * i], nli_scores[2 * i + 1]
            left = first["symmetric_entailment"]
            right = second["symmetric_entailment"]
            row["nli_good"] = first
            row["nli_altered"] = second
            row["nli_margin"] = round(left - right, 6)
            row["nli_prefers_faithful"] = left > right + 1e-7
        rows.append(row)

    control_count = len(cases)
    embedding_wins = sum(row["embedding_prefers_faithful"] for row in rows)
    summary = {
        "controls": control_count,
        "embedding_pairwise_wins": embedding_wins,
        "embedding_pairwise_rate": round(embedding_wins / control_count, 6),
        "embedding_missed_control_ids": [
            row["id"] for row in rows if not row["embedding_prefers_faithful"]
        ],
        "fact_discriminated_controls": sum(
            row["fact_discriminates"] for row in rows
        ),
        "fact_false_flags_on_faithful": sum(
            bool(row["fact_flags_faithful"]) for row in rows
        ),
        "embedding_or_fact_pairwise_wins": sum(
            row["embedding_prefers_faithful"] or row["fact_discriminates"]
            for row in rows
        ),
        "embedding_or_fact_missed_ids": [
            row["id"] for row in rows
            if not row["embedding_prefers_faithful"]
            and not row["fact_discriminates"]
        ],
    }
    if nli_scores is not None:
        wins = sum(row["nli_prefers_faithful"] for row in rows)
        summary.update({
            "nli_pairwise_wins": wins,
            "nli_pairwise_rate": round(wins / control_count, 6),
            "nli_missed_control_ids": [
                row["id"] for row in rows if not row["nli_prefers_faithful"]
            ],
        })

    real_out = []
    shift = 2 * control_count
    for i, group in enumerate(real_groups):
        item = {
            "start_s": group["start_s"],
            "end_s": group["end_s"],
            "source_cues": group["source_cues"],
            "translation_cues": group["translation_cues"],
            "source_text": group["source_text"],
            "translation_text": group["translation_text"],
            "embedding_score": round(float(embedding_scores[shift + i]), 6),
            "fact_check": inspect_en_ru(
                group["source_text"], group["translation_text"]
            ),
        }
        if nli_scores is not None:
            item["nli"] = nli_scores[shift + i]
        real_out.append(item)

    real_out.sort(key=lambda row: row["start_s"])
    return {
        "schema_version": 1,
        "status": "OBSERVED",
        "translation_quality_verified": False,
        "control_oracle": "model_authored_synthetic_contrastive_not_human_gold",
        "embedding_model": embedding_meta,
        "nli_model": nli_meta if nli_scores is not None else {"status": "NOT_RUN"},
        "summary": summary,
        "control_cases": rows,
        "real_rows": real_out,
        "environment": {"platform": platform.platform()},
    }


def run(
    controls_file: Path,
    out: Path,
    *,
    real_report: Path | None = None,
    nli: bool = False,
    allow_download: bool = False,
    device: str = "cpu",
) -> dict:
    cases = load_controls(controls_file)
    real_groups = load_real_groups(real_report)
    pairs = [
        pair
        for case in cases
        for pair in ((case["source"], case["faithful"]),
                     (case["source"], case["altered"]))
    ]
    pairs += [
        (row["source_text"], row["translation_text"])
        for row in real_groups
    ]
    embedding_scores, embedding_meta = _embedding_scores(
        pairs, "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        device, False,
    )
    nli_scores, nli_meta = (None, None)
    if nli:
        nli_scores, nli_meta = score_nli_pairs(
            pairs, device=device, allow_download=allow_download,
        )
    report = evaluate_scores(
        cases, embedding_scores, embedding_meta=embedding_meta,
        nli_scores=nli_scores, nli_meta=nli_meta,
        real_groups=real_groups,
    )
    report["inputs"] = {
        "controls_sha256": _file_hash(controls_file),
        "real_qe_sha256": _file_hash(real_report)
        if real_report is not None else None,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controls", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--real-report", type=Path)
    parser.add_argument("--nli", action="store_true")
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    args = parser.parse_args(argv)
    report = run(
        args.controls, args.out, real_report=args.real_report,
        nli=args.nli, allow_download=args.allow_download, device=args.device,
    )
    print(json.dumps({
        "status": report["status"], "summary": report["summary"],
        "real_scored": len(report["real_rows"]), "out": str(args.out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
