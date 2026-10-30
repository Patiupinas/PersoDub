"""Audit MAVC100 speech/singing cue annotations without loading source media.

The dataset labels describe performances, not instructional speech. A speech
annotation is never independent permission to dub the underlying audio.
"""

import argparse
import csv
import hashlib
import io
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

KIND_NAMES = {"1": "speech", "2": "singing", "3": "silence"}
REQUIRED_COLUMNS = ("Name", "Start", "Duration", "Time Format", "Type", "Description")


class MAVCAnnotationError(ValueError):
    """A marker sequence cannot be resolved without guessing timestamps."""


@dataclass(frozen=True)
class MAVCEvent:
    kind: str
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class MAVCClip:
    clip_id: str
    source_id: str
    annotation_sha256: str
    events: tuple[MAVCEvent, ...]


def _time_ms(value: str, where: str) -> int:
    if not isinstance(value, str) or value.count(":") != 1:
        raise MAVCAnnotationError(f"{where}: expected MM:SS.mmm")
    minute, second = value.strip().split(":")
    if not minute.isdigit() or not second or second.startswith(("-", "+")):
        raise MAVCAnnotationError(f"{where}: invalid timestamp")
    try:
        sec = Decimal(second)
    except InvalidOperation as exc:
        raise MAVCAnnotationError(f"{where}: invalid timestamp") from exc
    if not sec.is_finite() or sec < 0 or sec >= 60:
        raise MAVCAnnotationError(f"{where}: seconds out of range")
    millisecond = (Decimal(int(minute)) * 60 + sec) * 1000
    if millisecond != millisecond.to_integral_value():
        raise MAVCAnnotationError(f"{where}: non-millisecond precision")
    return int(millisecond)


def _split_clip_id(name: str) -> tuple[str, str]:
    if not name or not name.endswith(".csv"):
        raise MAVCAnnotationError("label file: expected a .csv filename")
    clip = name[:-4]
    source, sep, number = clip.rpartition("_")
    if not sep or not source or not number.isdigit():
        raise MAVCAnnotationError(f"{name}: expected source identifier and numbered clip")
    return clip, source


def parse_mavc_csv(raw: bytes, *, filename: str) -> MAVCClip:
    """Pair actual cue start/end markers with exact millisecond precision."""
    clip_id, source_id = _split_clip_id(filename)
    if not isinstance(raw, bytes):
        raise TypeError("raw: expected original annotation bytes")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise MAVCAnnotationError(f"{filename}: invalid UTF-8") from exc
    rows = csv.DictReader(io.StringIO(content, newline=""), delimiter="\t")
    if tuple(rows.fieldnames or ()) != REQUIRED_COLUMNS:
        raise MAVCAnnotationError(f"{filename}: unexpected annotation columns")
    active: dict[str, int] = {}
    events: list[MAVCEvent] = []
    for line, row in enumerate(rows, 2):
        where = f"{filename}:{line}"
        if None in row or row["Type"] != "Cue" or row["Time Format"] != "decimal":
            raise MAVCAnnotationError(f"{where}: malformed cue row")
        marker_value = row["Name"]
        # A published file has a harmless trailing space after one start marker.
        marker = marker_value.strip() if isinstance(marker_value, str) else marker_value
        if marker is None or len(marker) != 2 or marker[0] not in KIND_NAMES or marker[1] not in "se":
            raise MAVCAnnotationError(f"{where}: unrecognized label marker")
        code, edge = marker
        timestamp = _time_ms(row["Start"], where)
        if edge == "s":
            if code in active:
                raise MAVCAnnotationError(f"{where}: repeated start for {KIND_NAMES[code]}")
            active[code] = timestamp
        else:
            if code not in active:
                raise MAVCAnnotationError(f"{where}: unmatched end for {KIND_NAMES[code]}")
            start = active.pop(code)
            if timestamp < start:
                raise MAVCAnnotationError(f"{where}: reversed interval")
            if timestamp > start:
                events.append(MAVCEvent(KIND_NAMES[code], start, timestamp))
    if active:
        raise MAVCAnnotationError(f"{filename}: unclosed labels {sorted(KIND_NAMES[x] for x in active)}")
    events.sort(key=lambda x: (x.start_ms, x.end_ms, x.kind))
    for left, right in zip(events, events[1:]):
        if right.start_ms < left.end_ms:
            raise MAVCAnnotationError(f"{filename}: overlapping labels require manual reconciliation")
    return MAVCClip(clip_id, source_id, hashlib.sha256(raw).hexdigest(), tuple(events))


def _triads(clip: MAVCClip, *, min_event_ms: int, max_gap_ms: int) -> list[tuple[MAVCEvent, ...]]:
    voiced = [event for event in clip.events if event.kind in ("speech", "singing")]
    return [
        (first, middle, last)
        for first, middle, last in zip(voiced, voiced[1:], voiced[2:])
        if (first.kind, middle.kind, last.kind) == ("speech", "singing", "speech")
        and min(first.duration_ms, middle.duration_ms, last.duration_ms) >= min_event_ms
        and 0 <= middle.start_ms - first.end_ms <= max_gap_ms
        and 0 <= last.start_ms - middle.end_ms <= max_gap_ms
    ]


def audit_mavc_directory(
    directory: str | Path,
    *,
    limit: int = 3,
    min_event_ms: int = 500,
    max_gap_ms: int = 3000,
    selected_clip_ids: tuple[str, ...] | None = None,
) -> dict:
    """Select source-disjoint candidates; never infer that Speech == explanation."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise MAVCAnnotationError("limit must be a positive integer")
    for name, value in (("min_event_ms", min_event_ms), ("max_gap_ms", max_gap_ms)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise MAVCAnnotationError(f"{name} must be a nonnegative integer")
    folder = Path(directory)
    if not folder.is_dir():
        raise MAVCAnnotationError("labels directory does not exist")
    paths = sorted(folder.glob("*.csv"))
    if not paths:
        raise MAVCAnnotationError("labels directory has no CSV files")

    valid: list[tuple[MAVCClip, list[tuple[MAVCEvent, ...]]]] = []
    invalid: list[dict] = []
    for path in paths:
        try:
            clip = parse_mavc_csv(path.read_bytes(), filename=path.name)
        except MAVCAnnotationError as exc:
            invalid.append({"file": path.name, "reason": str(exc)})
            continue
        valid.append((clip, _triads(clip, min_event_ms=min_event_ms, max_gap_ms=max_gap_ms)))

    mixed = sum(
        any(e.kind == "speech" for e in clip.events)
        and any(e.kind == "singing" for e in clip.events)
        for clip, _ in valid
    )
    ranked = sorted(
        (pair for pair in valid if pair[1]),
        key=lambda pair: (
            -len(pair[1]),
            -min(
                sum(e.duration_ms for e in pair[0].events if e.kind == "speech"),
                sum(e.duration_ms for e in pair[0].events if e.kind == "singing"),
            ),
            pair[0].source_id,
            pair[0].clip_id,
        ),
    )
    if selected_clip_ids is not None:
        if not isinstance(selected_clip_ids, (tuple, list)) or not selected_clip_ids:
            raise MAVCAnnotationError("selected_clip_ids must be a nonempty list of exact clip IDs")
        if any(not isinstance(clip_id, str) or not clip_id for clip_id in selected_clip_ids):
            raise MAVCAnnotationError("selected clip IDs must be nonempty strings")
        if len(selected_clip_ids) > limit or len(set(selected_clip_ids)) != len(selected_clip_ids):
            raise MAVCAnnotationError("selected clip count or duplicate identifiers are invalid")
        eligible = {clip.clip_id: (clip, triads) for clip, triads in ranked}
        if any(not isinstance(clip_id, str) or clip_id not in eligible for clip_id in selected_clip_ids):
            raise MAVCAnnotationError("a requested clip is unknown or lacks a strict transition")
        candidates = [eligible[clip_id] for clip_id in selected_clip_ids]
    else:
        candidates = ranked
    picks: list[dict] = []
    used_sources: set[str] = set()
    for clip, triads in candidates:
        if clip.source_id in used_sources:
            if selected_clip_ids is not None:
                raise MAVCAnnotationError("requested clips reuse the same original source recording")
            continue
        used_sources.add(clip.source_id)
        picks.append({
            "clip_id": clip.clip_id,
            "source_id": clip.source_id,
            "annotation_sha256": clip.annotation_sha256,
            "speech_singing_speech_patterns": len(triads),
            "event_counts": {name: sum(e.kind == name for e in clip.events) for name in KIND_NAMES.values()},
            "event_duration_ms": {
                name: sum(e.duration_ms for e in clip.events if e.kind == name)
                for name in KIND_NAMES.values()
            },
            "example_pattern_ms": [
                {"label": event.kind, "start_ms": event.start_ms, "end_ms": event.end_ms}
                for event in triads[0]
            ],
        })
        if len(picks) >= limit:
            break

    return {
        "schema_version": 1,
        "source": "MAVC100: published audio-stream timestamp annotations",
        "total_label_files": len(paths),
        "valid_label_files": len(valid),
        "invalid_label_files": invalid,
        "mixed_speech_singing_files": mixed,
        "mixed_min_duration_files": sum(
            any(e.kind == "speech" and e.duration_ms >= min_event_ms for e in clip.events)
            and any(e.kind == "singing" and e.duration_ms >= min_event_ms for e in clip.events)
            for clip, _ in valid
        ),
        "speech_singing_speech_files": sum(bool(triads) for _, triads in valid),
        "selected": picks,
        "notes": [
            "These labels describe musical performance, not teacher explanations.",
            "Speech and singing event timestamps are observations, not source PCM frames.",
            "No video, model, audio signal, or rights to redistribute media are provided.",
            "The selected candidates are source-disjoint, not an independently approved holdout.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit only extracted MAVC100 audio-label CSV files")
    parser.add_argument("--labels", required=True, help="Directory of extracted CSV annotation files")
    parser.add_argument("--output", required=True, help="JSON audit destination (not media)")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--max-gap-ms", type=int, default=3000)
    parser.add_argument("--min-event-ms", type=int, default=500)
    parser.add_argument("--clip", dest="selected_clip_ids", action="append",
                        help="Exact existing clip ID; repeat to limit the selected subset")
    args = parser.parse_args(argv)
    report = audit_mavc_directory(
        args.labels,
        limit=args.limit,
        min_event_ms=args.min_event_ms,
        max_gap_ms=args.max_gap_ms,
        selected_clip_ids=tuple(args.selected_clip_ids) if args.selected_clip_ids is not None else None,
    )
    output = Path(args.output)
    if output.exists():
        raise MAVCAnnotationError("output file already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
