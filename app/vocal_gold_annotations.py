"""Compile independently annotated vocal events to the canonical decision schema.

Annotations remain the authority for human labels. This file only validates
and projects them; it never runs ASR, classifiers, or invents transcription.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from app.vocal_decisions import parse_decision_manifest

EVENT_ACTIONS = {
    "explanation": "TRANSLATE",
    "vocal_demo": "PRESERVE",
    "non_target": "PRESERVE",
    "speech_vocal_overlap": "REVIEW",
    "uncertain": "REVIEW",
}
_ROOT_FIELDS = {
    "schema_version", "source_sha256", "pcm_sha256", "sample_rate",
    "total_samples", "source_revision", "annotation_revision", "events",
}
_EVENT_REQUIRED = {"event_id", "start_sample", "end_sample", "event_type", "reason"}
_EVENT_FIELDS = _EVENT_REQUIRED | {"speaker_id", "source_language", "source_text"}


class GoldAnnotationError(ValueError):
    """The provided human annotation is not valid for gold scoring."""


def _object(value, fields, required, where):
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise GoldAnnotationError(f"{where}: expected an object with string keys")
    missing, unknown = required - value.keys(), value.keys() - fields
    if missing or unknown:
        raise GoldAnnotationError(f"{where}: missing {sorted(missing)}, unknown {sorted(unknown)}")
    return value


def _text(value, where, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise GoldAnnotationError(f"{where}: expected nonempty text")
    return value


def _integer(value, where):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GoldAnnotationError(f"{where}: expected non-negative integer")
    return value


def compile_gold_annotations(raw):
    """Return (validated decision manifest, event-type summary).

    A human-labelled explanation needs a *verified literal transcript* and
    an EN/DE language, because the current decision schema requires both for
    TRANSLATE. Spanish annotations are kept for future schema qualification,
    but are not silently downgraded or converted with the EN/DE-only policy.
    Human independence and correctness are not proved by structural checks.
    """
    source = _object(raw, _ROOT_FIELDS, _ROOT_FIELDS, "annotations")
    if type(source["schema_version"]) is not int or source["schema_version"] != 1:
        raise GoldAnnotationError("annotations: unsupported schema_version")
    _text(source["source_revision"], "source_revision", required=True)
    _text(source["annotation_revision"], "annotation_revision", required=True)
    total = _integer(source["total_samples"], "total_samples")
    if total == 0:
        raise GoldAnnotationError("total_samples must be positive")
    if _integer(source["sample_rate"], "sample_rate") == 0:
        raise GoldAnnotationError("sample_rate must be positive")
    if not isinstance(source["events"], list) or not source["events"]:
        raise GoldAnnotationError("events: expected nonempty list")

    segment_ids = set()
    segments = []
    event_counts = Counter()
    event_samples = Counter()
    for i, raw_event in enumerate(source["events"]):
        loc = f"events[{i}]"
        event = _object(raw_event, _EVENT_FIELDS, _EVENT_REQUIRED, loc)
        event_id = _text(event["event_id"], f"{loc}.event_id", required=True)
        if event_id in segment_ids:
            raise GoldAnnotationError(f"{loc}: duplicate event_id {event_id!r}")
        segment_ids.add(event_id)
        start = _integer(event["start_sample"], f"{loc}.start_sample")
        end = _integer(event["end_sample"], f"{loc}.end_sample")
        if end <= start or end > total:
            raise GoldAnnotationError(f"{loc}: invalid or out-of-range sample span")
        kind = event["event_type"]
        if not isinstance(kind, str) or kind not in EVENT_ACTIONS:
            raise GoldAnnotationError(f"{loc}: unknown event_type {kind!r}")
        reason = _text(event["reason"], f"{loc}.reason", required=True)
        speaker = _text(event.get("speaker_id"), f"{loc}.speaker_id")
        lang = _text(event.get("source_language"), f"{loc}.source_language")
        transcript = _text(event.get("source_text"), f"{loc}.source_text")
        if lang is not None and lang not in ("en", "de", "und"):
            raise GoldAnnotationError(f"{loc}: source_language {lang!r} not supported by decision schema v1")
        if kind == "explanation" and (lang not in ("en", "de") or transcript is None):
            raise GoldAnnotationError(f"{loc}: explanation requires verified EN/DE source_text")
        if kind in ("vocal_demo", "non_target") and transcript is not None:
            raise GoldAnnotationError(f"{loc}: do not fabricate captions for protected events")

        segment = {
            "segment_id": event_id,
            "start_sample": start,
            "end_sample": end,
            "action": EVENT_ACTIONS[kind],
            "reason": reason,
        }
        if speaker is not None:
            segment["speaker_id"] = speaker
        if lang is not None:
            segment["source_language"] = lang
        if transcript is not None:
            segment["source_text"] = transcript
        segments.append(segment)
        event_counts[kind] += 1
        event_samples[kind] += end - start

    manifest = {
        "schema_version": 1,
        "source_sha256": source["source_sha256"],
        "pcm_sha256": source["pcm_sha256"],
        "sample_rate": source["sample_rate"],
        "total_samples": total,
        "segments": segments,
    }
    # Reuse the canonical full-coverage, hash, action and field validator.
    parse_decision_manifest(manifest)
    summary = {
        "schema_version": 1,
        "annotation_revision": source["annotation_revision"],
        "source_sha256": source["source_sha256"],
        "pcm_sha256": source["pcm_sha256"],
        "event_counts": {key: event_counts[key] for key in EVENT_ACTIONS},
        "event_samples": {key: event_samples[key] for key in EVENT_ACTIONS},
        "vocal_demo_events": event_counts["vocal_demo"],
        "vocal_demo_samples": event_samples["vocal_demo"],
    }
    return manifest, summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Convert reviewed vocal annotations into decision gold")
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path, required=True)
    args = parser.parse_args(argv)
    outputs = [args.manifest_out.resolve(), args.summary_out.resolve()]
    if len(set(outputs + [args.annotations.resolve()])) != 3:
        parser.error("annotations, manifest and summary paths must be distinct")
    try:
        with args.annotations.open(encoding="utf-8") as source_file:
            manifest, summary = compile_gold_annotations(json.load(source_file))
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f"Invalid human annotation: {exc}\n")

    # Validate everything before writing either derived artifact.
    for destination, payload in ((args.manifest_out, manifest), (args.summary_out, summary)):
        destination.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                               encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
