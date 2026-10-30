"""Whisper/CAM++ source-clock projection tests, without loading inference models."""

from copy import deepcopy

import pytest

from app.vocal_local_observations import LocalCueProjectionError, normalize_local_whisper_cues


def cue(start=0.1, end=0.2, text="Hello world", speaker="SPK0", words=None):
    row = {"start": start, "end": end, "text": text, "speaker": speaker}
    if words is not None:
        row["words"] = words
    return row


def word(start=0.1, end=0.2, literal=" Hello world", **extra):
    return {"start": start, "end": end, "word": literal, **extra}


def project(rows, **changes):
    args = {
        "source_language": "en",
        "sample_rate": 48000,
        "total_samples": 480000,
        "source_offset_samples": 0,
    }
    args.update(changes)
    return normalize_local_whisper_cues(rows, **args)


def test_actual_worker_cue_format_with_campplus_label():
    rows = [cue(
        start=0.1, end=0.4,
        words=[word(0.1, 0.2, " Hello"), word(0.2, 0.4, " world")],
    )]
    frozen = deepcopy(rows)
    result = project(rows)
    assert rows == frozen
    assert len(result) == 1
    item = result[0]
    assert (item.cue_id, item.start_sample, item.end_sample) == ("cue_000001", 4800, 19200)
    assert item.speaker_candidate == "SPK0"
    assert item.speaker_evidence == "campplus_asr_cue"
    assert item.review_reasons == ("cue_level_speaker_not_independent",)
    assert [(w.word_id, w.start_sample, w.end_sample, w.text) for w in item.words] == [
        ("w_000001_0001", 4800, 9600, " Hello"),
        ("w_000001_0002", 9600, 19200, " world"),
    ]


def test_missing_campplus_is_not_fabricated_speaker():
    row = cue(text="hello")
    del row["speaker"]
    result = project([row])
    assert result[0].speaker_candidate is None
    assert result[0].speaker_evidence == "none"
    assert "no_speaker_evidence" in result[0].review_reasons


def test_whisper_sentence_split_without_word_payload_needs_review():
    result = project([cue(start=0, end=2, text="A phrase with no words")])
    assert result[0].words == ()
    assert "word_timestamps_unavailable" in result[0].review_reasons


def test_empty_input_does_not_mean_silence_or_speech():
    assert project([]) == ()


def test_source_offset_is_explicit_and_integer_exact():
    base = 2**53 + 37
    result = project([cue(start=0.001, end=0.002, words=[word(0.001, 0.002, " Hello world")])],
                     sample_rate=48000, source_offset_samples=base, total_samples=base + 1000)
    assert result[0].start_sample == base + 48
    assert result[0].end_sample == base + 96
    assert result[0].words[0].start_sample == base + 48


def test_44100_hz_quantization_never_rounds_away_edges():
    result = project([cue(start=0.001, end=0.002)], sample_rate=44100)
    assert (result[0].start_sample, result[0].end_sample) == (44, 89)


def test_1ms_at_8khz_exact_samples():
    result = project([cue(start=0.001, end=0.002)], sample_rate=8000)
    assert (result[0].start_sample, result[0].end_sample) == (8, 16)


def test_worker_sample_timestamps_are_global_within_input_excerpt():
    rows = [cue(start=5.0, end=6.0, words=[word(5.2, 5.5, " Hello world")])]
    result = project(rows, total_samples=1000000, source_offset_samples=1000)
    assert result[0].start_sample == 241000
    assert result[0].words[0].start_sample == 250600


def test_word_text_mismatch_is_not_repaired_by_interpolation():
    result = project([cue(text="hello world", words=[word(0.1, 0.2, "hello")])])
    assert "word_text_mismatch" in result[0].review_reasons
    assert len(result[0].words) == 1
    assert result[0].words[0].text == "hello"


def test_word_with_explicit_estimation_is_reviewed():
    rows = [cue(words=[word(0.1, 0.2, " Hello world", is_estimated=True)])]
    result = project(rows)
    assert result[0].words[0].is_estimated
    assert "estimated_word_timing" in result[0].review_reasons


def test_provider_word_times_without_estimated_flag_are_observations_not_gold():
    rows = [cue(words=[word(0.1, 0.2, " Hello world")])]
    result = project(rows)
    assert not result[0].words[0].is_estimated
    assert result[0].speaker_evidence == "campplus_asr_cue"
    assert result[0].needs_review


def test_overlap_words_are_preserved_and_marked():
    rows = [cue(text="one two", words=[word(0.1, 0.18, "one"), word(0.17, 0.2, " two")])]
    result = project(rows)
    assert "overlapping_word_timestamps" in result[0].review_reasons
    assert len(result[0].words) == 2


def test_cross_cue_overlap_flags_both_without_dropping_text():
    rows = [cue(0.2, 0.5, "second", "SPK1"), cue(0.1, 0.3, "first", "SPK0")]
    copied = deepcopy(rows)
    result = project(rows)
    assert rows == copied
    assert [x.text for x in result] == ["first", "second"]
    assert [x.cue_id for x in result] == ["cue_000002", "cue_000001"]
    assert all("overlapping_asr_cues" in x.review_reasons for x in result)


def test_nested_cue_overlaps_mark_every_intersecting_one():
    rows = [cue(0, 0.5, "long"), cue(0.1, 0.2, "inside"),
            cue(0.3, 0.4, "also inside")]
    out = project(rows)
    assert all("overlapping_asr_cues" in x.review_reasons for x in out)


def test_touching_half_open_cues_do_not_overlap():
    result = project([cue(0, 0.1), cue(0.1, 0.2)])
    assert all("overlapping_asr_cues" not in x.review_reasons for x in result)


def test_future_spanish_and_unknown_language_are_observable_not_approved():
    for language in ("es", "und"):
        result = project([cue()], source_language=language)
        assert result[0].source_language == language
        assert "language_not_approved_for_v1_translation" in result[0].review_reasons


@pytest.mark.parametrize("language", ["ru", "", "FR", None, 1])
def test_invalid_language_is_rejected(language):
    with pytest.raises(LocalCueProjectionError):
        project([cue()], source_language=language)


@pytest.mark.parametrize("settings", [
    {"sample_rate": 0}, {"sample_rate": True}, {"sample_rate": 44100.0},
    {"total_samples": 0}, {"total_samples": False},
    {"source_offset_samples": -1}, {"source_offset_samples": 480000},
    {"source_offset_samples": 0.0},
])
def test_invalid_clock_is_rejected(settings):
    with pytest.raises(LocalCueProjectionError):
        project([cue()], **settings)


@pytest.mark.parametrize("start,end", [
    (-0.001, 0.2), (0.2, 0.2), (0.3, 0.2), (0.1, float("nan")),
    (0.1, float("inf")), (True, 0.2), ("0.1", 0.2),
    (0.0005, 0.2), (0.1, 0.20001),
])
def test_malformed_raw_timing_is_not_guessed(start, end):
    with pytest.raises(LocalCueProjectionError):
        project([cue(start=start, end=end)])


def test_end_beyond_total_is_not_silently_clipped():
    with pytest.raises(LocalCueProjectionError, match="outside source PCM"):
        project([cue(0.1, 11.0)], total_samples=480000)


def test_word_outside_clamped_parent_is_rejected():
    with pytest.raises(LocalCueProjectionError, match="outside parent cue"):
        project([cue(0, 0.2, words=[word(0.1, 0.3)])])


@pytest.mark.parametrize("bad", [
    {"start": 0.1, "end": 0.2},
    {"start": 0.1, "end": 0.2, "text": "abc", "speaker_id": "SPK0"},
    {"start": 0.1, "end": 0.2, "text": "abc", "speaker": ""},
    {"start": 0.1, "end": 0.2, "text": ""},
    {"start": 0.1, "end": 0.2, "text": "abc", "words": None},
    3,
])
def test_bad_cues_are_rejected(bad):
    with pytest.raises(LocalCueProjectionError):
        project([bad])


@pytest.mark.parametrize("bad", [
    {"start": 0.1, "end": 0.2},
    {"start": 0.1, "end": 0.2, "word": ""},
    {"start": 0.1, "end": 0.2, "word": " hi", "confidence": 0.9},
    {"start": 0.1, "end": 0.2, "word": " hi", "is_estimated": 1},
    {"start": 0.1, "end": 0.1, "word": " hi"},
    {"start": 0.19, "end": 0.21, "word": " hi"},
    {"start": 0.09, "end": 0.19, "word": " hi"},
])
def test_bad_word_timing_is_rejected(bad):
    with pytest.raises(LocalCueProjectionError):
        project([cue(words=[bad])])


def test_nonsequence_cues_are_rejected():
    with pytest.raises(LocalCueProjectionError):
        project({"start": 0, "end": 0.1})


def test_no_second_rounding_or_speaker_confidence_is_fabricated():
    result = project([cue(words=[word(0.1, 0.2, " Hello world")])])
    assert result[0].words[0].start_sample == 4800
    assert not hasattr(result[0], "speaker_confidence")
    assert not hasattr(result[0], "action")
