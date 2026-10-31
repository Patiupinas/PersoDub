"""Audit unreviewed audio-language-model window hints without creating decisions.

This research-only module never changes A1 gold or A4 TRANSLATE/PRESERVE
policy. Overlapping targeted windows are observations, not a PCM partition.
"""

import hashlib
import math
import re

SEMANTIC_LABELS = {
    "lesson": {
        "EXPLANATION": "speech",
        "VOCAL_DEMO": "vocal",
        "MIXED": "mixed",
        "NON_TARGET": "non_target",
        "UNCERTAIN": "uncertain",
    },
    "neutral": {
        "SPEECH_ONLY": "speech",
        "VOCALIZATION_ONLY": "vocal",
        "BOTH": "mixed",
        "NONE": "non_target",
        "UNCERTAIN": "uncertain",
    },
}
SEMANTIC_LABELS["alt_context"] = SEMANTIC_LABELS["lesson"]

_ROOT = {
    "schema_version", "artifact_kind", "source_name",
    "source_wav_sha256", "source_raw_pcm_sha256", "sample_rate",
    "source_offset_samples", "total_samples", "model", "prompts",
    "windows", "repeatability_checks", "status",
}
_WINDOW = {
    "window_id", "tier", "start_sample", "end_sample",
    "previous_candidate", "wav_sha256", "pcm_sha256", "outputs",
}
_OUTPUT = {
    "raw_first_line", "semantic_class", "stdout_sha256",
    "wall_seconds", "format_exact_first_line",
}
_REPEAT = {
    "window_id", "prompt_id", "same_stdout",
    "first_stdout_sha256", "repeat_stdout_sha256",
}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class SemanticReviewError(ValueError):
    """Unreviewed model evidence cannot be linked to a verified source clock."""


def _keys(value, expected, where):
    if not isinstance(value, dict) or set(value) != expected:
        raise SemanticReviewError(f"{where}: unexpected or missing fields")
    return value


def _sha(value, where):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise SemanticReviewError(f"{where}: invalid SHA256")


def _integer(value, where, minimum=0):
    if type(value) is not int or value < minimum:
        raise SemanticReviewError(f"{where}: invalid integer")
    return value


def _text(value, where):
    if not isinstance(value, str) or not value.strip():
        raise SemanticReviewError(f"{where}: empty text")
    return value


def _parsed_class(output, prompt_id):
    where = f"outputs.{prompt_id}"
    _keys(output, _OUTPUT, where)
    first = _text(output["raw_first_line"], f"{where}.raw_first_line")
    if "\n" in first or "\r" in first:
        raise SemanticReviewError(f"{where}: multiline model label")
    tag = first.split(" ", 1)[0]
    label = SEMANTIC_LABELS[prompt_id].get(tag)
    if label is None or output["semantic_class"] != label:
        raise SemanticReviewError(f"{where}: unknown or inconsistent model label")
    if type(output["format_exact_first_line"]) is not bool:
        raise SemanticReviewError(f"{where}: bad strict-format flag")
    if output["format_exact_first_line"] != (first == tag):
        raise SemanticReviewError(f"{where}: strict-format flag mismatch")
    _sha(output["stdout_sha256"], f"{where}.stdout_sha256")
    duration = output["wall_seconds"]
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        raise SemanticReviewError(f"{where}: invalid runtime")
    return label


def audit_semantic_snapshot(raw):
    """Compare prompt responses on the same verified source-PCM windows.

    Agreement measures sensitivity to prompt formulations, NOT acoustic
    accuracy, sample-level coverage, provider independence, or TTS permission.
    All intervals refer to the same decoded source derivative. Targeted
    subwindows intentionally overlap the longer uncertain windows.
    """
    doc = _keys(raw, _ROOT, "snapshot")
    if doc["schema_version"] != 1 or doc["artifact_kind"] != "unreviewed_semantic_window_pilot":
        raise SemanticReviewError("unexpected semantic pilot schema")
    if "unreviewed" not in _text(doc["status"], "status").lower():
        raise SemanticReviewError("cannot promote machine results to gold")
    _text(doc["source_name"], "source_name")
    for name in ("source_wav_sha256", "source_raw_pcm_sha256"):
        _sha(doc[name], name)
    rate = _integer(doc["sample_rate"], "sample_rate", 1)
    offset = _integer(doc["source_offset_samples"], "source_offset_samples")
    length = _integer(doc["total_samples"], "total_samples", 1)
    if length % rate or offset % rate:
        raise SemanticReviewError("invalid source clock")
    model = doc["model"]
    if not isinstance(model, dict):
        raise SemanticReviewError("model provenance missing")
    for name in ("weights_sha256", "runtime_sha256", "runtime_release_tar_sha256"):
        _sha(model.get(name), f"model.{name}")
    if _integer(model.get("weights_bytes"), "model.weights_bytes", 1) < 1024:
        raise SemanticReviewError("model checkpoint too small")
    _text(model.get("name"), "model.name")

    prompts = doc["prompts"]
    if not isinstance(prompts, dict) or set(prompts) != set(SEMANTIC_LABELS):
        raise SemanticReviewError("missing or unexpected prompt variant")
    for variant, prompt in prompts.items():
        _keys(prompt, {"text", "sha256"}, f"prompts.{variant}")
        text = _text(prompt["text"], f"prompts.{variant}.text")
        _sha(prompt["sha256"], f"prompts.{variant}.sha256")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != prompt["sha256"]:
            raise SemanticReviewError("prompt content hash mismatch")

    windows = doc["windows"]
    if not isinstance(windows, list) or not windows:
        raise SemanticReviewError("no model windows")
    lookup = {}
    mismatched = []
    alt_mismatched = []
    alt_pairs = 0
    malformed_first_lines = 0
    for raw_window in windows:
        item = _keys(raw_window, _WINDOW, "window")
        name = _text(item["window_id"], "window_id")
        if not re.fullmatch(r"[A-Za-z0-9_]+", name) or name in lookup:
            raise SemanticReviewError("invalid or duplicate window identifier")
        a = _integer(item["start_sample"], f"{name}.start_sample")
        b = _integer(item["end_sample"], f"{name}.end_sample")
        if not offset <= a < b <= offset + length:
            raise SemanticReviewError(f"{name}: source window outside decoded PCM")
        if item["tier"] not in ("control", "coarse", "targeted_probe"):
            raise SemanticReviewError(f"{name}: unsupported research tier")
        if item["previous_candidate"] not in (
            "speech_candidate", "vocal_demo_candidate", "uncertain"
        ):
            raise SemanticReviewError(f"{name}: invalid prior candidate")
        for field in ("wav_sha256", "pcm_sha256"):
            _sha(item[field], f"{name}.{field}")
        outputs = item["outputs"]
        if not isinstance(outputs, dict) or (
            set(outputs) not in ({"lesson", "neutral"}, set(SEMANTIC_LABELS))
        ):
            raise SemanticReviewError(f"{name}: missing paired model results")
        classes = {variant: _parsed_class(result, variant) for variant, result in outputs.items()}
        malformed_first_lines += sum(
            not result["format_exact_first_line"] for result in outputs.values()
        )
        if classes["lesson"] != classes["neutral"]:
            mismatched.append(name)
        if "alt_context" in classes:
            alt_pairs += 1
            if classes["lesson"] != classes["alt_context"]:
                alt_mismatched.append(name)
        lookup[name] = item

    checks = doc["repeatability_checks"]
    if not isinstance(checks, list):
        raise SemanticReviewError("repeatability checks must be a list")
    checked = set()
    for entry in checks:
        item = _keys(entry, _REPEAT, "repeatability")
        key = (item["window_id"], item["prompt_id"])
        if key in checked or item["window_id"] not in lookup:
            raise SemanticReviewError("invalid or duplicate repeated measurement")
        checked.add(key)
        target = lookup[item["window_id"]]["outputs"].get(item["prompt_id"])
        if target is None:
            raise SemanticReviewError("repeatability references missing prompt")
        for field in ("first_stdout_sha256", "repeat_stdout_sha256"):
            _sha(item[field], field)
        if (
            type(item["same_stdout"]) is not bool
            or item["same_stdout"] != (
                item["first_stdout_sha256"] == item["repeat_stdout_sha256"]
            )
            or item["repeat_stdout_sha256"] != target["stdout_sha256"]
        ):
            raise SemanticReviewError("repeatability hash mismatch")

    return {
        "status": "unreviewed_machine_evidence_only",
        "windows": len(windows),
        "lesson_neutral_agreements": len(windows) - len(mismatched),
        "lesson_neutral_disagreements": mismatched,
        "lesson_alt_context_pairs": alt_pairs,
        "lesson_alt_context_disagreements": alt_mismatched,
        "nonstandard_first_lines": malformed_first_lines,
        "repeatability_checks": len(checks),
    }
