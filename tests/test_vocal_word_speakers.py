"""Conservative speaker/word reconciliation without WhisperNotes runtime."""

import pytest

from app.vocal_phrase_groups import SpeakerTurn
from app.vocal_word_speakers import TimedWord, align_word_speakers


def word(start, end, identifier="w1", text="hello", estimated=False):
    return TimedWord(identifier, start, end, text, estimated)


def turn(start, end, speaker="SPK0", source="model"):
    return SpeakerTurn(start, end, speaker, source)


def labels(words, turns, **kwargs):
    return align_word_speakers(words, turns, total_samples=10_000, **kwargs)


def test_one_speaker_and_two_nonoverlapping_words():
    result = labels([word(100, 200), word(300, 500, "w2", "world")], [turn(0, 600)])
    assert [(r.word.word_id, r.speaker_id, r.review_reasons) for r in result] == [
        ("w1", "SPK0", ()), ("w2", "SPK0", ())]


def test_two_speaker_words_split_without_fabricating_text():
    rows = [word(100, 200, "w1", "hello"), word(500, 600, "w2", "world")]
    result = labels(rows, [turn(0, 300, "SPK0"), turn(300, 800, "SPK1")])
    assert [r.speaker_id for r in result] == ["SPK0", "SPK1"]
    assert [r.word.text for r in result] == ["hello", "world"]
    assert [r.word.word_id for r in result] == ["w1", "w2"]


def test_one_word_crossing_two_speakers_is_not_split_or_attributed():
    result = labels([word(250, 350)], [turn(0, 300, "SPK0"), turn(300, 700, "SPK1")])
    assert result[0].speaker_id is None
    assert result[0].review_reasons == ("conflicting_speakers",)
    assert result[0].word.text == "hello"


def test_shorter_interjection_inside_longer_turn_is_review_not_guess():
    # WN prefers the shorter turn on a tie. Here speaker cross-talk is not resolved by duration.
    result = labels([word(250, 300)], [turn(0, 500, "SPK0"), turn(200, 350, "SPK1")])
    assert result[0].speaker_id is None
    assert result[0].needs_review
    assert result[0].review_reasons == ("conflicting_speakers",)


def test_even_one_sample_other_speaker_triggers_review():
    result = labels([word(100, 200)], [turn(100, 200, "SPK0"), turn(199, 210, "SPK1")])
    assert result[0].review_reasons == ("conflicting_speakers",)


def test_partial_coverage_marks_review_but_retains_dominant_speaker():
    result = labels([word(0, 100)], [turn(20, 100)])
    assert result[0].speaker_id == "SPK0"
    assert result[0].review_reasons == ("partial_speaker_coverage",)


def test_insufficient_coverage_does_not_claim_a_speaker():
    result = labels([word(0, 100)], [turn(70, 100)])
    assert result[0].speaker_id is None
    assert result[0].review_reasons == ("insufficient_speaker_coverage",)


def test_half_coverage_is_candidate_but_still_needs_review():
    result = labels([word(0, 100)], [turn(50, 100)])
    assert result[0].speaker_id == "SPK0"
    assert result[0].needs_review


def test_fallback_turn_is_not_speaker_evidence():
    result = labels([word(0, 100)], [turn(0, 100, source="fallback")])
    assert result[0].speaker_id is None
    assert result[0].review_reasons == ("no_speaker_evidence",)


def test_unknown_speaker_is_not_a_voice_identity():
    result = labels([word(0, 100)], [turn(0, 100, "UNKNOWN")])
    assert result[0].speaker_id is None
    assert result[0].review_reasons == ("unknown_speaker",)


def test_word_with_estimated_timing_is_not_approved():
    result = labels([word(0, 100, estimated=True)], [turn(0, 100)])
    assert result[0].speaker_id == "SPK0"
    assert result[0].review_reasons == ("estimated_word_timing",)


def test_overlapping_whisper_words_both_flagged():
    rows = [word(100, 300, "w1", "one"), word(200, 400, "w2", "two")]
    result = labels(rows, [turn(0, 500)])
    assert [r.speaker_id for r in result] == ["SPK0", "SPK0"]
    assert all("overlapping_asr_words" in r.review_reasons for r in result)


def test_long_word_overlaps_two_shorter_words_both_detected():
    rows = [word(0, 300, "w1"), word(10, 20, "w2"), word(40, 50, "w3")]
    result = labels(rows, [turn(0, 300)])
    assert all("overlapping_asr_words" in r.review_reasons for r in result)


def test_adjacent_words_do_not_count_as_overlap():
    result = labels([word(0, 100, "w1"), word(100, 200, "w2")], [turn(0, 200)])
    assert all(not r.needs_review for r in result)


def test_same_speaker_overlapping_turns_count_union_only():
    # Summed coverage would exceed the duration, masking missing evidence.
    result = labels([word(0, 100)], [turn(0, 40), turn(20, 60)])
    assert result[0].speaker_id == "SPK0"
    assert result[0].review_reasons == ("partial_speaker_coverage",)


def test_disjoint_turns_same_speaker_cover_full_word():
    result = labels([word(0, 100)], [turn(0, 50), turn(50, 100)])
    assert result[0].speaker_id == "SPK0"
    assert not result[0].needs_review


def test_returns_sorted_copy_without_modifying_input():
    rows = [word(500, 600, "w2"), word(100, 200, "w1")]
    original = list(rows)
    result = labels(rows, [turn(0, 1000)])
    assert [r.word.word_id for r in result] == ["w1", "w2"]
    assert rows == original


def test_no_words_returns_empty_without_hallucination():
    assert labels([], [turn(0, 100)]) == []


def test_no_turns_yields_review_for_every_word():
    result = labels([word(0, 100)], [])
    assert result[0].speaker_id is None
    assert result[0].review_reasons == ("no_speaker_evidence",)


def test_beyond_float_integer_limit_remains_exact():
    b = 2**53 + 35
    result = align_word_speakers([word(b, b + 50)], [turn(b, b + 50)], total_samples=b + 100)
    assert result[0].word.start_sample == b
    assert result[0].speaker_id == "SPK0"


def test_multiple_reasons_are_not_lost():
    result = labels([word(0, 100, estimated=True)], [turn(80, 100)])
    assert result[0].review_reasons == ("insufficient_speaker_coverage", "estimated_word_timing")


@pytest.mark.parametrize("field,value", [
    ("total_samples", 0), ("total_samples", 1.5), ("total_samples", True),
    ("min_overlap_samples", 0), ("min_overlap_samples", -2), ("min_overlap_samples", 2.5),
])
def test_rejects_invalid_configuration(field, value):
    opts = {"total_samples": 1000, "min_overlap_samples": 1}
    opts[field] = value
    with pytest.raises(ValueError):
        align_word_speakers([word(0, 100)], [turn(0, 100)], **opts)


@pytest.mark.parametrize("bad", [
    word(-1, 10), word(20, 20), word(20, 10), word(0, 10001),
    word(0, 10, ""), word(0, 10, "bad", " "),
    word(True, 10), word(0.0, 10), word(0, 10.5),
    TimedWord("w1", 0, 10, "text", is_estimated="no"), object(),
])
def test_rejects_invalid_words(bad):
    with pytest.raises((ValueError, TypeError)):
        labels([bad], [turn(0, 100)])


def test_rejects_duplicate_word_ids():
    with pytest.raises(ValueError, match="word_id"):
        labels([word(0, 10, "w1"), word(100, 200, "w1")], [turn(0, 200)])


@pytest.mark.parametrize("bad", [
    turn(-1, 10), turn(10, 10), turn(0, 10001), turn(0, 10, ""),
    turn(0, 10, " "), turn(0, 10.1), turn(0, True), object(),
])
def test_rejects_invalid_turns(bad):
    with pytest.raises((ValueError, TypeError)):
        labels([word(0, 10)], [bad])


def test_min_overlap_is_respected_without_losing_timestamps():
    result = labels([word(0, 100)], [turn(0, 100)], min_overlap_samples=101)
    assert result[0].speaker_id is None
    assert result[0].review_reasons == ("insufficient_speaker_coverage",)


def test_large_nonoverlapping_batch_preserves_all_word_ids():
    words = [word(i * 20, i * 20 + 10, f"w{i}", str(i)) for i in range(400)]
    result = labels(words, [turn(0, 10000)])
    assert len(result) == len(words)
    assert all(not r.needs_review for r in result)

def test_reordering_source_turns_does_not_change_attribution():
    turns = [turn(300, 600, "SPK1"), turn(0, 300, "SPK0")]
    words = [word(50, 150, "w0"), word(350, 450, "w1")]
    assert labels(words, turns) == labels(words, list(reversed(turns)))


def test_speaker_boundary_is_half_open_not_shared_at_exact_end():
    words = [word(0, 100, "left"), word(100, 200, "right")]
    turns = [turn(0, 100, "SPK0"), turn(100, 200, "SPK1")]
    out = labels(words, turns)
    assert [item.speaker_id for item in out] == ["SPK0", "SPK1"]
    assert all(not item.needs_review for item in out)
