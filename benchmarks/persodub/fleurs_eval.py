"""Bounded, reproducible FLEURS ASR evaluation using local test-set WAVs.

No dataset/model download, no transcript rewriting and no dependence on
WhisperNotes runtime. Reuse the project's independent WER/CER implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import wave
from pathlib import Path

from benchmarks.persodub.metrics import asr_metrics

LOCALES = {"en": "en_us", "de": "de_de", "es": "es_419", "ru": "ru_ru"}
DEFAULT_SEED = "persodub-fleurs-test-v1"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def _wav_info(path: Path) -> tuple[int, float]:
    with wave.open(str(path), "rb") as audio:
        if audio.getcomptype() != "NONE" or audio.getnframes() <= 0:
            raise ValueError("Test WAV must contain real uncompressed audio")
        duration = audio.getnframes() / audio.getframerate()
        if not 0.2 <= duration <= 60.0:
            raise ValueError("FLEURS short-speech sample outside expected bounds")
        return audio.getframerate(), duration


def select(manifest: Path, root: Path, language: str, count: int, seed: str = DEFAULT_SEED):
    """Freeze a deterministic shortlist of external test references.

    The local metadata belongs to a source corpus, not to synthesized output.
    IDs, source split, audio integrity and path ownership are validated before
    choosing cases, to avoid silently scoring a different dataset.
    """
    if language not in LOCALES or type(count) is not int or not 1 <= count <= 30:
        raise ValueError("Expected supported language and 1..30 clips")
    if not isinstance(seed, str) or not 1 <= len(seed) <= 128:
        raise ValueError("Invalid frozen selection seed")
    raw_path = Path(manifest).resolve(strict=True)
    root = Path(root).resolve(strict=True)
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    if raw.get("language") != language or raw.get("source") != (
        f"google/fleurs {LOCALES[language]} test (professional transcripts)"
    ):
        raise ValueError("FLEURS source/language/test split mismatch")
    clips = raw.get("clips")
    if not isinstance(clips, list) or len(clips) < count:
        raise ValueError("Insufficient frozen FLEURS test clips")
    seen_ids, seen_paths = set(), set()
    validated = []
    for entry in clips:
        if type(entry) is not dict:
            raise ValueError("Invalid sample record")
        case_id = entry.get("id")
        candidate = entry.get("wav")
        text = entry.get("rawText")
        if (not isinstance(case_id, str) or not case_id
                or not isinstance(candidate, str) or not candidate
                or not isinstance(text, str) or not text.strip()):
            raise ValueError("Every test clip needs ID, audio and independent transcript")
        if case_id in seen_ids:
            raise ValueError("Duplicate dataset utterance ID")
        seen_ids.add(case_id)
        relative = Path(candidate)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Dataset WAV must be within local corpus root")
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() != ".wav":
            raise ValueError("Invalid source WAV path")
        if path in seen_paths:
            raise ValueError("Duplicate dataset source WAV")
        seen_paths.add(path)
        sample_rate, duration = _wav_info(path)
        declared_duration = entry.get("durationSeconds")
        if (type(declared_duration) not in (float, int) or
                not math.isfinite(declared_duration) or
                abs(declared_duration - duration) > 0.15):
            raise ValueError("Dataset metadata/audio duration mismatch")
        validated.append({
            "id": case_id, "file": path, "text": text,
            "duration_s": round(duration, 5), "sample_rate": sample_rate,
        })
    selected = sorted(
        validated,
        key=lambda row: (
            hashlib.sha256(f"{seed}|{language}|{row['id']}".encode()).hexdigest(),
            row["id"],
        ),
    )[:count]
    return {
        "language": language, "source": raw["source"],
        "manifest_sha256": _sha(raw_path), "selection_seed": seed,
        "eligible_cases": len(validated), "selected": selected,
    }


def run(selection: dict, transcribe) -> dict:
    """Score each frozen external transcript against a distinct ASR decode."""
    output = []
    for row in selection["selected"]:
        recognized = transcribe(row["file"], selection["language"])
        if not isinstance(recognized, str):
            raise ValueError("ASR decoder must return a text string")
        metrics = asr_metrics(row["text"], recognized)
        result = {
            "id": row["id"], "source_sha256": _sha(row["file"]),
            "source_duration_s": row["duration_s"],
            "sample_rate": row["sample_rate"],
            "reference": row["text"], "recognized": recognized,
            **metrics,
        }
        output.append(result)
        print(f"FLEURS {selection['language']} {row['id']} WER={metrics['wer']:.4f}", flush=True)
    total_words = sum(r["reference_words"] for r in output)
    total_characters = sum(r["reference_characters"] for r in output)
    return {
        "schema_version": 1, "status": "OBSERVED",
        "oracle": "original FLEURS test transcript, not model output",
        "human_accent_validated": False,
        "source_timbre_validated": False,
        "language": selection["language"], "source": selection["source"],
        "source_manifest_sha256": selection["manifest_sha256"],
        "frozen_selection_seed": selection["selection_seed"],
        "eligible_cases": selection["eligible_cases"],
        "selected_cases": len(output),
        "summary": {
            "total_words": total_words,
            "word_errors": sum(r["word_errors"] for r in output),
            "corpus_wer": round(sum(r["word_errors"] for r in output) / total_words, 6),
            "total_characters": total_characters,
            "character_errors": sum(r["character_errors"] for r in output),
            "corpus_cer": round(
                sum(r["character_errors"] for r in output) / total_characters, 6),
        },
        "clips": output,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--language", choices=LOCALES, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    selection = select(args.manifest, args.root, args.language, args.limit, args.seed)
    model_dir = args.model_dir.resolve(strict=True)
    if not model_dir.is_dir() or not (model_dir / "model.bin").is_file():
        raise ValueError("Offline CTranslate2 ASR model directory is required")
    from faster_whisper import WhisperModel

    decoder = WhisperModel(str(model_dir), device="cpu", compute_type="int8")

    def transcribe(file: Path, language: str):
        segments, _ = decoder.transcribe(
            str(file), language=language, beam_size=5, temperature=0.0,
            condition_on_previous_text=False, vad_filter=False,
            word_timestamps=False,
        )
        return " ".join(s.text.strip() for s in segments)

    result = run(selection, transcribe)
    result["model"] = {
        "framework": "faster-whisper", "device": "cpu", "compute_type": "int8",
        "config_sha256": _sha(model_dir / "config.json"),
        "model_bin_sha256": _sha(model_dir / "model.bin"),
        "hardware": platform.machine(),
    }
    destination = args.out.resolve()
    if destination == args.manifest.resolve() or destination.is_relative_to(args.root.resolve()):
        raise ValueError("Benchmark output must not replace corpus metadata or source media")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"status": result["status"], "summary": result["summary"],
                      "out": str(destination)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
