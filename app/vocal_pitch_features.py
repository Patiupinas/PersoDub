"""Summarize time-aligned F0 evidence from an independently extracted vocal stem.

This module does not load audio or ASR models and never infers a dubbing action.
It accepts integer source-PCM sample indices anchored by the ingest owner.
"""

import math
from dataclasses import dataclass
from typing import Sequence


class PitchEvidenceError(ValueError):
    """A pitch track cannot be trusted on the claimed source PCM interval."""


@dataclass(frozen=True)
class PitchFrame:
    start_sample: int
    end_sample: int
    f0_hz: float | None
    voiced_probability: float


@dataclass(frozen=True)
class PitchSummary:
    start_sample: int
    end_sample: int
    voiced_fraction: float
    longest_voiced_seconds: float
    longest_stable_pitch_seconds: float
    mean_voiced_probability: float
    median_f0_hz: float | None
    f0_p10_p90_semitones: float | None


def _integer(value: object, name: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise PitchEvidenceError(f"{name}: expected integer >= {minimum}")
    return value


def _quantile(samples: Sequence[tuple[float, int]], percentile: float) -> float:
    """Return a duration-weighted quantile without expanding PCM samples."""
    ordered = sorted(samples, key=lambda row: row[0])
    total = sum(duration for _, duration in ordered)
    if total < 1:
        raise PitchEvidenceError("cannot compute quantile without voiced frames")
    threshold = percentile * total
    cumulative = 0
    for value, duration in ordered:
        cumulative += duration
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def summarize_pitch_frames(
    frames: Sequence[PitchFrame],
    *,
    sample_rate: int,
    total_samples: int,
    start_sample: int,
    end_sample: int,
    stable_pitch_tolerance_semitones: float = 0.75,
) -> PitchSummary:
    """Measure voiced runs and F0 stability, not speech/singing labels.

    The sequence must cover the requested window exactly, including unvoiced
    frames (f0_hz=None). Gaps, overlaps, extrapolated audio and invalid f0
    values fail rather than implying silence or ordinary speech.

    Stability is a *descriptive* excursion from the first pitch in a run. A
    glissando can be sung while having a short stable run; music instruments
    in a polyphonic mixture can produce the same evidence as a singer.
    """
    rate = _integer(sample_rate, "sample_rate", 1)
    total = _integer(total_samples, "total_samples", 1)
    start = _integer(start_sample, "start_sample", 0)
    end = _integer(end_sample, "end_sample", 1)
    if not 0 <= start < end <= total:
        raise PitchEvidenceError("window outside source PCM")
    if (
        type(stable_pitch_tolerance_semitones) not in (int, float)
        or not math.isfinite(stable_pitch_tolerance_semitones)
        or stable_pitch_tolerance_semitones <= 0
    ):
        raise PitchEvidenceError("stable_pitch_tolerance_semitones must be positive and finite")
    if not isinstance(frames, (list, tuple)) or not frames:
        raise PitchEvidenceError("nonempty ordered pitch frames required")

    cursor = start
    voiced_samples = 0
    probability_sum = 0.0
    longest_voiced = current_voiced = 0
    longest_stable = current_stable = 0
    stable_anchor = None
    weighted_pitches: list[tuple[float, int]] = []
    previous_end = -1
    for index, frame in enumerate(frames):
        if not isinstance(frame, PitchFrame):
            raise PitchEvidenceError(f"frames[{index}]: expected PitchFrame")
        left = _integer(frame.start_sample, f"frames[{index}].start_sample", 0)
        right = _integer(frame.end_sample, f"frames[{index}].end_sample", 1)
        if right <= left or right > total or left < previous_end:
            raise PitchEvidenceError(f"frames[{index}]: invalid or unsorted PCM interval")
        previous_end = right
        probability = frame.voiced_probability
        if type(probability) not in (int, float) or not math.isfinite(probability) or not 0 <= probability <= 1:
            raise PitchEvidenceError(f"frames[{index}]: invalid voiced probability")
        pitch = frame.f0_hz
        if pitch is not None and (
            type(pitch) not in (int, float) or not math.isfinite(pitch) or pitch <= 0
        ):
            raise PitchEvidenceError(f"frames[{index}]: invalid f0_hz")
        if right <= start or left >= end:
            continue
        a, b = max(start, left), min(end, right)
        if a != cursor:
            raise PitchEvidenceError(f"pitch frames do not cover PCM at {cursor}")
        duration = b - a
        cursor = b
        probability_sum += duration * probability
        if pitch is None:
            current_voiced = 0
            current_stable = 0
            stable_anchor = None
            continue
        voiced_samples += duration
        weighted_pitches.append((float(pitch), duration))
        current_voiced += duration
        longest_voiced = max(longest_voiced, current_voiced)
        if stable_anchor is None or abs(12 * math.log2(pitch / stable_anchor)) > stable_pitch_tolerance_semitones:
            stable_anchor = pitch
            current_stable = duration
        else:
            current_stable += duration
        longest_stable = max(longest_stable, current_stable)
    if cursor != end:
        raise PitchEvidenceError(f"pitch frames do not cover PCM tail [{cursor}, {end})")

    med = p10 = p90 = None
    if weighted_pitches:
        med = _quantile(weighted_pitches, 0.5)
        p10 = _quantile(weighted_pitches, 0.1)
        p90 = _quantile(weighted_pitches, 0.9)
    return PitchSummary(
        start_sample=start,
        end_sample=end,
        voiced_fraction=voiced_samples / (end - start),
        longest_voiced_seconds=longest_voiced / rate,
        longest_stable_pitch_seconds=longest_stable / rate,
        mean_voiced_probability=probability_sum / (end - start),
        median_f0_hz=med,
        f0_p10_p90_semitones=12 * math.log2(p90 / p10) if p10 is not None else None,
    )
