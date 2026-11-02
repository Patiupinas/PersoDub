"""Offline CV3-style speaker-similarity diagnostic on matched TTS candidates.

This is NOT the official CV3-Eval ERes2Net/DNSMOS implementation. The optional
local WavLMForXVector model is a separate pretrained speaker-embedding proxy.
No model or dataset downloads, no source modifications or human-quality PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import wave
from collections import defaultdict
from pathlib import Path

SCHEMA_VERSION = 1
MAX_AUDIO_SECONDS = 30.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wav(path: Path) -> dict:
    with wave.open(str(path), "rb") as audio:
        sr, frames = audio.getframerate(), audio.getnframes()
        channels = audio.getnchannels()
        if (audio.getcomptype() != "NONE" or audio.getsampwidth() not in (2, 4)
                or sr not in (16000, 24000, 44100, 48000)
                or channels not in (1, 2)
                or not 0.2 <= frames / sr <= MAX_AUDIO_SECONDS):
            raise ValueError("Expected a bounded mono/stereo PCM WAV")
    return {
        "sha256": sha256(path), "duration_seconds": round(frames / sr, 6),
        "sample_rate": sr, "channels": channels,
    }


def _cosine(left, right):
    if len(left) != len(right) or len(left) < 2:
        raise ValueError("Incompatible speaker embeddings")
    l, r = [float(x) for x in left], [float(x) for x in right]
    if not all(math.isfinite(x) for x in l + r):
        raise ValueError("Non-finite speaker embedding")
    ll = math.sqrt(sum(x * x for x in l))
    rr = math.sqrt(sum(x * x for x in r))
    if ll < 1e-10 or rr < 1e-10:
        raise ValueError("Zero-vector speaker embedding")
    return round(sum(x * y for x, y in zip(l, r)) / (ll * rr), 6)


def _media(entry, root: Path, known: set[Path], name: str) -> dict:
    if type(entry) is not dict or not isinstance(entry.get("id"), str):
        raise ValueError(f"{name} needs stable id")
    if not entry["id"] or not entry["id"].isascii() or not all(
        c.isalnum() or c in "-_" for c in entry["id"]
    ):
        raise ValueError("Unsafe benchmark ID")
    raw = entry.get("file")
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{name} needs local WAV path")
    path = Path(raw)
    resolved = (path if path.is_absolute() else root / path).resolve(strict=True)
    if resolved.suffix.lower() != ".wav" or not resolved.is_file():
        raise ValueError("Speaker similarity accepts existing WAV files only")
    if resolved in known:
        raise ValueError("A benchmark WAV cannot serve as multiple independent examples")
    known.add(resolved)
    return {"id": entry["id"], "file": resolved, **_wav(resolved)}


def load_manifest(manifest: Path) -> dict:
    """Reject mismatched source anchors and unmatched AB candidate sets."""
    manifest = Path(manifest).resolve(strict=True)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    if type(raw) is not dict or raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Invalid speaker similarity manifest version")
    source_language, target_language = raw.get("source_language"), raw.get("target_language")
    control_record = raw.get("unrelated_control")
    if (source_language not in ("en", "de", "es") or target_language != "ru"
            or not isinstance(control_record, dict)
            or control_record.get("language") != "ru"):
        raise ValueError("Explicit EN/DE/ES source, RU target and RU control languages required")
    root = manifest.parent
    known = set()
    anchor_rows = raw.get("anchors")
    candidates = raw.get("candidates")
    if not isinstance(anchor_rows, list) or len(anchor_rows) != 2:
        raise ValueError("Exactly two independent original source anchors are required")
    if not isinstance(candidates, list) or len(candidates) < 3:
        raise ValueError("At least three voice candidate WAVs required")
    anchors = [_media(row, root, known, "anchor") for row in anchor_rows]
    if len({r["id"] for r in anchors}) != 2:
        raise ValueError("Duplicate source anchor ID")
    negative = _media(raw["unrelated_control"], root, known, "unrelated_control")
    by_case = defaultdict(list)
    parsed = []
    for row in candidates:
        audio = _media(row, root, known, "candidate")
        case, variant = row.get("case_id"), row.get("variant")
        text, seed, slot = row.get("target"), row.get("seed"), row.get("slot_seconds")
        if (not isinstance(case, str) or not case or not isinstance(variant, str)
                or not variant or not isinstance(text, str) or not text.strip()
                or type(seed) is not int or type(slot) not in (float, int)
                or not math.isfinite(slot) or slot <= 0):
            raise ValueError("Every candidate needs case, variant, target, seed and slot")
        by_case[case].append((variant, text, seed, slot))
        parsed.append({**audio, "case_id": case, "variant": variant,
                       "target": text, "seed": seed, "slot_seconds": float(slot)})
    variants = None
    for case, records in by_case.items():
        current = {item[0] for item in records}
        if (len(current) != len(records) or
                len({(item[1], item[2], item[3]) for item in records}) != 1):
            raise ValueError(f"Case {case} must have distinct variants and identical target/seed/slot")
        if variants is None:
            variants = current
        elif variants != current:
            raise ValueError("Each case must contain the same controlled variants")
    if len(by_case) < 2 or len(variants) < 2:
        raise ValueError("Multiple matched cases and variants are required")
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_sha256": sha256(manifest),
        "source_language": source_language, "target_language": target_language,
        "unrelated_control_language": "ru",
        "anchors": anchors, "unrelated_control": negative,
        "candidates": sorted(parsed, key=lambda row: (row["case_id"], row["variant"])),
    }


def evaluate(inputs: dict, embed) -> dict:
    """Produce paired, non-calibrated similarities with an unrelated control."""
    anchors = inputs["anchors"]
    controls = anchors + [inputs["unrelated_control"]]
    all_media = controls + inputs["candidates"]
    vectors = {item["file"]: embed(item["file"]) for item in all_media}
    for item in all_media:
        if _cosine(vectors[item["file"]], vectors[item["file"]]) < 0.9999:
            raise ValueError("Speaker encoder failed self-consistency")
    a, b = (vectors[x["file"]] for x in anchors)
    unrelated = vectors[inputs["unrelated_control"]["file"]]
    anchor_similarity = _cosine(a, b)
    negatives = {
        anchors[0]["id"]: _cosine(a, unrelated),
        anchors[1]["id"]: _cosine(b, unrelated),
    }
    cases, by_variant = [], defaultdict(list)
    unrelated_wins = 0
    for item in inputs["candidates"]:
        vector = vectors[item["file"]]
        scores = {anchor["id"]: _cosine(vectors[anchor["file"]], vector)
                  for anchor in anchors}
        average = round(sum(scores.values()) / len(scores), 6)
        control_score = _cosine(unrelated, vector)
        conflict = control_score >= average
        unrelated_wins += int(conflict)
        result = {
            "case_id": item["case_id"], "variant": item["variant"],
            "id": item["id"], "target": item["target"], "seed": item["seed"],
            "file_sha256": item["sha256"],
            "duration_seconds": item["duration_seconds"],
            "slot_seconds": item["slot_seconds"],
            "fits_source_slot": item["duration_seconds"] <= item["slot_seconds"] + 1e-6,
            "reference_cosines": scores, "mean_source_cosine": average,
            "unrelated_control_cosine": control_score,
            "unrelated_control_closer_than_source_mean": conflict,
            "source_minus_unrelated_cosine": round(average - control_score, 6),
        }
        cases.append(result)
        by_variant[item["variant"]].append(result)
    summary = {}
    for variant, records in sorted(by_variant.items()):
        summary[variant] = {
            "samples": len(records),
            "mean_source_cosine": round(
                sum(x["mean_source_cosine"] for x in records) / len(records), 6
            ),
            "mean_cosines_by_anchor": {
                anchor["id"]: round(sum(x["reference_cosines"][anchor["id"]]
                                        for x in records) / len(records), 6)
                for anchor in anchors
            },
            "source_slot_overruns": sum(not x["fits_source_slot"] for x in records),
        }
    return {
        "schema_version": 1,
        "status": "OBSERVED",
        "benchmark": "cv3_style_cached_wavlm_speaker_similarity",
        "official_cv3_eval_run": False,
        "official_eres2net_scoring": False,
        "source_language": inputs["source_language"],
        "target_language": inputs["target_language"],
        "unrelated_control_language": inputs["unrelated_control_language"],
        "unrelated_control_identity_independently_verified": False,
        "source_anchors_same_speaker_independently_verified": False,
        "cross_language_control_result": (
            "CONFLICTING_LANGUAGE_OR_SPEAKER_PROXY" if unrelated_wins
            else "UNVERIFIED_SINGLE_CONTROL"
        ),
        "unrelated_control_closer_cases": unrelated_wins,
        "unrelated_control_cases": len(cases),
        "speaker_similarity_model_selection_validated": False,
        "human_native_russian_accent_verified": False,
        "human_speaker_likeness_verified": False,
        "calibrated_similarity_acceptance": False,
        "source_identity_unverified": True,
        "target_cases": len({x["case_id"] for x in cases}),
        "model_sensitive_and_cross_language_confounded": True,
        "manifest_sha256": inputs["manifest_sha256"],
        "anchors": [
            {"id": row["id"], "sha256": row["sha256"],
             "duration_seconds": row["duration_seconds"]}
            for row in anchors
        ],
        "unrelated_control_sha256": inputs["unrelated_control"]["sha256"],
        "two_source_anchors_cosine": anchor_similarity,
        "source_vs_unrelated_cosines": negatives,
        "by_variant": summary,
        "cases": cases,
    }


def _wavlm_encoder(model_dir: Path):
    """Load a *local* preinstalled checkpoint, never a model hub name."""
    import numpy as np
    import soundfile as sf
    import torch
    from scipy.signal import resample_poly
    from transformers import WavLMForXVector

    model_dir = Path(model_dir).resolve(strict=True)
    for name in ("config.json", "model.safetensors"):
        if not (model_dir / name).is_file():
            raise ValueError("Offline WavLM model is missing " + name)
    torch.set_num_threads(min(torch.get_num_threads(), 4))
    model = WavLMForXVector.from_pretrained(
        str(model_dir), local_files_only=True, trust_remote_code=False
    ).eval()

    def encode(path: Path):
        audio, sr = sf.read(path, dtype="float32", always_2d=True)
        audio = audio.mean(axis=1)
        if sr != 16000:
            gcd = math.gcd(sr, 16000)
            audio = resample_poly(audio, 16000 // gcd, sr // gcd)
        if not np.all(np.isfinite(audio)) or np.max(np.abs(audio)) < 1e-6:
            raise ValueError("A speaker reference is silent or non-finite")
        with torch.inference_mode():
            result = model(torch.as_tensor(audio, dtype=torch.float32)[None, :])
        return result.embeddings.squeeze(0).cpu().float().tolist()

    return encode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    source = load_manifest(args.manifest)
    model_dir = args.model_dir.resolve(strict=True)
    report = evaluate(source, _wavlm_encoder(model_dir))
    report["model"] = {
        "model_family": "microsoft/wavlm-base-plus-sv",
        "weights_sha256": sha256(model_dir / "model.safetensors"),
        "config_sha256": sha256(model_dir / "config.json"),
        "device": "cpu", "backend": "transformers.WavLMForXVector",
        "platform": platform.machine(),
    }
    dest = args.out.resolve()
    if dest == args.manifest.resolve():
        raise ValueError("Result must not replace source manifest")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({
        "status": report["status"], "source_anchors": report["two_source_anchors_cosine"],
        "by_variant": report["by_variant"], "out": str(dest),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
