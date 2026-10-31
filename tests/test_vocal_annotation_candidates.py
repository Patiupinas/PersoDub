"""Model evidence can suggest intervals, but never create approved dubbing gold."""

import pytest

from app.vocal_annotation_candidates import (
    EventObservation,
    PreannotationError,
    suggest_annotation_candidates,
)


def ob(start, end, label):
    return EventObservation(start, end, label)


def score(*, smad, ina, words=(), sample_rate=1000, total=12000,
          offset=60000, review=1):
    return suggest_annotation_candidates(
        sample_rate=sample_rate,
        total_samples=total,
        source_offset_samples=offset,
        smad=smad,
        ina=ina,
        asr_words=words,
        boundary_review_seconds=review,
    )


def fixture():
    smad = [
        ob(i * 1000, (i + 1) * 1000,
           "speech_noise" if i < 4 or i >= 8 else "singing_music")
        for i in range(12)
    ]
    ina = [ob(0, 4000, "speech"), ob(4000, 8000, "music"),
           ob(8000, 12000, "speech")]
    words = [ob(0, 4000, "word"), ob(8000, 12000, "word")]
    return smad, ina, words


def test_clear_speech_demonstration_speech_and_transition_review():
    smad, ina, words = fixture()
    outcome = score(smad=smad, ina=ina, words=words)
    assert [(x.start_sample, x.end_sample, x.candidate) for x in outcome] == [
        (60000, 63000, "speech_candidate"),
        (63000, 65000, "uncertain"),
        (65000, 67000, "vocal_demo_candidate"),
        (67000, 69000, "uncertain"),
        (69000, 72000, "speech_candidate"),
    ]
    assert not any(hasattr(x, "action") for x in outcome)
    assert all(x.end_sample == y.start_sample for x, y in zip(outcome, outcome[1:]))


def test_asr_lyrics_do_not_make_singing_safe_to_translate():
    smad, ina, words = fixture()
    words = (*words, ob(5000, 7000, "sung_lyrics"))
    outcome = score(smad=smad, ina=ina, words=words)
    assert any(x.candidate == "vocal_demo_candidate" for x in outcome)
    assert not any(x.candidate == "speech_candidate"
                   and x.start_sample < 67000 and x.end_sample > 65000 for x in outcome)


def test_conflicting_speech_over_music_is_not_automatic_speech():
    smad, ina, words = fixture()
    smad[5] = ob(5000, 6000, "speech_music")
    outcome = score(smad=smad, ina=ina, words=words, review=0)
    assert any(x.candidate == "uncertain"
               and x.start_sample <= 65000 < x.end_sample for x in outcome)


def test_no_asr_words_prevents_unqualified_speech_candidates():
    smad, ina, _ = fixture()
    outcome = score(smad=smad, ina=ina)
    assert not any(x.candidate == "speech_candidate" for x in outcome)


def test_no_energy_and_no_voice_becomes_only_non_target_candidate():
    smad = [ob(i * 1000, (i + 1) * 1000, "none") for i in range(12)]
    outcome = score(smad=smad, ina=[ob(0, 12000, "noEnergy")])
    assert len(outcome) == 1 and outcome[0].candidate == "non_target_candidate"


def test_missing_ina_tail_is_uncertain_not_guessed_as_silence():
    smad = [ob(i * 1000, (i + 1) * 1000, "speech_noise") for i in range(12)]
    outcome = score(smad=smad, ina=[ob(0, 11980, "speech")],
                    words=[ob(0, 12000, "word")], review=0)
    assert outcome[-1].candidate == "uncertain"
    assert outcome[-1].end_sample == 72000


def test_untranslated_output_has_no_gold_schema_or_tts_action():
    smad, ina, words = fixture()
    first = score(smad=smad, ina=ina, words=words)
    second = score(smad=smad, ina=ina, words=words)
    assert first == second
    assert "source_text" not in first[0].__dataclass_fields__
    assert "event_type" not in first[0].__dataclass_fields__


@pytest.mark.parametrize(
    "changed",
    [
        {"sample_rate": 0}, {"sample_rate": True},
        {"sample_rate": 700}, {"total": 0},
        {"total": 13000}, {"total": False},
        {"offset": -1}, {"offset": True},
        {"review": -1}, {"review": True},
    ],
)
def test_invalid_source_clock_rejected(changed):
    smad, ina, words = fixture()
    with pytest.raises(PreannotationError):
        score(smad=smad, ina=ina, words=words, **changed)


@pytest.mark.parametrize(
    "bad",
    [
        [ob(0, 999, "speech_noise")] * 12,
        [ob(0, 12000, "speech_noise")],
        [ob(i * 1000, (i + 1) * 1000, "invalid") for i in range(12)],
        [ob(i * 1000, (i + 1) * 1000, "speech_noise") for i in range(11)],
        [ob(i * 1000, (i + 1) * 1000, "speech_noise") for i in range(12)][::-1],
    ],
)
def test_smad_timeline_must_be_complete_valid_and_one_second(bad):
    _, ina, words = fixture()
    with pytest.raises(PreannotationError):
        score(smad=bad, ina=ina, words=words)


def test_ina_must_not_contain_overlapping_intervals():
    smad, _, words = fixture()
    with pytest.raises(PreannotationError):
        score(smad=smad, ina=[ob(0, 5000, "speech"), ob(4900, 12000, "music")],
              words=words)


def test_ina_unknown_label_fails():
    smad, _, words = fixture()
    with pytest.raises(PreannotationError):
        score(smad=smad, ina=[ob(0, 12000, "singing")], words=words)
