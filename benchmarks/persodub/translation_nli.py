"""Optional independent cross-lingual NLI probe for translation-quality triage.

Only a diagnostic experiment. NLI entailment scores are not calibrated
translation scores, and automatic output cannot replace bilingual review.
"""
from __future__ import annotations

import math
from typing import Any

DEFAULT_NLI_MODEL = "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli"


def score_nli_pairs(
    pairs: list[tuple[str, str]],
    *,
    model_id: str = DEFAULT_NLI_MODEL,
    device: str = "cpu",
    allow_download: bool = False,
    batch_size: int = 8,
) -> tuple[list[dict[str, float]], dict[str, Any]]:
    """Measure both directions to expose possible omission versus addition.

    The directions are English as premise versus Russian as hypothesis
    and Russian as premise versus English as hypothesis, respectively.
    """
    if not pairs:
        return [], {"method": "cross_language_nli", "status": "NOT_RUN"}
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if any(not isinstance(a, str) or not a.strip() or
           not isinstance(b, str) or not b.strip() for a, b in pairs):
        raise ValueError("NLI requires non-empty source and target strings")

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    options = {
        "trust_remote_code": False,
        "local_files_only": not allow_download,
    }
    tokenizer = AutoTokenizer.from_pretrained(model_id, **options)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_id, **options
    ).to(device).eval()

    labels = {str(name).lower(): int(idx)
              for idx, name in model.config.id2label.items()}
    if not {"entailment", "contradiction", "neutral"}.issubset(labels):
        raise ValueError("NLI model must explicitly define all three labels")

    sequences = []
    for a, b in pairs:
        sequences.extend([(a, b), (b, a)])
    probs = []
    with torch.inference_mode():
        for start in range(0, len(sequences), batch_size):
            chunk = sequences[start:start + batch_size]
            batch = tokenizer(
                [pair[0] for pair in chunk],
                [pair[1] for pair in chunk],
                padding=True,
                truncation=True,
                max_length=256,
                return_tensors="pt",
            )
            batch = {k: v.to(device) for k, v in batch.items()}
            output = model(**batch).logits.softmax(dim=-1)
            probs.extend(output.cpu().tolist())

    rows = []
    for i in range(len(pairs)):
        forward, reverse = probs[2 * i:2 * i + 2]
        left = float(forward[labels["entailment"]])
        right = float(reverse[labels["entailment"]])
        contradiction = max(
            float(forward[labels["contradiction"]]),
            float(reverse[labels["contradiction"]]),
        )
        if not all(math.isfinite(x) for x in (left, right, contradiction)):
            raise ValueError("NLI model produced invalid probability")
        rows.append({
            "entailment_source_to_target": round(left, 6),
            "entailment_target_to_source": round(right, 6),
            "symmetric_entailment": round(min(left, right), 6),
            "contradiction_max": round(contradiction, 6),
        })
    return rows, {
        "method": "bidirectional_cross_language_nli",
        "model": model_id,
        "model_commit": getattr(model.config, "_commit_hash", None),
        "device": device,
        "labels": labels,
        "model_is_translation_quality_estimator": False,
        "calibrated_quality_threshold": False,
    }
