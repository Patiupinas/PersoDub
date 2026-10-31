"""Reproducible, oracle-gated benchmarks for each PersoDub processing stage.

CLI: python -m benchmarks.persodub.runner --manifest CASES.json --out REPORT.json

No model inference, network downloads, new weights or video modification.
A missing independent oracle cannot be interpreted as a passing score.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
from collections import Counter
from pathlib import Path

from benchmarks.persodub.metrics import (
    asr_metrics,
    event_metrics,
    mix_metrics,
    stem_metrics,
    timing_metrics,
)

SUPPORTED = {
    "separation", "events", "asr", "tts_readback", "timing", "mix",
    "export", "translation", "job_audit", "human_review",
}
INDEPENDENT_ORACLES = {"human_gold", "dataset_ground_truth", "synthetic_invariant"}
PROXY_ORACLE = "source_derived_proxy"
SCHEMA = 1


class MissingAsset(Exception):
    pass


def file_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(2 * 1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _asset(root: Path, case: dict, key: str) -> Path:
    raw = case.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Case %s requires local path '%s'" % (case.get("id"), key))
    path = Path(raw)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_file():
        raise MissingAsset("%s not found" % key)
    return path


def _paired_files(root, case):
    """Reject an oracle that is literally the model's own output file."""
    reference = _asset(root, case, "reference")
    candidate = _asset(root, case, "candidate")
    if reference == candidate:
        raise ValueError("Oracle and candidate cannot be the same file")
    return reference, candidate


def _input_fingerprints(root, case):
    """Preserve evidence identity, not local full paths or transcript contents."""
    inputs = {}
    for field in ("reference", "candidate", "source", "events"):
        raw = case.get(field)
        if not isinstance(raw, str):
            continue
        path = Path(raw)
        path = (path if path.is_absolute() else root / path).resolve()
        if path.is_file():
            inputs[field] = {"sha256": file_sha256(path), "bytes": path.stat().st_size}
    return inputs


def _json(root, case, key):
    return json.loads(_asset(root, case, key).read_text(encoding="utf-8"))


def _text(root, case, key):
    return _asset(root, case, key).read_text(encoding="utf-8-sig")


def _events(data):
    if isinstance(data, dict):
        data = data.get("events")
    if not isinstance(data, list):
        raise ValueError("Event file needs an 'events' list or a list of intervals")
    return data


def _utterances(data):
    if isinstance(data, dict):
        data = data.get("utterances")
    if not isinstance(data, list):
        raise ValueError("Timing file needs an 'utterances' list or list of intervals")
    return data


def _metadata(media: Path):
    response = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of",
         "json", str(media)],
        text=True, capture_output=True, timeout=60, check=True,
    )
    data = json.loads(response.stdout)
    if not isinstance(data.get("streams"), list):
        raise ValueError("ffprobe returned no stream inventory")
    duration = float(data.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Unusable video duration")
    return data, duration


def _render_export(root: Path, case: dict):
    source = _asset(root, case, "source")
    output = _asset(root, case, "candidate")
    raw_source, src_dur = _metadata(source)
    raw_out, out_dur = _metadata(output)
    source_audio = sum(s.get("codec_type") == "audio" for s in raw_source["streams"])
    output_audio = sum(s.get("codec_type") == "audio" for s in raw_out["streams"])
    output_video = sum(s.get("codec_type") == "video" for s in raw_out["streams"])
    requested = case.get("expected_mode")
    if requested not in ("replace", "overdub"):
        raise ValueError("expected_mode=replace|overdub required")
    drift = abs(src_dur - out_dur)
    # A straight copy of the original is not evidence of successful dubbing,
    # even when its streams and exact duration look perfect.
    output_changed = source != output and file_sha256(source) != file_sha256(output)
    max_drift = case.get("max_duration_drift_s", 0.15)
    if not isinstance(max_drift, (float, int)) or max_drift < 0:
        raise ValueError("Invalid duration tolerance")
    count_ok = output_audio >= (2 if requested == "overdub" else 1)
    return {
        "source_duration_s": round(src_dur, 6),
        "result_duration_s": round(out_dur, 6),
        "duration_drift_s": round(drift, 6),
        "source_audio_streams": source_audio,
        "output_audio_streams": output_audio,
        "output_video_streams": output_video,
        "required_audio_streams": 2 if requested == "overdub" else 1,
        "streams_ok": count_ok and output_video > 0,
        "output_changed_from_source": output_changed,
        "duration_ok": drift <= max_drift,
    }


def _stage_metrics(root: Path, case: dict) -> dict:
    stage = case["stage"]
    if stage in ("asr", "tts_readback", "events", "timing", "separation", "translation", "mix"):
        _paired_files(root, case)
    if stage in ("asr", "tts_readback"):
        return asr_metrics(_text(root, case, "reference"), _text(root, case, "candidate"))
    if stage == "events":
        return event_metrics(
            _events(_json(root, case, "reference")),
            _events(_json(root, case, "candidate")),
            case["duration_s"],
        )
    if stage == "timing":
        return timing_metrics(
            _utterances(_json(root, case, "reference")),
            _utterances(_json(root, case, "candidate")),
        )
    if stage == "separation":
        return stem_metrics(
            str(_asset(root, case, "reference")),
            str(_asset(root, case, "candidate")),
        )
    if stage == "mix":
        return mix_metrics(
            str(_asset(root, case, "reference")),
            str(_asset(root, case, "candidate")),
            _events(_json(root, case, "events")),
        )
    if stage == "export":
        return _render_export(root, case)
    if stage == "translation":
        # There can be many valid paraphrases. Lexical edit distance is not
        # a semantic translation quality metric. Do not issue a fake PASS.
        return {
            "reference_characters": len(_text(root, case, "reference").strip()),
            "candidate_characters": len(_text(root, case, "candidate").strip()),
            "semantic_quality": "not_measured",
        }
    if stage == "job_audit":
        from app.dub_quality_audit import audit_completed

        location = case.get("job_dir")
        if not isinstance(location, str) or not location:
            raise ValueError("job_audit requires job_dir")
        path = Path(location)
        path = (path if path.is_absolute() else root / path).resolve()
        if not path.is_dir():
            raise MissingAsset("job_dir not found")
        return audit_completed(str(path), expected_mode=case.get("expected_mode"))
    if stage == "human_review":
        # Scoring human accent / voice similarity from the same model's
        # speaker embeddings would bias validation. Only real ratings count.
        data = _json(root, case, "reference")
        if not isinstance(data, dict) or not isinstance(data.get("ratings"), list):
            raise ValueError("Human review needs independent 'ratings'")
        ratings = data["ratings"]
        if len({r.get("rater_id") for r in ratings}) < 3:
            raise ValueError("At least three independent reviewers required")
        if not all(r.get("native_ru") is True for r in ratings):
            raise ValueError("Native-Russian speaker verification required for accent MOS")
        fields = ("russian_accent", "voice_likeness", "pause_naturalness",
                  "original_mix_audibility")
        values = {field: [] for field in fields}
        for row in ratings:
            for field in fields:
                score = row.get(field)
                if type(score) not in (int, float) or not 1 <= score <= 5:
                    raise ValueError("All human dimensions require 1-5 MOS ratings")
                values[field].append(score)
        return {field + "_mos": round(sum(scores) / len(scores), 3)
                for field, scores in values.items()} | {"raters": len(ratings)}
    raise ValueError("Unknown benchmark stage: " + stage)


def _score(stage, metrics, thresholds, oracle_kind):
    if stage == "export":
        return ("PASS" if metrics["streams_ok"] and metrics["duration_ok"]
                and metrics["output_changed_from_source"] else "FAIL")
    if stage == "job_audit":
        return "FAIL" if metrics.get("issues") else "OBSERVED"
    if stage == "translation":
        return "OBSERVED"
    if stage == "mix" and oracle_kind != "synthetic_invariant":
        return "OBSERVED"
    if stage == "human_review" and oracle_kind != "human_gold":
        return "OBSERVED"
    if oracle_kind not in INDEPENDENT_ORACLES:
        return "OBSERVED"
    if not thresholds:
        return "OBSERVED"
    for metric, limit in thresholds.items():
        if metric not in metrics:
            raise ValueError("Threshold names missing measured metric: " + metric)
        value = metrics[metric]
        if value is None and stage == "separation" and metrics.get("perfect_reconstruction"):
            value = math.inf
        if type(value) not in (int, float) or math.isnan(value):
            raise ValueError("Threshold requires a finite numerical metric")
        if not isinstance(limit, dict) or set(limit) not in ({"max"}, {"min"}):
            raise ValueError("Use one bound per metric: {'min':number} or {'max':number}")
        bound, edge = next(iter(limit.items()))
        if type(edge) not in (int, float) or not math.isfinite(edge):
            raise ValueError("Threshold bound must be finite")
        if bound == "max" and value > edge + 1e-6:
            return "FAIL"
        if bound == "min" and value + 1e-6 < edge:
            return "FAIL"
    return "PASS"


def _validate(case, ids):
    if not isinstance(case, dict) or not isinstance(case.get("id"), str):
        raise ValueError("Every benchmark case needs a stable ID")
    if case["id"] in ids or not case["id"]:
        raise ValueError("Duplicate or empty benchmark case ID")
    ids.add(case["id"])
    if case.get("stage") not in SUPPORTED:
        raise ValueError("Unknown stage: %s" % case.get("stage"))
    kind = case.get("oracle_kind")
    if kind not in INDEPENDENT_ORACLES | {PROXY_ORACLE, "none"}:
        raise ValueError("Every case needs declared oracle_kind")
    if "thresholds" in case and not isinstance(case["thresholds"], dict):
        raise ValueError("Thresholds must be an object")


def run_chain(manifest_path: Path, root: Path | None = None) -> dict:
    manifest_path = Path(manifest_path).resolve()
    suite = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (not isinstance(suite, dict) or suite.get("schema_version") != SCHEMA
            or not isinstance(suite.get("cases"), list)
            or not isinstance(suite.get("suite_id"), str)):
        raise ValueError("Invalid benchmark suite schema")
    root = Path(root or manifest_path.parent).resolve()
    if not root.is_dir():
        raise ValueError("Benchmark assets root does not exist")
    ids = set()
    results = []
    for case in suite["cases"]:
        _validate(case, ids)
        result = {"id": case["id"], "stage": case["stage"],
                  "oracle_kind": case["oracle_kind"],
                  "split": case.get("split", "unspecified")}
        try:
            metrics = _stage_metrics(root, case)
            result["metrics"] = metrics
            result["input_fingerprints"] = _input_fingerprints(root, case)
            result["status"] = _score(
                case["stage"], metrics, case.get("thresholds", {}),
                case["oracle_kind"],
            )
        except MissingAsset as exc:
            result["status"] = "NOT_RUN" if case.get("optional") else "FAIL"
            result["reason"] = str(exc)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            result["status"] = "ERROR"
            result["reason"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
        results.append(result)
    tally = Counter(item["status"] for item in results)
    if tally["FAIL"] or tally["ERROR"]:
        outcome = "FAIL"
    elif tally["NOT_RUN"] or tally["OBSERVED"] or not results:
        outcome = "INCOMPLETE"
    else:
        outcome = "PASS_MEASURED_CASES_ONLY"
    return {
        "schema_version": SCHEMA,
        "suite_id": suite["suite_id"],
        "manifest_sha256": file_sha256(manifest_path),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "overall": outcome,
        "production_quality_verified": False,
        "summary": dict(sorted(tally.items())),
        "cases": results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--strict", action="store_true",
                        help="Exit nonzero if any case fails or is incomplete")
    args = parser.parse_args(argv)
    report = run_chain(args.manifest, args.root)
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.out:
        # Never overwrite a prior experiment result; preserve run lineage.
        with args.out.open("x", encoding="utf-8") as file:
            file.write(encoded)
    print(encoded, end="")
    if args.strict and report["overall"] != "PASS_MEASURED_CASES_ONLY":
        return 2
    return 1 if report["overall"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
