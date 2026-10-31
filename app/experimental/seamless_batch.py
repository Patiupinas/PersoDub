"""Prepare and run resumable local SeamlessM4T S2ST experiments.

The job source video is never copied or modified. Only explicitly selected
speech candidates are processed, and no classification of singing is inferred.
Models are loaded once per batch, which is essential for multi-hour lessons.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import subprocess
import time
from pathlib import Path

from app.experimental.seamless_s2st import (
    MAX_INPUT_SECONDS,
    MODEL_REVISION,
    SeamlessSession,
    run,
    sha256_file,
)


def _write_json_atomic(path, value):
    pending = path.with_suffix(path.suffix + ".part")
    with pending.open("w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(pending, path)


def prepare(job_dir, indices, experiment_dir):
    """Make source-clock WAVs for selected 30s speech segments."""
    job = Path(job_dir).resolve()
    dest = Path(experiment_dir).resolve()
    if dest.exists():
        raise FileExistsError("Experiment directory must be new")
    source = job / "input.mp4"
    if not source.is_file() or not (job / "speakers.json").is_file():
        raise ValueError("Completed source job must contain video and source cues")
    cues = json.loads((job / "speakers.json").read_text(encoding="utf-8"))
    if not isinstance(cues, list) or not cues:
        raise ValueError("Source cues must be a non-empty list")
    if not indices or len(indices) != len(set(indices)):
        raise ValueError("Select distinct source cue indices")
    if any(type(i) is not int or i < 0 or i >= len(cues) for i in indices):
        raise ValueError("Source cue index is outside source transcript")
    requests = []
    for index in indices:
        cue = cues[index]
        start, end = cue.get("start"), cue.get("end")
        if any(type(n) not in (int, float) or not math.isfinite(n) for n in (start, end)):
            raise ValueError("Non-finite source cue")
        if start < 0 or not (0 < end - start <= MAX_INPUT_SECONDS):
            raise ValueError("Selected cue exceeds 30-second speech bound")
        requests.append({
            "index": index, "start": start, "end": end,
            "speaker_label": cue.get("speaker", "unknown"),
            "review_state": "REVIEW",
        })
    dest.mkdir(parents=True, exist_ok=False)
    try:
        entries = []
        for cue in requests:
            index = cue["index"]
            input_file = dest / ("source-%03d.wav" % index)
            subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-i", str(source),
                 "-ss", "%.6f" % cue["start"],
                 "-t", "%.6f" % (cue["end"] - cue["start"]),
                 "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
                 "-c:a", "pcm_s16le", str(input_file)],
                capture_output=True, check=True, timeout=90,
            )
            entries.append({
                **cue, "source_clip": input_file.name,
                "source_sha256": sha256_file(input_file),
                "output_wav": "ru-%03d.wav" % index,
                "output_report": "ru-%03d.json" % index,
            })
        metadata = {
            "schema_version": 1, "model_revision": MODEL_REVISION,
            "job_source_video_sha256": sha256_file(source),
            "source_job_dir": str(job),
            "entries": entries,
            "intended_use": "benchmark_only",
            "singing_translation_approved": False,
        }
        _write_json_atomic(dest / "plan.json", metadata)
        return metadata
    except Exception:
        for path in dest.iterdir():
            if path.is_file():
                path.unlink()
        dest.rmdir()
        raise


def _checked_clip(path, relative, digest):
    if type(relative) is not str or Path(relative).name != relative:
        raise ValueError("Invalid clip path in experiment plan")
    source = path / relative
    if not source.is_file() or sha256_file(source) != digest:
        raise ValueError("Source clip hash does not match experiment plan")
    return source


def run_batch(experiment_dir, model_dir, device="mps", session_factory=SeamlessSession):
    """One model load and per-clip receipts, safe to restart after interruption."""
    root = Path(experiment_dir).resolve()
    plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    if plan.get("schema_version") != 1 or plan.get("model_revision") != MODEL_REVISION:
        raise ValueError("Unexpected S2ST experiment plan version")
    job_dir = Path(plan.get("source_job_dir", ""))
    source_video = job_dir / "input.mp4"
    if not source_video.is_file() or sha256_file(source_video) != plan["job_source_video_sha256"]:
        raise ValueError("Original source video hash changed")
    entries = plan.get("entries")
    if type(entries) is not list or not entries:
        raise ValueError("No source utterance entries")
    if device not in ("mps", "cpu"):
        raise ValueError("Invalid compute device")
    model_dir = Path(model_dir).expanduser().resolve()

    lock = root / ".experiment.lock"
    with lock.open("a+") as owner:
        try:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another experiment already owns this output directory") from None
        ready = []
        pending = []
        for entry in entries:
            index = entry.get("index")
            if type(index) is not int or index < 0:
                raise ValueError("Invalid source utterance index")
            if (entry.get("source_clip") != "source-%03d.wav" % index
                    or entry.get("output_wav") != "ru-%03d.wav" % index
                    or entry.get("output_report") != "ru-%03d.json" % index):
                raise ValueError("Experiment plan file names differ from selected cue")
            input_wav = _checked_clip(
                root, entry["source_clip"], entry["source_sha256"],
            )
            wav = root / entry["output_wav"]
            report = root / entry["output_report"]
            if wav.exists() and report.exists():
                receipt = json.loads(report.read_text(encoding="utf-8"))
                if (receipt.get("source_sha256") == entry["source_sha256"]
                        and receipt.get("model_revision") == MODEL_REVISION
                        and receipt.get("output_sha256") == sha256_file(wav)):
                    ready.append(entry["index"])
                    continue
                raise ValueError("Invalid prior S2ST result; use a fresh experiment directory")
            if wav.exists() != report.exists():
                # This clip may have been interrupted between WAV and receipt
                # commits. Never trust the orphaned half; recompute that clip.
                if wav.exists():
                    wav.unlink()
                if report.exists():
                    report.unlink()
            pending.append((entry, input_wav, wav, report))

        progress = {"schema_version": 1, "total": len(entries),
                    "done": len(ready), "reused": len(ready),
                    "failed": 0, "state": "running", "updated_at": time.time()}
        _write_json_atomic(root / "progress.json", progress)
        session = session_factory(model_dir, device) if pending else None
        try:
            for entry, input_wav, wav, report in pending:
                try:
                    run(input_wav, wav, model_dir, device=device, report=report,
                        infer=session)
                except Exception:
                    progress["failed"] += 1
                    progress["state"] = "error"
                    progress["updated_at"] = time.time()
                    _write_json_atomic(root / "progress.json", progress)
                    raise
                progress["done"] += 1
                progress["updated_at"] = time.time()
                _write_json_atomic(root / "progress.json", progress)
            progress["state"] = "done"
            progress["updated_at"] = time.time()
            _write_json_atomic(root / "progress.json", progress)
        finally:
            if session is not None:
                session.close()
        return progress


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--job-dir", type=Path, required=True)
    prep.add_argument("--indices", type=str, required=True)
    prep.add_argument("--experiment-dir", type=Path, required=True)
    resume = commands.add_parser("run")
    resume.add_argument("--experiment-dir", type=Path, required=True)
    resume.add_argument("--model-dir", type=Path, required=True)
    resume.add_argument("--device", choices=("cpu", "mps"), default="mps")
    args = parser.parse_args(argv)
    if args.action == "prepare":
        indices = [int(i) for i in args.indices.split(",")]
        output = prepare(args.job_dir, indices, args.experiment_dir)
    else:
        output = run_batch(args.experiment_dir, args.model_dir, args.device)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
