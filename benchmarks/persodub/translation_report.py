"""Read an independently produced translation-QE report into the stage chain."""

import hashlib
import math
from pathlib import Path


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_report(source: Path, translation: Path, report: dict) -> dict:
    """Never treat a score report for different media as valid evidence."""
    if not isinstance(report, dict):
        raise ValueError("Invalid translation quality report")
    identifiers = report.get("input", {})
    if (
        report.get("status") != "OBSERVED"
        or report.get("semantic_quality_certified") is not False
        or identifiers.get("source_sha256") != _sha(source)
        or identifiers.get("translation_sha256") != _sha(translation)
    ):
        raise ValueError("Translation quality report/source identity mismatch")
    summary = report.get("summary", {})
    score = summary.get("mean_similarity")
    if (
        type(summary.get("scored_groups")) is not int
        or summary["scored_groups"] < 1
        or type(score) not in (int, float)
        or not math.isfinite(score)
    ):
        raise ValueError("Translation quality report has invalid or missing scores")
    return {
        "semantic_quality": "uncalibrated_multilingual_proxy",
        "model_method": report.get("model", {}).get("method"),
        "scored_groups": summary["scored_groups"],
        "mean_similarity": score,
        "unmatched_source_groups": summary.get("unmatched_source_groups"),
        "unmatched_translation_groups": summary.get("unmatched_translation_groups"),
    }
