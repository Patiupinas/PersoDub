"""Conservative, model-agnostic vote policy for selective vocal dubbing.

It consumes PRE-ALIGNED, disjoint PCM windows from acoustic adapters + ASR.
No model or real audio is loaded here. Disagreement never triggers a dub.
"""

import json
from pathlib import Path

from app.vocal_decisions import parse_decision_manifest

ALLOWED_LABELS = frozenset({"speech", "vocal", "music", "breath", "silence", "uncertain"})
PROTECTED_LABELS = frozenset({"vocal", "music", "breath", "silence"})
SPEECH_VOTES_REQUIRED = 2  # explicit multi-model corroboration, not a confidence threshold


class VotePolicyError(ValueError):
    """Observation cannot safely be converted into dubbing decisions."""


def _object(raw, name, required, allowed):
    if not isinstance(raw, dict):
        raise VotePolicyError(f"{name}: expected JSON object")
    if any(not isinstance(k, str) for k in raw):
        raise VotePolicyError(f"{name}: keys must be strings")
    if missing := (required - raw.keys()):
        raise VotePolicyError(f"{name}: missing keys {sorted(missing)}")
    if unknown := (raw.keys() - allowed):
        raise VotePolicyError(f"{name}: unknown keys {sorted(unknown)}")
    return raw


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise VotePolicyError(f"{name}: expected non-empty string")
    return value


def _asr(raw, where):
    if raw is None:
        return None
    obj = _object(raw, where, {"text", "language"}, {"text", "language", "speaker_id"})
    text = _text(obj["text"], f"{where}.text")
    language = _text(obj["language"], f"{where}.language")
    if language not in ("de", "en", "und"):
        raise VotePolicyError(f"{where}: unsupported language {language!r}")
    speaker = obj.get("speaker_id")
    if speaker is not None:
        speaker = _text(speaker, f"{where}.speaker_id")
    return {"source_text": text, "source_language": language, "speaker_id": speaker}


def _votes(raw, revisions, where):
    if not isinstance(raw, list):
        raise VotePolicyError(f"{where}: expected list of acoustic votes")
    labels = []
    sources = set()
    for i, value in enumerate(raw):
        loc = f"{where}[{i}]"
        obj = _object(value, loc, {"model_id", "label"}, {"model_id", "label"})
        model_id = _text(obj["model_id"], f"{loc}.model_id")
        label = _text(obj["label"], f"{loc}.label")
        if label not in ALLOWED_LABELS:
            raise VotePolicyError(f"{loc}: unsupported acoustic label {label!r}")
        if model_id not in revisions:
            raise VotePolicyError(f"{loc}: model_id not declared in model_revisions")
        if model_id in sources:
            raise VotePolicyError(f"{loc}: duplicate model_id {model_id!r}")
        labels.append(label)
        sources.add(model_id)
    return labels


def select_vocal_decisions(raw):
    """Build schema-v1 decisions from window-aligned ASR and acoustic votes.

    TRANSLATE requires DE/EN ASR text and >=2 different acoustic models that
    *all* vote speech. A definite non-speech window without ASR is PRESERVE.
    Everything else is REVIEW; no silence/cue gaps are silently translated.

    The independent adapters must establish sample accuracy and provenance.
    This code does not check whether detectors are statistically independent.
    """
    obj = _object(raw, "observations",
                  {"schema_version", "source_sha256", "pcm_sha256", "sample_rate",
                   "total_samples", "model_revisions", "windows"},
                  {"schema_version", "source_sha256", "pcm_sha256", "sample_rate",
                   "total_samples", "model_revisions", "windows"})
    revisions = obj["model_revisions"]
    if not isinstance(revisions, dict):
        raise VotePolicyError("model_revisions: expected object")
    if not isinstance(obj["windows"], list):
        raise VotePolicyError("windows: expected list")
    decisions = []
    for i, raw_window in enumerate(obj["windows"]):
        where = f"windows[{i}]"
        win = _object(raw_window, where,
                      {"start_sample", "end_sample", "asr", "votes"},
                      {"start_sample", "end_sample", "asr", "votes"})
        asr = _asr(win["asr"], f"{where}.asr")
        votes = _votes(win["votes"], revisions, f"{where}.votes")
        if asr is not None and asr["source_language"] in ("de", "en") and (
                len(votes) >= SPEECH_VOTES_REQUIRED and set(votes) == {"speech"}):
            action, reason = "TRANSLATE", "DE/EN ASR and unanimous independent acoustic speech votes"
        elif asr is None and votes and set(votes) <= PROTECTED_LABELS:
            action, reason = "PRESERVE", "confirmed original nonspeech/vocal sound"
        else:
            action, reason = "REVIEW", "missing/conflicting evidence or speech/vocal overlap"
        segment = {"segment_id": f"window-{i:06d}",
                   "start_sample": win["start_sample"], "end_sample": win["end_sample"],
                   "action": action, "reason": reason}
        if asr is not None:
            segment.update(asr)
        decisions.append(segment)
    result = {name: obj[name] for name in ("schema_version", "source_sha256",
                                           "pcm_sha256", "sample_rate", "total_samples",
                                           "model_revisions")}
    result["segments"] = decisions
    # Shared v1 validator is the authority for missing coverage, overlaps,
    # zero-length windows, hashes, and legal actions.
    parse_decision_manifest(result)
    return result


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="Conservative offline vocal vote gate")
    parser.add_argument("--observations", type=Path, required=True, help="Pre-aligned observation windows JSON")
    args = parser.parse_args(argv)
    try:
        with args.observations.open(encoding="utf-8") as reader:
            result = select_vocal_decisions(json.load(reader))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Vote policy failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
