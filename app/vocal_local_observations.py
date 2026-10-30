"""Normalize existing local Whisper/CAM++ cues onto a source PCM frame clock.

This is a *projection* of observations, not an inference provider and not a
speech/vocal classifier. The WhisperNotes source code is never imported.
"""

from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Sequence

from app.vocal_word_speakers import TimedWord


class LocalCueProjectionError(ValueError):
    """A cue cannot be represented on the verified source PCM timeline."""


@dataclass(frozen=True)
class LocalCueObservation:
    cue_id: str
    start_sample: int
    end_sample: int
    text: str
    source_language: str
    speaker_candidate: str | None
    speaker_evidence: str
    words: tuple[TimedWord, ...]
    review_reasons: tuple[str, ...]

    @property
    def needs_review(self) -> bool:
        return bool(self.review_reasons)


def _integer(value: int, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise LocalCueProjectionError(f"{field}: expected integer >= {minimum}")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LocalCueProjectionError(f"{field}: expected nonempty text")
    return value


def _seconds(value: object, field: str) -> Decimal:
    """Require the millisecond clock actually emitted by whisper_transcribe.py."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LocalCueProjectionError(f"{field}: expected non-negative millisecond seconds")
    seconds = Decimal(str(value))
    if not seconds.is_finite() or seconds < 0 or seconds * 1000 != (seconds * 1000).to_integral_value():
        raise LocalCueProjectionError(f"{field}: expected finite non-negative millisecond seconds")
    return seconds


def _frames(seconds: Decimal, rate: int, offset: int, *, is_start: bool) -> int:
    # Floor starts and ceil ends to avoid losing a sample at 44.1 kHz.
    direction = ROUND_FLOOR if is_start else ROUND_CEILING
    return offset + int((seconds * rate).to_integral_value(rounding=direction))


def normalize_local_whisper_cues(
    cues: Sequence[dict],
    *,
    source_language: str,
    sample_rate: int,
    total_samples: int,
    source_offset_samples: int,
) -> tuple[LocalCueObservation, ...]:
    """Project already-produced PersoDub local cues; never perform inference.

    Source PCM sample rate, count and exact excerpt origin come from the
    ingest owner. Raw worker timestamps are absolute *within that excerpt*,
    with 1 ms decimal precision. The caller must establish the excerpt's
    relation to source video PTS; this helper does not infer the offset.

    A CAM++ `speaker` result labels the ASR cue used to extract its embedding,
    not an independently observed speaker turn. It is therefore a candidate
    only, and every cue requires review until stronger evidence exists.
    """
    rate = _integer(sample_rate, "sample_rate", 1)
    total = _integer(total_samples, "total_samples", 1)
    offset = _integer(source_offset_samples, "source_offset_samples")
    if offset >= total:
        raise LocalCueProjectionError("source_offset_samples: outside source PCM")
    language = _text(source_language, "source_language")
    if language not in ("en", "de", "es", "und"):
        raise LocalCueProjectionError("source_language: unsupported observation language")
    if not isinstance(cues, (list, tuple)):
        raise LocalCueProjectionError("cues: expected sequence")

    projected = []
    for index, raw in enumerate(cues, 1):
        where = f"cues[{index - 1}]"
        if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
            raise LocalCueProjectionError(f"{where}: expected object")
        unknown = raw.keys() - {"start", "end", "text", "words", "speaker"}
        missing = {"start", "end", "text"} - raw.keys()
        if unknown or missing:
            raise LocalCueProjectionError(f"{where}: missing {sorted(missing)}, unknown {sorted(unknown)}")

        start_sec = _seconds(raw["start"], f"{where}.start")
        end_sec = _seconds(raw["end"], f"{where}.end")
        if end_sec <= start_sec:
            raise LocalCueProjectionError(f"{where}: non-positive cue duration")
        start = _frames(start_sec, rate, offset, is_start=True)
        end = _frames(end_sec, rate, offset, is_start=False)
        if end <= start or end > total:
            raise LocalCueProjectionError(f"{where}: cue outside source PCM")
        text = _text(raw["text"], f"{where}.text")

        if "speaker" in raw:
            speaker = _text(raw["speaker"], f"{where}.speaker")
            speaker_evidence = "campplus_asr_cue"
            reasons = ["cue_level_speaker_not_independent"]
        else:
            speaker = None
            speaker_evidence = "none"
            reasons = ["no_speaker_evidence"]
        if language in ("es", "und"):
            reasons.append("language_not_approved_for_v1_translation")

        word_rows = raw.get("words", [])
        if not isinstance(word_rows, list):
            raise LocalCueProjectionError(f"{where}.words: expected list")
        words = []
        if not word_rows:
            reasons.append("word_timestamps_unavailable")
        for word_index, row in enumerate(word_rows, 1):
            loc = f"{where}.words[{word_index - 1}]"
            if not isinstance(row, dict) or any(not isinstance(k, str) for k in row):
                raise LocalCueProjectionError(f"{loc}: expected object")
            unknown_word = row.keys() - {"start", "end", "word", "is_estimated"}
            missing_word = {"start", "end", "word"} - row.keys()
            if missing_word or unknown_word:
                raise LocalCueProjectionError(
                    f"{loc}: missing {sorted(missing_word)}, unknown {sorted(unknown_word)}"
                )
            left_sec = _seconds(row["start"], f"{loc}.start")
            right_sec = _seconds(row["end"], f"{loc}.end")
            if right_sec <= left_sec:
                raise LocalCueProjectionError(f"{loc}: non-positive word duration")
            left = _frames(left_sec, rate, offset, is_start=True)
            right = _frames(right_sec, rate, offset, is_start=False)
            if left < start or right > end or right <= left:
                raise LocalCueProjectionError(f"{loc}: word outside parent cue")
            literal = _text(row["word"], f"{loc}.word")
            estimated = row.get("is_estimated", False)
            if not isinstance(estimated, bool):
                raise LocalCueProjectionError(f"{loc}.is_estimated: expected boolean")
            if estimated and "estimated_word_timing" not in reasons:
                reasons.append("estimated_word_timing")
            words.append(TimedWord(f"w_{index:06d}_{word_index:04d}", left, right, literal, estimated))

        if words:
            # The Swift UI fallback interpolates text across missing word spans.
            # A dubbing transcript must never silently fabricate those words.
            reconstructed = "".join(word.text for word in words)
            if " ".join(reconstructed.split()) != " ".join(text.split()):
                reasons.append("word_text_mismatch")
            ordered_words = sorted(words, key=lambda word: (word.start_sample, word.end_sample))
            if any(b.start_sample < a.end_sample for a, b in zip(ordered_words, ordered_words[1:])):
                reasons.append("overlapping_word_timestamps")

        projected.append(
            LocalCueObservation(
                cue_id=f"cue_{index:06d}",
                start_sample=start,
                end_sample=end,
                text=text,
                source_language=language,
                speaker_candidate=speaker,
                speaker_evidence=speaker_evidence,
                words=tuple(words),
                review_reasons=tuple(reasons),
            )
        )

    # Keep original cue identity even when a provider returns unsorted spans.
    sorted_cues = sorted(projected, key=lambda cue: (cue.start_sample, cue.end_sample, cue.cue_id))
    active = []
    conflicting_ids = set()
    for cue in sorted_cues:
        active = [prev for prev in active if prev.end_sample > cue.start_sample]
        if active:
            conflicting_ids.add(cue.cue_id)
            conflicting_ids.update(prev.cue_id for prev in active)
        active.append(cue)
    return tuple(
        replace(cue, review_reasons=cue.review_reasons + ("overlapping_asr_cues",))
        if cue.cue_id in conflicting_ids else cue
        for cue in sorted_cues
    )
