"""Subprocess bridge to app/scripts/qwen_score_takes.py (the CAM++/whisper take
scorer). The app's own Python 3.8 venv has neither onnxruntime nor torch, so
scoring runs as a separate process under QWEN_SCORER_PYTHON (config.py) --
the same "run a heavy tool in its own process, parse its JSON" convention
app/separate.py and app/diar_campplus_client.py follow.

Graceful degradation is the whole point of this module: any failure (missing
interpreter, missing script, subprocess crash/timeout, bad JSON, or the
scorer itself reporting ok=false) returns None instead of raising, so
app/qwen_pipeline.synth_lines can fall back to single-take behavior and the
dub job still completes.

Input JSON handed to the scorer:
  {"language": "es" (a Whisper code; null = detect), "speakers": {spk: ref_wav_path, ...},
   "lines": [{"i": int, "spk": str, "usable": float, "text": str,
              "takes": [{"k": int, "path": str}, ...]}, ...]}
Output JSON the scorer writes back:
  {"ok": true, "lines": {"<i>": [{"k", "sim", "sim_other", "asr", "dur",
                                  "usable", "spk", "emb"}, ...]}}
  or {"ok": false, "error": "..."} on failure.
"""
import contextlib
import json
import os
import subprocess
import time
from typing import Callable, Dict, List, Optional

from app.config import LANGUAGE_NAMES, QWEN_SCORER_PYTHON

SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "qwen_score_takes.py")


def _scorer_asr_timeout_per_take() -> float:
    """Per-take ASR seconds this parent budgets for the child -- the SAME
    PERSODUB_SCORER_ASR_TIMEOUT env var and default-15 garbage-safe parse
    app/scripts/qwen_score_takes.py uses for its own ASR_BATCH_TIMEOUT_PER_FILE,
    read live (not cached at import time) so the two actually stay in sync
    (e.g. kit.env's 60) instead of this parent silently hardcoding 15."""
    try:
        return float(os.environ.get("PERSODUB_SCORER_ASR_TIMEOUT", "15"))
    except (TypeError, ValueError):
        return 15.0


def read_asr_progress(work_dir, now=None):
    """Return bounded counters for the active CPU Whisper scorer, never filenames.

    This is advisory job progress, not a persistent job-state owner. The
    separate source-bound ASR checkpoint survives failures; this small status
    file is deleted when the scorer returns and expires if a process vanishes.
    """
    path = os.path.join(work_dir, "qwen_scorer_asr_progress.json")
    try:
        if os.path.getsize(path) > 4096:
            return None
        with open(path, encoding="utf-8") as file:
            value = json.load(file)
        clock = time.time() if now is None else now
        done, total, reused = (value.get(key) for key in ("done", "total", "reused"))
        stamp = value.get("updated_at")
        if (
            type(value) is not dict
            or value.get("schema_version") != 1 or value.get("phase") != "asr"
            or any(type(n) is not int for n in (done, total, reused))
            or not 0 <= reused <= done <= total <= 1000000
            or type(stamp) not in (int, float)
            or not 0 <= clock - stamp <= 180
        ):
            return None
        return {"phase": "asr", "done": done, "total": total, "reused": reused}
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def whisper_code(language) -> Optional[str]:
    """The Whisper code for a dub language, given as the app passes it (a name
    like "Spanish" or a code like "es"); None lets Whisper detect it. Every
    language the local path speaks (LANGUAGE_NAMES) is one Whisper knows by
    the same code. Reading everything but Korean as English scored a correct
    Spanish take as a poor one, so High quality picked by voice alone."""
    lang = str(language or "").strip().lower()
    for code, name in LANGUAGE_NAMES.items():
        if lang in (code, name.lower()):
            return code
    return None


def score_takes(
    speaker_ref_paths: Dict[str, str],
    lines_payload: List[dict],
    language: str,
    work_dir: str,
    log: Optional[Callable[[str], None]] = None,
    timeout: int = 900,
) -> Optional[Dict[int, List[dict]]]:
    """Score every candidate take of every line. Returns {line_index: [scored
    take dicts]}, or None if scoring is unavailable/fails for any reason
    (never raises -- see module docstring)."""
    log = log or (lambda m: None)
    # Scale the subprocess ceiling with the actual take count: embeddings + batch
    # ASR on N takes cannot fit a fixed 900s once N grows (measured 2026-07-30:
    # 88 takes under CPU contention). Per-take budget mirrors the scorer's own
    # ASR budget (_scorer_asr_timeout_per_take, same env var) so the two
    # actually stay in sync; the fixed floor stays for small jobs.
    total_takes = sum(len(line.get("takes") or []) for line in lines_payload)
    timeout = max(timeout, total_takes * _scorer_asr_timeout_per_take() + 900)
    py = QWEN_SCORER_PYTHON
    if not (os.path.exists(py) and os.access(py, os.X_OK)):
        log("   Warning: take scorer interpreter not found (%s) -- skipping take selection" % py)
        return None
    if not os.path.exists(SCRIPT_PATH):
        log("   Warning: take scorer script missing (%s) -- skipping take selection" % SCRIPT_PATH)
        return None

    payload = {"language": whisper_code(language), "speakers": speaker_ref_paths, "lines": lines_payload}
    in_path = os.path.join(work_dir, "qwen_scorer_input.json")
    out_path = os.path.join(work_dir, "qwen_scorer_output.json")
    progress_path = os.path.join(work_dir, "qwen_scorer_asr_progress.json")
    # Never carry the visible progress from a previous attempt into this run.
    # The durable checkpoint is distinct and intentionally survives retries.
    with contextlib.suppress(FileNotFoundError):
        os.unlink(progress_path)
    with open(in_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    try:
        r = subprocess.run(
            [py, SCRIPT_PATH, "--input", in_path, "--output", out_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except Exception as e:
        log("   Warning: take scorer failed to run (%s) -- skipping take selection" % str(e)[:120])
        return None
    finally:
        # A completed/failed scorer no longer owns the live progress indicator.
        # Its source-bound ASR checkpoint remains available for Resume.
        with contextlib.suppress(FileNotFoundError):
            os.unlink(progress_path)

    if r.returncode != 0 or not os.path.exists(out_path):
        log("   Warning: take scorer exited with an error (%s) -- skipping take selection"
            % (r.stderr.strip()[-200:] or "no output produced"))
        return None
    try:
        with open(out_path, encoding="utf-8") as f:
            result = json.load(f)
    except Exception as e:
        log("   Warning: take scorer produced invalid output (%s) -- skipping take selection" % str(e)[:120])
        return None
    if not result.get("ok"):
        log("   Warning: take scorer reported an error (%s) -- skipping take selection"
            % str(result.get("error"))[:200])
        return None

    lines = result.get("lines") or {}
    return {int(k): v for k, v in lines.items()}
