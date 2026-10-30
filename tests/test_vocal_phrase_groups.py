"""Reference parity and source-sample invariants for speaker phrase grouping."""

import pytest

from app.vocal_phrase_groups import PhraseGroup, SpeakerTurn, build_phrase_groups

SR = 1000


def turn(start, end, speaker="SPEAKER_00", source=""):
    return SpeakerTurn(start, end, speaker, source)


def test_whispernotes_reference_three_turn_fixture():
    # Matches SessionPipelineV2Tests.phraseBuilderMergesSameSpeakerTurns.
    rows = [turn(0, 2000), turn(2500, 5000), turn(6000, 8000, "SPEAKER_01")]
    assert build_phrase_groups(rows, sample_rate=SR) == [
        PhraseGroup("phrase_001", "SPEAKER_00", 0, 5000),
        PhraseGroup("phrase_002", "SPEAKER_01", 6000, 8000),
    ]


def test_default_gap_includes_exactly_ten_seconds_but_not_one_more_sample():
    merged = build_phrase_groups([turn(0, 1000), turn(11000, 12000)], sample_rate=SR)
    separate = build_phrase_groups([turn(0, 1000), turn(11001, 12000)], sample_rate=SR)
    assert [(p.start_sample, p.end_sample) for p in merged] == [(0, 12000)]
    assert [(p.start_sample, p.end_sample) for p in separate] == [(0, 1000), (11001, 12000)]


def test_gap_can_be_disabled_for_speech_only_context():
    rows = [turn(0, 1000), turn(1001, 2000)]
    assert len(build_phrase_groups(rows, sample_rate=SR, merge_gap_samples=0)) == 2
    assert len(build_phrase_groups(rows, sample_rate=SR)) == 1


def test_speaker_switch_blocks_merge_even_when_intervals_overlap():
    rows = [turn(0, 3000, "A"), turn(1000, 2000, "B"), turn(2800, 3600, "A")]
    groups = build_phrase_groups(rows, sample_rate=SR)
    assert [(p.speaker_id, p.start_sample, p.end_sample) for p in groups] == [
        ("A", 0, 3000), ("B", 1000, 2000), ("A", 2800, 3600)
    ]


def test_filters_fallback_and_nonpositive_duration_like_reference():
    rows = [turn(0, 1000, source="fallback"), turn(2000, 2000), turn(5000, 4500), turn(6000, 7000)]
    assert build_phrase_groups(rows, sample_rate=SR) == [PhraseGroup("phrase_001", "SPEAKER_00", 6000, 7000)]
    assert build_phrase_groups([turn(0, 1000, source="fallback")], sample_rate=SR) == []


def test_sorted_before_grouping_without_mutating_input():
    rows = [turn(2000, 3000, "B"), turn(0, 1000, "A"), turn(4000, 6000, "B")]
    original = list(rows)
    groups = build_phrase_groups(rows, sample_rate=SR)
    assert rows == original
    assert [(p.phrase_id, p.speaker_id) for p in groups] == [
        ("phrase_001", "A"), ("phrase_002", "B")
    ]


def test_exactly_45_seconds_remains_one_group():
    groups = build_phrase_groups([turn(0, 45000)], sample_rate=SR)
    assert groups == [PhraseGroup("phrase_001", "SPEAKER_00", 0, 45000)]


def test_long_turn_splits_at_integer_samples_and_names_each_part():
    groups = build_phrase_groups([turn(250, 100250)], sample_rate=SR)
    assert groups == [
        PhraseGroup("phrase_001_1", "SPEAKER_00", 250, 45250),
        PhraseGroup("phrase_001_2", "SPEAKER_00", 45250, 90250),
        PhraseGroup("phrase_001_3", "SPEAKER_00", 90250, 100250),
    ]


def test_large_sample_offsets_remain_integer_exact():
    base = 2**53 + 17
    groups = build_phrase_groups([turn(base, base + 7)], sample_rate=SR, max_phrase_samples=3)
    assert [(p.start_sample, p.end_sample) for p in groups] == [
        (base, base + 3), (base + 3, base + 6), (base + 6, base + 7)
    ]


def test_unknown_speaker_is_retained_without_making_up_identity():
    assert build_phrase_groups([turn(0, 3000, "UNKNOWN")], sample_rate=SR) == [
        PhraseGroup("phrase_001", "UNKNOWN", 0, 3000)
    ]


@pytest.mark.parametrize("kwargs", [
    {"sample_rate": 0}, {"sample_rate": True}, {"sample_rate": 1000.0},
    {"sample_rate": SR, "merge_gap_samples": -1},
    {"sample_rate": SR, "merge_gap_samples": 2.0},
    {"sample_rate": SR, "max_phrase_samples": 0},
    {"sample_rate": SR, "max_phrase_samples": False},
])
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        build_phrase_groups([turn(0, 1000)], **kwargs)


@pytest.mark.parametrize("rows", [
    [turn(-1, 100)], [turn(0.5, 10)], [turn(0, 10.1)],
    [turn(0, 100, "")], [turn(0, 100, " ")], [object()],
])
def test_invalid_turn_is_rejected(rows):
    with pytest.raises((TypeError, ValueError)):
        build_phrase_groups(rows, sample_rate=SR)


def test_phrase_does_not_grant_translate_permission():
    # A six-second gap can contain a protected vocal demo. A2/A4 still decide.
    rows = [turn(0, 1000), turn(7000, 8000)]
    assert build_phrase_groups(rows, sample_rate=SR) == [
        PhraseGroup("phrase_001", "SPEAKER_00", 0, 8000)
    ]
