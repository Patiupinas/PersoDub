"""Validate a sample-accurate decision manifest for selective vocal dubbing.

This is a pure-data, opt-in contract. It does not classify audio, translate,
call a TTS engine, or modify PersoDub's existing dubbing pipeline.

Every decoded PCM frame must have exactly one leaf action. Unknown intervals
must be labelled REVIEW, not implicitly dropped or translated. Boundaries are
integer frame indices [start_sample, end_sample); no float-second rounding.
"""

import math
import re
from dataclasses import dataclass
from typing import Optional, Tuple


SCHEMA_VERSION = 1
LEAF_ACTIONS = frozenset(("TRANSLATE", "PRESERVE", "REVIEW"))
ACTIONS = LEAF_ACTIONS | {"MIXED"}
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SEGMENT_FIELDS = frozenset((
    "segment_id", "start_sample", "end_sample", "action", "children",
    "speaker_id", "source_language", "source_text", "reason", "confidence",
    "human_override",
))


class DecisionValidationError(ValueError):
    """A manifest could replace or discard audio and must not be used."""


@dataclass(frozen=True)
class HumanOverride:
    previous_action: str
    reason: str


@dataclass(frozen=True)
class DecisionSpan:
    segment_id: str
    start_sample: int
    end_sample: int
    action: str
    speaker_id: Optional[str]
    source_language: Optional[str]
    source_text: Optional[str]
    reason: Optional[str]
    confidence: Optional[float]
    human_override: Optional[HumanOverride]


@dataclass(frozen=True)
class DecisionManifest:
    source_sha256: str
    pcm_sha256: str
    sample_rate: int
    total_samples: int
    spans: Tuple[DecisionSpan, ...]
    model_revisions: Tuple[Tuple[str, str], ...]


def _object(value, where, required, allowed):
    if not isinstance(value, dict):
        raise DecisionValidationError(f"{where}: expected object")
    if any(not isinstance(key, str) for key in value):
        raise DecisionValidationError(f"{where}: object keys must be strings")
    missing = required - value.keys()
    unknown = value.keys() - allowed
    if missing:
        raise DecisionValidationError(f"{where}: missing {sorted(missing)}")
    if unknown:
        raise DecisionValidationError(f"{where}: unknown keys {sorted(unknown)}")
    return value


def _integer(value, where, minimum):
    # bool is a subclass of int in Python and must be rejected explicitly.
    if type(value) is not int or value < minimum:
        raise DecisionValidationError(f"{where}: expected integer >= {minimum}")
    return value


def _string(value, where, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise DecisionValidationError(f"{where}: expected non-empty string")
    return value


def _sha(value, where):
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise DecisionValidationError(f"{where}: expected lowercase 64-digit SHA-256")
    return value


def _confidence(value, where):
    if value is None:
        return None
    if type(value) not in (float, int) or not 0 <= value <= 1:
        raise DecisionValidationError(f"{where}: expected finite confidence in [0, 1]")
    try:
        result = float(value)
    except OverflowError as exc:
        raise DecisionValidationError(f"{where}: expected finite confidence in [0, 1]") from exc
    if not math.isfinite(result):
        raise DecisionValidationError(f"{where}: expected finite confidence in [0, 1]")
    return result


def _override(value, action, where):
    if value is None:
        return None
    obj = _object(value, where, {"previous_action", "reason"}, {"previous_action", "reason"})
    previous = obj["previous_action"]
    if not isinstance(previous, str) or previous not in LEAF_ACTIONS or previous == action:
        raise DecisionValidationError(f"{where}: previous_action must be a different leaf action")
    return HumanOverride(previous, _string(obj["reason"], f"{where}.reason", required=True))


def _partition(items, start, end, where):
    if not isinstance(items, list) or not items:
        raise DecisionValidationError(f"{where}: expected non-empty segment list")
    next_start = start
    for i, item in enumerate(items):
        loc = f"{where}[{i}]"
        _object(item, loc, {"segment_id", "start_sample", "end_sample", "action"}, _SEGMENT_FIELDS)
        left = _integer(item["start_sample"], f"{loc}.start_sample", 0)
        right = _integer(item["end_sample"], f"{loc}.end_sample", 0)
        if right <= left or right > end:
            raise DecisionValidationError(f"{loc}: invalid or out-of-range sample interval")
        if left != next_start:
            kind = "gap" if left > next_start else "overlap or unsorted segment"
            raise DecisionValidationError(f"{loc}: {kind} at sample {next_start}")
        next_start = right
    if next_start != end:
        raise DecisionValidationError(f"{where}: uncovered tail [{next_start}, {end})")


def _segments(items, start, end, where, used_ids):
    _partition(items, start, end, where)
    out = []
    for i, item in enumerate(items):
        loc = f"{where}[{i}]"
        segment_id = _string(item["segment_id"], f"{loc}.segment_id", required=True)
        if segment_id in used_ids:
            raise DecisionValidationError(f"{loc}: duplicate segment_id {segment_id!r}")
        used_ids.add(segment_id)
        action = item["action"]
        if not isinstance(action, str) or action not in ACTIONS:
            raise DecisionValidationError(f"{loc}.action: unknown decision")
        speaker = _string(item.get("speaker_id"), f"{loc}.speaker_id")
        language = _string(item.get("source_language"), f"{loc}.source_language")
        if language is not None and language not in ("de", "en", "und"):
            raise DecisionValidationError(f"{loc}.source_language: unsupported language")
        source_text = _string(item.get("source_text"), f"{loc}.source_text")
        reason = _string(item.get("reason"), f"{loc}.reason")
        confidence = _confidence(item.get("confidence"), f"{loc}.confidence")
        override = _override(item.get("human_override"), action, f"{loc}.human_override")
        if action == "MIXED":
            if override is not None:
                raise DecisionValidationError(f"{loc}: override MIXED through leaf actions instead")
            children = item.get("children")
            if not isinstance(children, list) or len(children) < 2:
                raise DecisionValidationError(f"{loc}.children: MIXED needs >= 2 children")
            if any(child.get("action") == "MIXED" for child in children if isinstance(child, dict)):
                raise DecisionValidationError(f"{loc}: nested MIXED is not supported in v1")
            out.extend(_segments(children, item["start_sample"], item["end_sample"],
                                 f"{loc}.children", used_ids))
            continue
        if "children" in item:
            raise DecisionValidationError(f"{loc}: leaf actions must not have children")
        if action == "TRANSLATE" and (language not in ("de", "en") or source_text is None):
            raise DecisionValidationError(f"{loc}: TRANSLATE requires DE/EN source_language and source_text")
        if action == "REVIEW" and reason is None:
            raise DecisionValidationError(f"{loc}: REVIEW requires a reason")
        out.append(DecisionSpan(segment_id, item["start_sample"], item["end_sample"],
                                action, speaker, language, source_text, reason,
                                confidence, override))
    return out


def parse_decision_manifest(raw):
    """Return validated immutable leaf actions, or raise DecisionValidationError.

    The sample timeline is the selected **decoded PCM** stream, starting at
    sample zero. The input hash binds that PCM; mapping its zero to the
    source video's absolute PTS is an ingest responsibility, not a guess here.
    Validation alone does not prove that a supplied hash matches media bytes.
    """
    required = {"schema_version", "source_sha256", "pcm_sha256",
                "sample_rate", "total_samples", "segments"}
    obj = _object(raw, "manifest", required, required | {"model_revisions"})
    if type(obj["schema_version"]) is not int or obj["schema_version"] != SCHEMA_VERSION:
        raise DecisionValidationError(f"manifest: unsupported schema_version (expected {SCHEMA_VERSION})")
    source_sha = _sha(obj["source_sha256"], "manifest.source_sha256")
    pcm_sha = _sha(obj["pcm_sha256"], "manifest.pcm_sha256")
    rate = _integer(obj["sample_rate"], "manifest.sample_rate", 1)
    total = _integer(obj["total_samples"], "manifest.total_samples", 1)
    revisions = obj.get("model_revisions", {})
    if not isinstance(revisions, dict):
        raise DecisionValidationError("manifest.model_revisions: expected object")
    for key, revision in revisions.items():
        _string(key, "manifest.model_revisions key", required=True)
        _string(revision, f"manifest.model_revisions[{key!r}]", required=True)
    spans = tuple(_segments(obj["segments"], 0, total, "manifest.segments", set()))
    return DecisionManifest(source_sha, pcm_sha, rate, total, spans,
                            tuple(sorted(revisions.items())))
