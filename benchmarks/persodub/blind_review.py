"""Make a blinded A/B listening pack without revealing provider assignments.

Inputs must be *preselected short* audio files. No media is downloaded, no
TTS model is run, and the private answer key must be saved outside the pack.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import secrets
import shutil
import subprocess
from pathlib import Path

VALID_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
MAX_CLIP_SECONDS = 45.0


def _resolve(root, raw):
    if not isinstance(raw, str) or not raw:
        raise ValueError("Audio source path is required")
    path = Path(raw)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_file():
        raise FileNotFoundError("A selected short audio file is missing")
    return path


def _duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True, timeout=30,
    )
    value = float(r.stdout.strip())
    if not 0 < value <= MAX_CLIP_SECONDS:
        raise ValueError("Blind reviewer inputs must be preselected <=45s clips")
    return value


def _neutral_wav(source, output):
    """Normalize containers/metadata equally; never add a voice label."""
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(source),
         "-map", "0:a:0", "-vn", "-map_metadata", "-1",
         "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(output)],
        capture_output=True, check=True, timeout=90,
    )


def _sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as data:
        for chunk in iter(lambda: data.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare(manifest_path: Path, review_dir: Path, key_path: Path,
            seed: int | None = None) -> dict:
    manifest_path = Path(manifest_path).resolve()
    review_dir = Path(review_dir).resolve()
    key_path = Path(key_path).resolve()
    if review_dir == key_path or review_dir in key_path.parents:
        raise ValueError("The assignment key must be outside the reviewer pack")
    if review_dir.exists() or key_path.exists():
        raise FileExistsError("Use new review-pack and private-key destinations")

    input_obj = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (input_obj.get("schema_version") != 1
            or not isinstance(input_obj.get("pairs"), list)
            or not input_obj["pairs"]):
        raise ValueError("Expected a nonempty pair manifest")
    root = manifest_path.parent
    ids = set()
    rows = []
    for entry in input_obj["pairs"]:
        case_id = entry.get("id")
        if not isinstance(case_id, str) or not VALID_ID.fullmatch(case_id):
            raise ValueError("IDs must contain only letters, digits, _ and -")
        if case_id in ids:
            raise ValueError("Duplicate pair ID")
        ids.add(case_id)
        baseline = _resolve(root, entry.get("baseline"))
        candidate = _resolve(root, entry.get("candidate"))
        reference = _resolve(root, entry["source"]) if entry.get("source") else None
        sources = [baseline, candidate] + ([reference] if reference else [])
        for media in sources:
            _duration(media)
        if _sha(baseline) == _sha(candidate):
            raise ValueError("Cannot blindly compare an audio file to itself")
        rows.append((case_id, baseline, candidate, reference, entry.get("target_text", "")))

    rng_seed = secrets.randbits(63) if seed is None else seed
    rng = random.Random(rng_seed)
    assignment = [False] * (len(rows) // 2) + [True] * (len(rows) - len(rows) // 2)
    rng.shuffle(assignment)
    rng.shuffle(rows)
    review_dir.mkdir(parents=True, exist_ok=False)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    solution = {"schema_version": 1, "suite_id": input_obj.get("suite_id"),
                "seed": rng_seed, "pairs": []}
    try:
        with (review_dir / "ratings_template.csv").open("x", encoding="utf-8", newline="") as f:
            fields = [
                "rater_id", "pair_id", "A_file", "B_file", "source_file",
                "target_text", "A_accent_1to5", "B_accent_1to5",
                "A_voice_1to5", "B_voice_1to5", "A_pauses_1to5",
                "B_pauses_1to5", "A_original_audibility_1to5",
                "B_original_audibility_1to5", "preference_A_B_tie", "notes",
            ]
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for (case_id, baseline, candidate, reference, target_text), switched in zip(
                rows, assignment
            ):
                folder = review_dir / case_id
                folder.mkdir()
                a, b = (candidate, baseline) if switched else (baseline, candidate)
                _neutral_wav(a, folder / "A.wav")
                _neutral_wav(b, folder / "B.wav")
                if reference:
                    _neutral_wav(reference, folder / "source.wav")
                writer.writerow({
                    "pair_id": case_id, "A_file": case_id + "/A.wav",
                    "B_file": case_id + "/B.wav",
                    "source_file": case_id + "/source.wav" if reference else "",
                    "target_text": target_text,
                })
                solution["pairs"].append({
                    "id": case_id,
                    "A": "candidate" if switched else "baseline",
                    "B": "baseline" if switched else "candidate",
                    "baseline_sha256": _sha(baseline),
                    "candidate_sha256": _sha(candidate),
                })
        # Keep the A/B mapping outside the reviewer package and readable only
        # by its owner so blind assessors cannot infer system assignments.
        fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(json.dumps(solution, indent=2) + "\n")
    except Exception:
        shutil.rmtree(review_dir)
        if key_path.exists():
            key_path.unlink()
        raise
    return {"pairs": len(rows), "review_dir": str(review_dir),
            "key_outside_review_pack": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)
    result = prepare(args.pairs, args.review_dir, args.private_key, args.seed)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
