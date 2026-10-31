"""Build research-only audio pre-annotation suggestions from timed observations.

This does not generate A1 gold labels, A4 actions, subtitles, or source text.
It deliberately marks model disagreements and boundary neighborhoods uncertain.
"""

from dataclasses import dataclass
from typing import Sequence

SMAD_LABELS = frozenset(("speech_noise", "speech_music", "singing_music", "none"))
INA_LABELS = frozenset(("speech", "music", "noise", "noEnergy"))
CANDIDATE_LABELS = frozenset(
    ("speech_candidate", "vocal_demo_candidate", "non_target_candidate", "uncertain")
)


class PreannotationError(ValueError):
    """Evidence is malformed or cannot be attached to this source clock."""


@dataclass(frozen=True)
class EventObservation:
    start_sample: int
    end_sample: int
    label: str


@dataclass(frozen=True)
class ProposedEvent:
    start_sample: int
    end_sample: int
    candidate: str
    evidence: tuple[str, ...]


def _positive_int(value: object, name: str, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise PreannotationError(f"{name}: expected integer >= {minimum}")
    return value


def _check_events(
    events: Sequence[EventObservation],
    *,
    total_samples: int,
    allowed: frozenset[str] | None = None,
    require_full_coverage: bool = False,
) -> tuple[EventObservation, ...]:
    if not isinstance(events, (list, tuple)):
        raise PreannotationError("expected sequence of EventObservation")
    if require_full_coverage and not events:
        raise PreannotationError("complete observation timeline is required")
    previous_end = 0
    for idx, event in enumerate(events):
        if not isinstance(event, EventObservation):
            raise PreannotationError(f"event[{idx}] is not EventObservation")
        if (
            type(event.start_sample) is not int
            or type(event.end_sample) is not int
            or not 0 <= event.start_sample < event.end_sample <= total_samples
        ):
            raise PreannotationError(f"event[{idx}]: invalid source PCM interval")
        if event.start_sample < previous_end or (
            require_full_coverage and event.start_sample != previous_end
        ):
            raise PreannotationError(f"event[{idx}]: overlap or uncovered source PCM")
        if allowed is not None and event.label not in allowed:
            raise PreannotationError(f"event[{idx}]: unknown model label")
        previous_end = event.end_sample
    if require_full_coverage and previous_end != total_samples:
        raise PreannotationError("observations do not cover source PCM tail")
    return tuple(events)


def suggest_annotation_candidates(
    *,
    sample_rate: int,
    total_samples: int,
    source_offset_samples: int,
    smad: Sequence[EventObservation],
    ina: Sequence[EventObservation],
    asr_words: Sequence[EventObservation],
    boundary_review_seconds: int = 2,
) -> tuple[ProposedEvent, ...]:
    """Return a complete provisional partition; never infer TRANSLATE/PRESERVE.

    SMAD is a one-second timeline generated from four-second acoustic windows.
    INA may contain gaps near the tail. ASR words are evidence of content only,
    including lyrics: their presence does not imply ordinary spoken explanation.

    A boundary neighborhood is marked uncertain whenever either acoustic
    model changes its label. Numeric input and output use the same decoded PCM
    sample clock; source_offset_samples maps this derivative excerpt to a
    longer upstream recording but is not proof of original-video PTS equality.
    """
    rate = _positive_int(sample_rate, "sample_rate")
    total = _positive_int(total_samples, "total_samples")
    offset = _positive_int(source_offset_samples, "source_offset_samples", minimum=0)
    pad_seconds = _positive_int(
        boundary_review_seconds, "boundary_review_seconds", minimum=0
    )
    if total % rate:
        raise PreannotationError("source excerpt requires complete one-second cells")
    smad_events = _check_events(
        smad, total_samples=total, allowed=SMAD_LABELS, require_full_coverage=True
    )
    ina_events = _check_events(ina, total_samples=total, allowed=INA_LABELS)
    words = _check_events(asr_words, total_samples=total)
    for index, event in enumerate(smad_events):
        if (
            event.start_sample != index * rate
            or event.end_sample != (index + 1) * rate
        ):
            raise PreannotationError("SMAD annotations must be exact one-second cells")
    if len(smad_events) != total // rate:
        raise PreannotationError("SMAD one-second timeline has missing cells")

    boundary_points: set[int] = set()
    for observations in (smad_events, ina_events):
        for earlier, later in zip(observations, observations[1:]):
            if earlier.label != later.label:
                boundary_points.add(earlier.end_sample)
                boundary_points.add(later.start_sample)

    cells: list[ProposedEvent] = []
    for second, detected in enumerate(smad_events):
        left = second * rate
        right = left + rate
        ina_matches = [
            item for item in ina_events
            if item.start_sample < right and item.end_sample > left
        ]
        ina_full = (
            len(ina_matches) == 1
            and ina_matches[0].start_sample <= left
            and ina_matches[0].end_sample >= right
        )
        ina_label = ina_matches[0].label if ina_full else "mixed_or_missing"
        has_words = any(word.start_sample < right and word.end_sample > left for word in words)
        near_boundary = any(
            left < point + pad_seconds * rate and
            right > point - pad_seconds * rate
            for point in boundary_points
        )
        evidence = (f"smad:{detected.label}", f"ina:{ina_label}",
                    "asr:words" if has_words else "asr:no_words")
        if near_boundary:
            candidate = "uncertain"
            evidence += ("acoustic_boundary",)
        elif detected.label == "singing_music" and ina_label == "music":
            candidate = "vocal_demo_candidate"
        elif (
            detected.label in ("speech_noise", "speech_music")
            and ina_label == "speech"
            and has_words
        ):
            candidate = "speech_candidate"
        elif detected.label == "none" and ina_label == "noEnergy" and not has_words:
            candidate = "non_target_candidate"
        else:
            candidate = "uncertain"
        cells.append(ProposedEvent(left + offset, right + offset, candidate, evidence))

    merged: list[ProposedEvent] = []
    for event in cells:
        if merged and merged[-1].candidate == event.candidate:
            previous = merged.pop()
            merged.append(
                ProposedEvent(
                    previous.start_sample, event.end_sample, event.candidate,
                    tuple(sorted(set(previous.evidence + event.evidence))),
                )
            )
        else:
            merged.append(event)
    if (
        not merged
        or merged[0].start_sample != offset
        or merged[-1].end_sample != offset + total
        or any(left.end_sample != right.start_sample for left, right in zip(merged, merged[1:]))
        or any(event.candidate not in CANDIDATE_LABELS for event in merged)
    ):
        raise PreannotationError("output proposals do not partition the excerpt")
    return tuple(merged)
