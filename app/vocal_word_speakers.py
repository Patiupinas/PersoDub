"""Conservative word-to-speaker alignment on a decoded PCM sample clock.

The overlap model comes from WhisperNotes SpeakerDiarizationAligner.swift at
2f863db64f41680365a0f9f8772f9147034ea675, but the dubbing-specific
contract deliberately rejects proportional text redistribution and speaker
tie-breaking for overlapping voices. This module makes no dubbing decisions.
"""

from dataclasses import dataclass
from typing import Sequence

from app.vocal_phrase_groups import SpeakerTurn


@dataclass(frozen=True)
class TimedWord:
    word_id: str
    start_sample: int
    end_sample: int
    text: str
    is_estimated: bool = False


@dataclass(frozen=True)
class AttributedWord:
    word: TimedWord
    speaker_id: str | None
    review_reasons: tuple[str, ...]

    @property
    def needs_review(self) -> bool:
        return bool(self.review_reasons)


def _sample(value: int, field: str, *, positive: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < int(positive):
        raise ValueError(f"{field} must be an integer >= {int(positive)}")
    return value


def _coverage(intervals: list[tuple[int, int]]) -> int:
    """Count the union, not the sum, of overlapping turns of one speaker."""
    if not intervals:
        return 0
    ordered = sorted(intervals)
    start, end = ordered[0]
    total = 0
    for next_start, next_end in ordered[1:]:
        if next_start > end:
            total += end - start
            start, end = next_start, next_end
        else:
            end = max(end, next_end)
    return total + end - start


def align_word_speakers(
    words: Sequence[TimedWord],
    turns: Sequence[SpeakerTurn],
    *,
    total_samples: int,
    min_overlap_samples: int = 1,
) -> list[AttributedWord]:
    """Attribute original word spans to one certain speaker or REVIEW.

    Words are not split, interpolated, repeated, or rewritten. If independent
    speaker turns of different IDs overlap a word, the speaker is unresolved,
    even when the WhisperNotes UI aligner would prefer the shorter turn.
    Partial coverage, estimated timings and overlapping ASR words retain the
    candidate speaker, but require review before any downstream translation.

    Input words and turns must already use the source decoded PCM sample clock.
    Missing word timings cannot be inferred here: the parent cue must remain
    REVIEW in the A0/A4 integration until explicit word evidence is available.
    """
    _sample(total_samples, "total_samples", positive=True)
    _sample(min_overlap_samples, "min_overlap_samples", positive=True)

    seen = set()
    verified_words = []
    for word in words:
        if not isinstance(word, TimedWord):
            raise TypeError("words must contain TimedWord")
        if not isinstance(word.word_id, str) or not word.word_id.strip() or word.word_id in seen:
            raise ValueError("word_id must be unique and nonempty")
        seen.add(word.word_id)
        _sample(word.start_sample, "word.start_sample")
        _sample(word.end_sample, "word.end_sample")
        if word.end_sample <= word.start_sample or word.end_sample > total_samples:
            raise ValueError("word interval is empty or outside source PCM")
        if not isinstance(word.text, str) or not word.text.strip():
            raise ValueError("word.text must be nonempty")
        if not isinstance(word.is_estimated, bool):
            raise ValueError("word.is_estimated must be boolean")
        verified_words.append(word)

    verified_turns = []
    for turn in turns:
        if not isinstance(turn, SpeakerTurn):
            raise TypeError("turns must contain SpeakerTurn")
        _sample(turn.start_sample, "turn.start_sample")
        _sample(turn.end_sample, "turn.end_sample")
        if turn.end_sample <= turn.start_sample or turn.end_sample > total_samples:
            raise ValueError("turn interval is empty or outside source PCM")
        if not isinstance(turn.speaker_id, str) or not turn.speaker_id.strip():
            raise ValueError("turn.speaker_id must be nonempty")
        if turn.source != "fallback":
            verified_turns.append(turn)

    ordered_words = sorted(verified_words, key=lambda w: (w.start_sample, w.end_sample, w.word_id))
    ordered_turns = sorted(verified_turns, key=lambda t: (t.start_sample, t.end_sample, t.speaker_id))

    # All ASR words that intersect another ASR word need independent checking.
    intersecting_words: set[str] = set()
    latest: TimedWord | None = None
    for word in ordered_words:
        if latest is not None and word.start_sample < latest.end_sample:
            intersecting_words.add(latest.word_id)
            intersecting_words.add(word.word_id)
        if latest is None or word.end_sample > latest.end_sample:
            latest = word

    active: list[SpeakerTurn] = []
    turn_cursor = 0
    result = []
    for word in ordered_words:
        while turn_cursor < len(ordered_turns) and ordered_turns[turn_cursor].start_sample < word.end_sample:
            active.append(ordered_turns[turn_cursor])
            turn_cursor += 1
        active = [turn for turn in active if turn.end_sample > word.start_sample]

        intervals: dict[str, list[tuple[int, int]]] = {}
        for turn in active:
            left = max(word.start_sample, turn.start_sample)
            right = min(word.end_sample, turn.end_sample)
            if left < right:
                intervals.setdefault(turn.speaker_id, []).append((left, right))

        coverage = {speaker: _coverage(spans) for speaker, spans in intervals.items()}
        duration = word.end_sample - word.start_sample
        speaker_id = None
        reasons = []
        if not coverage:
            reasons.append("no_speaker_evidence")
        elif len(coverage) > 1:
            reasons.append("conflicting_speakers")
        else:
            candidate, covered = next(iter(coverage.items()))
            if candidate == "UNKNOWN":
                reasons.append("unknown_speaker")
            elif covered < min_overlap_samples or covered * 2 < duration:
                reasons.append("insufficient_speaker_coverage")
            else:
                speaker_id = candidate
                if covered < duration:
                    reasons.append("partial_speaker_coverage")

        if word.is_estimated:
            reasons.append("estimated_word_timing")
        if word.word_id in intersecting_words:
            reasons.append("overlapping_asr_words")
        result.append(AttributedWord(word=word, speaker_id=speaker_id, review_reasons=tuple(reasons)))
    return result
