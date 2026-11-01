"""Run a reviewed, bounded S2ST research batch outside the PersoDub app.

This is a subprocess entrypoint. No model, output or source audio is installed
into the normal dubbing pipeline. Every candidate stays a research artifact.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

from app.experimental.s2st_preview import render
from app.experimental.s2st_quality import evaluate_experiment
from app.experimental.seamless_batch import prepare, run_batch


def _state(path, value):
    pending = path.with_suffix(".json.part")
    with pending.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, path)


def execute(job_dir, indices, experiment_dir, model_dir, device="mps",
            *, prepare_fn=prepare, batch_fn=run_batch, evaluate_fn=evaluate_experiment,
            preview_fn=render):
    """Execute once; emit a persistent terminal state even on model failure."""
    folder = Path(experiment_dir).resolve()
    parent = folder.parent
    if not parent.is_dir() or folder.exists():
        raise FileExistsError("S2ST research output must be a new child directory")
    terminal = parent / "worker-state.json"
    if terminal.exists():
        raise FileExistsError("Worker state already exists")
    _state(terminal, {"state": "running", "started_at": time.time()})
    try:
        manifest = prepare_fn(job_dir, indices, folder)
        progress = batch_fn(folder, model_dir, device=device)
        quality = evaluate_fn(folder)
        _state(folder / "quality-triage.json", quality)
        generated = []
        skipped = []
        for entry in manifest["entries"]:
            index = entry["index"]
            verdict = next(
                (candidate for candidate in quality["cases"] if candidate["index"] == index),
                None,
            )
            if verdict is None or verdict["state"] != "TIMING_CANDIDATE_ONLY":
                skipped.append(index)
                continue
            preview_path = folder / ("preview-%03d.mp4" % index)
            try:
                record = preview_fn(
                    Path(job_dir) / "input.mp4",
                    folder / entry["output_wav"],
                    entry["start"], entry["end"], preview_path,
                )
                _state(folder / ("preview-%03d.json" % index), record)
                generated.append(index)
            except (OSError, ValueError, RuntimeError) as exc:
                # WAV and quality receipts remain valid and separately
                # downloadable even if a preview-only FFmpeg export fails.
                print("S2ST preview %s failed: %s" % (index, type(exc).__name__), flush=True)
                skipped.append(index)
        result = {
            "state": "done",
            "finished_at": time.time(),
            "generated_previews": generated,
            "skipped_previews": skipped,
            "completed_segments": progress["done"],
            "review_required": quality["review_required"],
        }
        _state(terminal, result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result
    except Exception as exc:
        error = {"state": "error", "finished_at": time.time(),
                 "error_type": type(exc).__name__}
        _state(terminal, error)
        traceback.print_exc(file=sys.stderr)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--indices", type=str, required=True)
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    args = parser.parse_args(argv)
    indices = [int(value) for value in args.indices.split(",")]
    execute(args.job_dir, indices, args.experiment_dir,
            args.model_dir, args.device)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
