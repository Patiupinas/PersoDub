"""Optional local-only AST inference over SHA-frozen, publisher-labelled audio.

Use an isolated audio ML Python environment, NOT the PersoDub core venv.
Does not download weights, change the production pipeline or emit dubbing actions.
"""

import argparse
import hashlib
import json
from pathlib import Path

from app.vocal_audio_tag_benchmark import _validate_sources


def _sha_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _model_data(model_dir, original_evidence):
    import torch
    from transformers import ASTFeatureExtractor, ASTForAudioClassification

    frozen = original_evidence["model_provenance"]["ast"]
    checkpoint = Path(model_dir) / "model.safetensors"
    if _sha_file(checkpoint) != frozen["weights_sha256"]:
        raise ValueError("AST model weights SHA differ from frozen benchmark")
    processor = ASTFeatureExtractor.from_pretrained(
        str(model_dir), local_files_only=True
    )
    network = ASTForAudioClassification.from_pretrained(
        str(model_dir), local_files_only=True
    ).eval()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    network = network.to(device)
    lookup = {
        str(name): int(idx) for idx, name in network.config.id2label.items()
    }
    groups = {
        key: [lookup[label] for label in labels if label in lookup]
        for key, labels in frozen["ontology"].items()
    }
    if any(not ids for ids in groups.values()):
        raise ValueError("AST AudioSet label groups cannot be resolved")
    return torch, processor, network, device, groups


def _classify(waveform, torch, processor, network, device, groups):
    import numpy as np

    inputs = processor(
        waveform, sampling_rate=16000, return_tensors="pt"
    ).input_values.to(device)
    with torch.inference_mode():
        logits = network(inputs).logits[0].float().cpu().numpy()
    probability = 1 / (1 + np.exp(-np.clip(logits, -50, 50)))
    scores = {
        key: round(float(max(probability[ids])), 6)
        for key, ids in groups.items()
    }
    return scores, sorted(scores, key=lambda key: -scores[key])


def infer_selected(source_manifest, reference_evidence, source_index, audio_root,
                   model_dir, source_ids=None):
    import librosa

    sources = _validate_sources(source_manifest)
    index = json.loads(Path(source_index).read_text(encoding="utf-8"))
    pool = [
        key for key, source in sources.items()
        if source["dataset"] != "RAVDESS-speech"
        or source.get("actor") not in ("07", "08")
    ]
    selected = set(source_ids) if source_ids else set(pool)
    if not selected or not selected <= set(pool):
        raise ValueError("unknown or unsupported selected source")
    torch, processor, network, device, groups = _model_data(
        model_dir, reference_evidence
    )
    results = []
    for source_id in pool:
        if source_id not in selected:
            continue
        source = sources[source_id]
        record = index.get(source_id)
        if not isinstance(record, dict) or not record.get("wav_name"):
            raise ValueError("selected WAV not present in download index")
        path = Path(audio_root) / record["wav_name"]
        if _sha_file(path) != source["wav_sha256"]:
            raise ValueError("selected original WAV was changed")
        pcm, rate = librosa.load(str(path), sr=16000, mono=True)
        count = 10 * rate
        begin = max(0, (len(pcm) - count) // 2)
        crop = pcm[begin:begin + count]
        scores, ranking = _classify(
            crop, torch, processor, network, device, groups
        )
        results.append({
            "source_id": source_id,
            "wav_sha256": source["wav_sha256"],
            "crop_start_seconds": round(begin / rate, 3),
            "crop_end_seconds": round((begin + len(crop)) / rate, 3),
            "category_scores": scores,
            "category_ranking": ranking,
        })
    return {
        "schema_version": 1,
        "artifact_kind": "fresh_ast_inference_without_gold_promotion",
        "model_weights_sha256": reference_evidence["model_provenance"]["ast"]["weights_sha256"],
        "model_device": device,
        "selected_clips": len(results),
        "predictions": results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Re-run local AST on preselected original clips")
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--audio-root", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--source-id", action="append")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error("output must be a new file")
    try:
        result = infer_selected(
            json.loads(args.sources.read_text(encoding="utf-8")),
            json.loads(args.evidence.read_text(encoding="utf-8")),
            args.source_index, args.audio_root, args.model_dir, args.source_id,
        )
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"AST inference rejected: {exc}\n")
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"AST source-bound predictions: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
