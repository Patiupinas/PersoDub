"""Pure, source-clock grouping of diarization turns for vocal lectures.

Adapted from WhisperNotes SessionPhraseBuilder.swift at
2f863db64f41680365a0f9f8772f9147034ea675. The inputs are already
normalized integer PCM samples, rather than Swift TimeInterval seconds.
This module does not infer speech, translate, or authorize dubbing.
"""

from dataclasses import dataclass, replace
from typing import Sequence


@dataclass(frozen=True)
class SpeakerTurn:
    start_sample: int
    end_sample: int
    speaker_id: str
    source: str = ""


@dataclass(frozen=True)
class PhraseGroup:
    phrase_id: str
    speaker_id: str
    start_sample: int
    end_sample: int


def _checked_samples(value: int, name: str, *, zero_allowed: bool) -> int:
    if type(value) is not int or value < 0 or (not zero_allowed and value == 0):
        raise ValueError(f"{name} must be a {'non-negative' if zero_allowed else 'positive'} integer")
    return value


def build_phrase_groups(
    turns: Sequence[SpeakerTurn],
    *,
    sample_rate: int,
    merge_gap_samples: int | None = None,
    max_phrase_samples: int | None = None,
) -> list[PhraseGroup]:
    """Group adjacent same-speaker turns, splitting long groups.

    The default 10-second merge gap and 45-second duration mirror the pinned
    WhisperNotes reference, but are configurable in samples. They are *not*
    permissions to dub: a vocal demonstration can occupy the gap between two
    spoken turns. The acoustic policy must decide protected intervals later.

    The reference deliberately drops diarization turns tagged ``fallback``
    and zero/reversed intervals. A caller must account for uncovered audio
    separately instead of treating absent turns as safe translation windows.
    """
    _checked_samples(sample_rate, "sample_rate", zero_allowed=False)
    gap = 10 * sample_rate if merge_gap_samples is None else merge_gap_samples
    limit = 45 * sample_rate if max_phrase_samples is None else max_phrase_samples
    _checked_samples(gap, "merge_gap_samples", zero_allowed=True)
    _checked_samples(limit, "max_phrase_samples", zero_allowed=False)

    usable = []
    for turn in turns:
        if not isinstance(turn, SpeakerTurn):
            raise TypeError("turns must contain SpeakerTurn values")
        if turn.source == "fallback":
            continue
        _checked_samples(turn.start_sample, "start_sample", zero_allowed=True)
        _checked_samples(turn.end_sample, "end_sample", zero_allowed=True)
        if not isinstance(turn.speaker_id, str) or not turn.speaker_id.strip():
            raise ValueError("speaker_id must be a non-empty string")
        if turn.end_sample > turn.start_sample:
            usable.append(turn)

    usable.sort(key=lambda turn: (turn.start_sample, turn.end_sample))
    if not usable:
        return []

    merged = []
    current = usable[0]
    for turn in usable[1:]:
        if turn.speaker_id == current.speaker_id and turn.start_sample - current.end_sample <= gap:
            current = replace(current, end_sample=max(current.end_sample, turn.end_sample))
        else:
            merged.append(current)
            current = turn
    merged.append(current)

    phrases = []
    for index, turn in enumerate(merged, 1):
        parts = []
        cursor = turn.start_sample
        while cursor < turn.end_sample:
            end = min(cursor + limit, turn.end_sample)
            parts.append((cursor, end))
            cursor = end
        prefix = f"phrase_{index:03d}"
        for part_index, (start, end) in enumerate(parts, 1):
            suffix = f"_{part_index}" if len(parts) > 1 else ""
            phrases.append(PhraseGroup(prefix + suffix, turn.speaker_id, start, end))
    return phrases
