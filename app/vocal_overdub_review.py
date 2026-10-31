"""Map source-bound model observations to reviewable Overdub intervals.

Raw event inference is not an A4 decision. The suggested action is separate
from the always-unapproved action field. All boundaries use original 48k PCM.
"""
import hashlib
import json
import math
from pathlib import Path

from app.audio.overdub import OverdubError, _parse_plan
from app.audio.pcm import SR

KINDS = frozenset(("speech", "singing", "laughing", "crying_baby", "coughing", "sneezing", "breathing"))
SUGGEST = {k: ("TRANSLATE" if k == "speech" else "PRESERVE") for k in KINDS}
BIN_FRAMES = SR * 2
WINDOW_FRAMES = SR * 4


def _score_top(scores):
    if type(scores) is not dict or set(scores) != KINDS or any(
        type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
        for v in scores.values()
    ):
        raise OverdubError("AST scores must match the seven original AudioSet groups")
    top = max(sorted(KINDS), key=lambda k: scores[k])
    return top, round(scores[top], 5)


def _verify_observations(record, frames, sha):
    if (
        type(record) is not dict
        or set(record) != {"schema_version", "source_wav_sha256", "sample_rate",
                          "total_frames", "model", "model_weights_sha256", "windows"}
        or record["schema_version"] != 1 or record["sample_rate"] != SR
        or record["total_frames"] != frames or record["source_wav_sha256"] != sha
        or record["model"] != "MIT/ast-finetuned-audioset-12-12-0.447"
        or not isinstance(record["model_weights_sha256"], str)
        or record["model_weights_sha256"]
        != "d87987744d05c134a9f4294568888832b94ad3a9a2d62a3e3a8de5d793eb1918"
        or type(record["windows"]) is not list or not record["windows"]
    ):
        raise OverdubError("AST observations do not match this original audio")
    previous = -1
    for row in record["windows"]:
        if type(row) is not dict or set(row) != {"start_frame", "end_frame", "scores"}:
            raise OverdubError("Unexpected AST window fields")
        start, end = row["start_frame"], row["end_frame"]
        if (
            type(start) is not int or type(end) is not int or
            start <= previous or not 0 <= start < end <= frames or
            end - start > WINDOW_FRAMES
        ):
            raise OverdubError("AST timestamps are not ordered source PCM frames")
        _score_top(row["scores"])
        previous = start
    return record["windows"]


def _compress(rows):
    """Merge only identical adjacent suggestions, never reviewed actions."""
    result = []
    for row in rows:
        if result and result[-1]["end_frame"] == row["start_frame"] and all(
            result[-1][k] == row[k] for k in ("hint", "suggested_action", "score")
        ):
            result[-1]["end_frame"] = row["end_frame"]
        else:
            result.append(dict(row))
    return result


def model_suggestions(frames, sha, observations):
    """Use closest 4-second AST observation for each 2-second review bin."""
    windows = _verify_observations(observations, frames, sha)
    rows = []
    for start in range(0, frames, BIN_FRAMES):
        end = min(start + BIN_FRAMES, frames)
        center = (start + end) / 2
        sample = min(windows, key=lambda r: abs(
            (r["start_frame"] + r["end_frame"]) / 2 - center
        ))
        kind, score = _score_top(sample["scores"])
        available = sample["start_frame"] <= center < sample["end_frame"]
        rows.append({
            "start_frame": start, "end_frame": end, "action": "REVIEW",
            "suggested_action": SUGGEST[kind] if available else "REVIEW",
            "hint": kind if available else "unscored",
            "score": score if available else None,
        })
    return _compress(rows)


def transcript_suggestions(frames, spans):
    """Approximate fallback from transcript cue ranges, not singing labels."""
    edges = {0, frames}
    cues = []
    for a, b in spans:
        if type(a) not in (int, float) or type(b) not in (int, float):
            continue
        if not math.isfinite(a) or not math.isfinite(b):
            continue
        start, end = max(0, round(a * SR)), min(frames, round(b * SR))
        if start >= end:
            continue
        cues.append((start, end))
        edges.update((start, end))
    rows = []
    endpoints = sorted(edges)
    for start, end in zip(endpoints, endpoints[1:]):
        matched = any(a < end and b > start for a, b in cues)
        rows.append({
            "start_frame": start, "end_frame": end, "action": "REVIEW",
            "suggested_action": "TRANSLATE" if matched else "REVIEW",
            "hint": "speech-cue" if matched else "unknown", "score": None,
        })
    return _compress(rows)


def approved_plan(frames, sha, rows):
    if type(rows) is not list or not rows:
        raise OverdubError("Complete reviewed intervals are required")
    if any(type(row) is not dict or set(row) != {"start_frame", "end_frame", "action"}
           for row in rows):
        raise OverdubError("Unexpected fields in the reviewed event plan")
    plan = {
        "schema_version": 1, "sample_rate": SR,
        "total_frames": frames, "source_wav_sha256": sha,
        "events": rows,
    }
    _parse_plan(plan, frames, sha)
    return plan


def plan_sha(plan):
    return hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def record_plan(dest, plan):
    """Create a new immutable plan; never overwrite another approval."""
    path = Path(dest)
    with path.open("x", encoding="utf-8") as out:
        json.dump(plan, out, indent=2)
        out.write("\n")
    return path
