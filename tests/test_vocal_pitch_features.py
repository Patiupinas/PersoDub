"""Source-clock pitch descriptions without semantic or musical classification."""

import math

import pytest

from app.vocal_pitch_features import (
    PitchEvidenceError,
    PitchFrame,
    summarize_pitch_frames,
)


def describe(frames, **kwargs):
    return summarize_pitch_frames(
        frames, sample_rate=1000, total_samples=10000,
        start_sample=0, end_sample=1000, **kwargs,
    )


def test_sustained_note_is_descriptive_not_translation_permission():
    frames = [PitchFrame(i, i + 100, 440.0, 0.91) for i in range(0, 1000, 100)]
    result = describe(frames)
    assert result.voiced_fraction == 1
    assert result.longest_voiced_seconds == 1
    assert result.longest_stable_pitch_seconds == 1
    assert result.f0_p10_p90_semitones == 0
    assert result.median_f0_hz == 440
    assert not hasattr(result, "action")


def test_pitch_glide_remains_voiced_but_not_one_stable_note():
    frames = [PitchFrame(i, i + 100, 220 * 2 ** (i / 1000), 0.8)
              for i in range(0, 1000, 100)]
    result = describe(frames)
    assert result.longest_voiced_seconds == 1
    assert result.longest_stable_pitch_seconds == pytest.approx(0.1)
    assert result.f0_p10_p90_semitones >= 8


def test_unvoiced_frames_are_not_normal_speech_evidence():
    result = describe([PitchFrame(0, 1000, None, 0.05)])
    assert result.voiced_fraction == 0
    assert result.median_f0_hz is None
    assert result.f0_p10_p90_semitones is None
    assert result.longest_stable_pitch_seconds == 0
    assert not hasattr(result, "label")


def test_consonant_break_ends_earlier_voiced_run():
    result = describe([
        PitchFrame(0, 300, 200.0, 0.8), PitchFrame(300, 400, None, 0.1),
        PitchFrame(400, 1000, 205.0, 0.9),
    ])
    assert result.voiced_fraction == 0.9
    assert result.longest_voiced_seconds == pytest.approx(0.6)
    assert result.longest_stable_pitch_seconds == pytest.approx(0.6)


def test_window_crop_preserves_source_sample_origin_and_duration():
    frames = [PitchFrame(0, 400, 100.0, 0.2),
              PitchFrame(400, 700, 200.0, 0.4),
              PitchFrame(700, 1200, 220.0, 0.8)]
    output = summarize_pitch_frames(frames, sample_rate=1000, total_samples=2000,
                                    start_sample=500, end_sample=1000)
    assert output.voiced_fraction == 1
    assert output.median_f0_hz == 220.0
    assert output.start_sample == 500 and output.end_sample == 1000
    assert output.mean_voiced_probability == pytest.approx((200 * 0.4 + 300 * 0.8) / 500)


def test_duration_weighted_f0_median_not_frame_count_median():
    result = describe([
        PitchFrame(0, 100, 120.0, 0.8),
        PitchFrame(100, 1000, 240.0, 0.8),
    ])
    assert result.median_f0_hz == 240


@pytest.mark.parametrize("frames,reason", [
    ([], "nonempty"),
    ([PitchFrame(0, 900, 440, 0.8)], "tail"),
    ([PitchFrame(0, 400, 440, 0.8), PitchFrame(500, 1000, 440, 0.8)], "cover"),
    ([PitchFrame(0, 600, 440, 0.8), PitchFrame(500, 1000, 440, 0.8)], "unsorted"),
    ([PitchFrame(0, 1000, float("nan"), 0.8)], "f0"),
    ([PitchFrame(0, 1000, 0, 0.8)], "f0"),
    ([PitchFrame(0, 1000, 440, 1.2)], "probability"),
    ([PitchFrame(0, 1000, 440, True)], "probability"),
    ([PitchFrame(0, 1000, None, float("inf"))], "probability"),
    ([PitchFrame(0, 1000, 440, 0.8), PitchFrame(1000, 11000, 440, 0.8)], "interval"),
    ([{"start_sample": 0, "end_sample": 1000, "f0_hz": 440, "voiced_probability": 0.8}], "PitchFrame"),
])
def test_malformed_pitch_tracks_fail_closed(frames, reason):
    with pytest.raises(PitchEvidenceError, match=reason):
        describe(frames)


@pytest.mark.parametrize("changes", [
    {"sample_rate": True}, {"sample_rate": 0}, {"total_samples": 0},
    {"start_sample": -1}, {"start_sample": 1000}, {"end_sample": 10001},
    {"stable_pitch_tolerance_semitones": float("inf")},
    {"stable_pitch_tolerance_semitones": -0.1},
])
def test_bad_clock_or_tolerance_rejected(changes):
    arguments = dict(sample_rate=1000, total_samples=10000, start_sample=0, end_sample=1000)
    arguments.update(changes)
    with pytest.raises(PitchEvidenceError):
        summarize_pitch_frames([PitchFrame(0, 1000, 440.0, 0.5)], **arguments)


def test_inputs_are_immutable_and_diagnostic_is_deterministic():
    frames = (PitchFrame(0, 500, 440.0, 0.5), PitchFrame(500, 1000, None, 0.1))
    result = describe(frames)
    assert result == describe(frames)
    assert frames[0] == PitchFrame(0, 500, 440.0, 0.5)
    assert result.longest_voiced_seconds == 0.5
    assert math.isfinite(result.mean_voiced_probability)
    assert result.voiced_fraction == 0.5
