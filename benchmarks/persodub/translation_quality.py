"""Reference-free translation quality triage for source-bound PersoDub SRT files.

This tool measures cross-language semantic similarity and subtitle coverage.
Scores are diagnostic proxies, not human-grounded translation acceptance.
No source file is modified, no weights are bundled with the application.

Usage:
  python -m benchmarks.persodub.translation_quality \
    --source original.srt --translation translated.srt --out quality.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from pathlib import Path

from app.text.srt import parse_srt

SCHEMA_VERSION = 1
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _read_cues(path: Path) -> list[dict]:
    cues = parse_srt(path.read_text(encoding="utf-8-sig"))
    if not cues:
        raise ValueError(f"No subtitle cues found in {path.name}")
    previous_start = -1.0
    for cue in cues:
        start, end = cue["start"], cue["end"]
        if not all(math.isfinite(x) for x in (start, end)):
            raise ValueError("Non-finite subtitle timestamp")
        if start < previous_start or start < 0 or end <= start:
            raise ValueError("Unsorted or invalid subtitle timestamp")
        previous_start = start
    return cues


def _align(source: list[dict], translation: list[dict]) -> list[dict]:
    """Return bounded source-clock alignment with explicit missing spans."""
    from benchmarks.persodub.translation_alignment import align_cues

    return align_cues(source, translation)

def _number_tokens(text: str) -> list[str]:
    """Numbers are only potential review hints, not semantic error proof."""
    import re

    return sorted(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)", text))


def _embedding_scores(pairs: list[tuple[str, str]], model_id: str,
                      device: str, allow_download: bool) -> tuple[list[float], dict]:
    """Use a separate multilingual encoder, not the translation generator."""
    import torch
    import torch.nn.functional as functional
    from transformers import AutoModel, AutoTokenizer

    kwargs = {"local_files_only": not allow_download, "trust_remote_code": False}
    tokenizer = AutoTokenizer.from_pretrained(model_id, **kwargs)
    model = AutoModel.from_pretrained(model_id, **kwargs).to(device).eval()
    texts = [item for pair in pairs for item in pair]
    vectors = []
    with torch.inference_mode():
        for start in range(0, len(texts), 8):
            batch = tokenizer(
                texts[start:start + 8],
                padding=True,
                truncation=True,
                max_length=256,
                return_tensors="pt",
            )
            batch = {name: value.to(device) for name, value in batch.items()}
            last = model(**batch).last_hidden_state
            mask = batch["attention_mask"].unsqueeze(-1)
            pooled = (last * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
            pooled = functional.normalize(pooled, p=2, dim=1)
            vectors.extend(pooled.cpu().tolist())

    scores = [round(sum(a * b for a, b in zip(vectors[2 * i],
                                                vectors[2 * i + 1])), 6)
              for i in range(len(pairs))]
    metadata = {
        "method": "multilingual_embedding_cosine",
        "model": model_id,
        "model_commit": getattr(model.config, "_commit_hash", None),
        "device": device,
        "higher_is_more_similar": True,
        "calibrated_quality_threshold": False,
    }
    return scores, metadata


def _comet_scores(pairs: list[tuple[str, str]], checkpoint: Path) -> tuple[list[float], dict]:
    """Use a pre-authorized, locally available referenceless COMET checkpoint."""
    from comet import load_from_checkpoint

    model = load_from_checkpoint(str(checkpoint))
    outputs = model.predict(
        [{"src": src, "mt": mt} for src, mt in pairs],
        batch_size=4,
        gpus=0,
    )
    return [round(float(score), 6) for score in outputs.scores], {
        "method": "comet_reference_free",
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": _sha256(checkpoint),
        "higher_is_more_similar": True,
        "calibrated_quality_threshold": False,
    }


def evaluate(source_file: Path, translation_file: Path,
             score_fn=None, scorer: str = "embedding",
             model_id: str = DEFAULT_MODEL, device: str = "cpu",
             allow_download: bool = False,
             comet_checkpoint: Path | None = None) -> dict:
    """Return measured scores and all unsupported/unaligned intervals."""
    source_file = Path(source_file).resolve()
    translation_file = Path(translation_file).resolve()
    if source_file == translation_file:
        raise ValueError("Source and translation must be different files")
    source = _read_cues(source_file)
    translation = _read_cues(translation_file)
    groups = _align(source, translation)
    aligned = [row for row in groups
               if row["source_text"] and row["translation_text"]]
    pairs = [(row["source_text"], row["translation_text"]) for row in aligned]
    metadata = {"method": "not_measured"}
    if pairs:
        if score_fn is not None:
            values = score_fn(pairs)
            metadata = {"method": "test_injected_scorer"}
        elif scorer == "embedding":
            values, metadata = _embedding_scores(
                pairs, model_id, device, allow_download
            )
        elif scorer == "comet":
            if comet_checkpoint is None or not comet_checkpoint.is_file():
                raise ValueError("COMET requires an existing --comet-checkpoint")
            values, metadata = _comet_scores(pairs, comet_checkpoint)
        else:
            raise ValueError(f"Unknown scorer: {scorer}")

        if len(values) != len(aligned) or not all(
            isinstance(x, (int, float)) and math.isfinite(x) for x in values
        ):
            raise ValueError("Scorer returned incomplete or non-finite results")
        for group, value in zip(aligned, values):
            group["semantic_similarity"] = round(float(value), 6)

    for group in groups:
        flags = []
        if not group["source_cues"] or not group["source_text"]:
            flags.append("no_aligned_source")
        if not group["translation_cues"] or not group["translation_text"]:
            flags.append("missing_translation")
        if (group["source_text"] and group["translation_text"]
                and _number_tokens(group["source_text"])
                != _number_tokens(group["translation_text"])):
            flags.append("numerals_differ_review")
        group["review_flags"] = flags

    scored = [row["semantic_similarity"] for row in groups
              if "semantic_similarity" in row]
    # Rank only: model scores are not calibrated against human judgments.
    review_order = sorted(
        range(len(groups)),
        key=lambda idx: (
            0 if groups[idx]["review_flags"] else 1,
            groups[idx].get("semantic_similarity", -1),
            groups[idx]["start_s"],
        ),
    )
    for rank, index in enumerate(review_order, 1):
        groups[index]["review_rank"] = rank
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "OBSERVED" if scored else "NOT_RUN",
        "semantic_quality_certified": False,
        "input": {
            "source_sha256": _sha256(source_file),
            "translation_sha256": _sha256(translation_file),
            "source_cues": len(source),
            "translation_cues": len(translation),
        },
        "alignment": "bounded_monotone_time_dp_v1",
        "model": metadata,
        "summary": {
            "groups": len(groups),
            "scored_groups": len(scored),
            "unmatched_source_groups": sum(
                not row["translation_cues"] for row in groups),
            "unmatched_translation_groups": sum(
                not row["source_cues"] for row in groups),
            "mean_similarity": round(sum(scored) / len(scored), 6)
            if scored else None,
            "lowest_similarity": min(scored) if scored else None,
        },
        "groups": groups,
        "environment": {"python_platform": platform.platform()},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--translation", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--scorer", choices=["embedding", "comet"],
                        default="embedding")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    parser.add_argument("--allow-download", action="store_true")
    parser.add_argument("--comet-checkpoint", type=Path)
    args = parser.parse_args(argv)
    report = evaluate(
        args.source, args.translation, scorer=args.scorer,
        model_id=args.model, device=args.device,
        allow_download=args.allow_download,
        comet_checkpoint=args.comet_checkpoint,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "summary": report["summary"],
        "output": str(args.out),
    }, ensure_ascii=False))
    return 0 if report["status"] == "OBSERVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
