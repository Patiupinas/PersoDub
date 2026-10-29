"""Align sample-indexed ASR phrases and acoustic tracks without splitting TTS text.

This model-free module does not convert floating seconds to PCM sample indices.
Upstream ingest owns decoded-PCM provenance and offset/PTS mapping. Every
acoustic provider must cover every sample; missing evidence is never inferred.
"""

import argparse
import json
from bisect import bisect_right
from pathlib import Path

from app.vocal_policy import ALLOWED_LABELS, select_vocal_decisions


class ObservationAlignmentError(ValueError):
    """Input tracks or intervals cannot support a trustworthy decision."""


def _object(value, where, fields, required):
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ObservationAlignmentError(f"{where}: expected object with string keys")
    missing = required - value.keys()
    unknown = value.keys() - fields
    if missing or unknown:
        raise ObservationAlignmentError(f"{where}: missing {sorted(missing)}, unknown {sorted(unknown)}")
    return value


def _integer(value, where, lower):
    if type(value) is not int or value < lower:
        raise ObservationAlignmentError(f"{where}: expected integer >= {lower}")
    return value


def _nonempty(value, where):
    if not isinstance(value, str) or not value.strip():
        raise ObservationAlignmentError(f"{where}: expected nonempty string")
    return value


def _intervals(raw, kind, length, *, complete):
    if not isinstance(raw, list):
        raise ObservationAlignmentError(f"{kind}: expected list")
    if complete and not raw:
        raise ObservationAlignmentError(f"{kind}: empty acoustic track")
    result = []
    previous_end = 0
    for i, part in enumerate(raw):
        where = f"{kind}[{i}]"
        fields = {"start_sample", "end_sample"}
        extras = {"label"} if complete else {"text", "language", "speaker_id"}
        item = _object(part, where, fields | extras, fields | (extras - {"speaker_id"}))
        start = _integer(item["start_sample"], f"{where}.start_sample", 0)
        end = _integer(item["end_sample"], f"{where}.end_sample", 0)
        if end <= start or end > length:
            raise ObservationAlignmentError(f"{where}: empty or out-of-range interval")
        if start < previous_end:
            raise ObservationAlignmentError(f"{where}: overlapping or unsorted intervals")
        if complete and start != previous_end:
            raise ObservationAlignmentError(f"{where}: uncovered acoustic samples [{previous_end}, {start})")
        previous_end = end
        if complete:
            label = _nonempty(item["label"], f"{where}.label")
            if label not in ALLOWED_LABELS:
                raise ObservationAlignmentError(f"{where}: unknown acoustic label {label!r}")
            if result and result[-1][1] == start and result[-1][2] == label:
                result[-1] = (result[-1][0], end, label)
            else:
                result.append((start, end, label))
        else:
            asr = {"text": _nonempty(item["text"], f"{where}.text"),
                   "language": _nonempty(item["language"], f"{where}.language")}
            if asr["language"] not in ("en", "de", "und"):
                raise ObservationAlignmentError(f"{where}: unsupported ASR language")
            if "speaker_id" in item:
                asr["speaker_id"] = _nonempty(item["speaker_id"], f"{where}.speaker_id")
            result.append((start, end, asr))
    if complete and previous_end != length:
        raise ObservationAlignmentError(f"{kind}: uncovered acoustic tail [{previous_end}, {length})")
    return result


def _label_for(track, starts, start, end):
    index = bisect_right(starts, start) - 1
    if index < 0 or end > track[index][1]:
        # The model changed category at least once inside this interval.
        # Returning 'uncertain' forces REVIEW without repeating the ASR text.
        return "uncertain"
    return track[index][2]


def align_observations(raw):
    """Return contiguous policy observations on a decoded PCM sample timeline.

    ASR phrases are indivisible: a detector category change inside a phrase
    marks that detector uncertain across the *entire* phrase. This prevents
    accidental TTS duplication and protects vocal onsets at phrase boundaries.
    Unknown ASR gaps are partitioned by detector boundaries, without assuming
    anything about the missing transcript.
    """
    root_fields = {"schema_version", "source_sha256", "pcm_sha256", "sample_rate",
                   "total_samples", "model_revisions", "asr_segments", "acoustic_tracks"}
    obj = _object(raw, "source", root_fields, root_fields)
    total = _integer(obj["total_samples"], "total_samples", 1)
    _integer(obj["sample_rate"], "sample_rate", 1)
    revisions = obj["model_revisions"]
    tracks = obj["acoustic_tracks"]
    if not isinstance(revisions, dict) or any(not isinstance(k, str) for k in revisions):
        raise ObservationAlignmentError("model_revisions: expected string-keyed object")
    if not isinstance(tracks, dict) or any(not isinstance(k, str) for k in tracks):
        raise ObservationAlignmentError("acoustic_tracks: expected string-keyed object")
    if set(revisions) != set(tracks):
        raise ObservationAlignmentError("acoustic_tracks must match declared model_revisions")
    asr = _intervals(obj["asr_segments"], "asr_segments", total, complete=False)
    normalized = {}
    starts = {}
    boundaries = {0, total}
    for model_id in sorted(revisions):
        _nonempty(model_id, "model_id")
        _nonempty(revisions[model_id], f"model_revisions[{model_id!r}]")
        segments = _intervals(tracks[model_id], f"acoustic_tracks[{model_id!r}]", total, complete=True)
        normalized[model_id] = segments
        starts[model_id] = [item[0] for item in segments]
        boundaries.update(segment[0] for segment in segments)
        boundaries.update(segment[1] for segment in segments)
    boundaries = sorted(boundaries)

    def votes(start, end):
        return [{"model_id": model_id,
                 "label": _label_for(normalized[model_id], starts[model_id], start, end)}
                for model_id in sorted(normalized)]

    windows = []

    def append_gap(left, right):
        if left == right:
            return
        i = bisect_right(boundaries, left)
        cut_points = [left]
        while i < len(boundaries) and boundaries[i] < right:
            cut_points.append(boundaries[i])
            i += 1
        cut_points.append(right)
        for a, b in zip(cut_points, cut_points[1:]):
            windows.append({"start_sample": a, "end_sample": b, "asr": None,
                            "votes": votes(a, b)})

    cursor = 0
    for begin, end, metadata in asr:
        append_gap(cursor, begin)
        windows.append({"start_sample": begin, "end_sample": end,
                        "asr": metadata, "votes": votes(begin, end)})
        cursor = end
    append_gap(cursor, total)
    result = {k: obj[k] for k in ("schema_version", "source_sha256", "pcm_sha256",
                                   "sample_rate", "total_samples", "model_revisions")}
    result["windows"] = windows
    # The policy and original manifest validator are the sole authority for
    # valid decisions, strict coverage, and metadata integrity.
    select_vocal_decisions(result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline integer-sample ASR/acoustic alignment")
    parser.add_argument("--source", type=Path, required=True, help="JSON with ASR spans and acoustic tracks")
    args = parser.parse_args(argv)
    try:
        with args.source.open(encoding="utf-8") as handle:
            result = align_observations(json.load(handle))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Observation alignment failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
