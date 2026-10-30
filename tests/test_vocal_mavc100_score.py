"""Synthetic scores enforce source integrity and duration, not acoustic quality."""

import pytest

from app.vocal_mavc100_score import MAVCScoringError, combine_mavc_scores, score_mavc_clip

HEAD = "Name\tStart\tDuration\tTime Format\tType\tDescription\r\n"


def fixture(*rows):
    return (HEAD + "".join(f"{edge}\t0:{time}\t0:00.000\tdecimal\tCue\t\r\n"
                           for edge, time in rows)).encode("utf-8-sig")


def gold():
    return fixture(("1s", "00.000"), ("1e", "01.000"),
                   ("2s", "01.001"), ("2e", "02.500"),
                   ("1s", "02.501"), ("1e", "03.500"),
                   ("3s", "29.977"), ("3e", "30.030"))


def pred(kind, a, b):
    return {"label": kind, "start_sec": a, "end_sec": b}


def score(rows, **kwargs):
    return score_mavc_clip(rows, filename="Example_0.csv",
                           predictions=kwargs.pop("predictions", [pred("speech", 0, 1),
                                                                  pred("music", 1, 2),
                                                                  pred("speech", 2, 2.6)]),
                           sample_rate=kwargs.pop("sample_rate", 1000),
                           total_samples=kwargs.pop("total_samples", 30000), **kwargs)


def test_wrong_predicted_speech_on_singing_is_counted_in_frames():
    result = score(gold())
    assert result["gold_speech_samples"] == 1999
    assert result["gold_singing_samples"] == 1499
    assert result["gold_singing_predicted_speech_samples"] == 500
    assert result["singing_events_touched_by_predicted_speech"] == 1
    assert result["gold_speech_predicted_speech_samples"] == 1099
    assert result["clipped_published_silence_tail_samples"] == 30
    assert result["confusion"]["singing"]["music"] == 999


def test_48k_sample_weights_are_exact_integer_multiples_for_whole_ms_labels():
    result = score(gold(), sample_rate=48000, total_samples=1440000)
    assert result["gold_singing_predicted_speech_samples"] == 500 * 48
    assert result["clipped_published_silence_tail_samples"] == 30 * 48
    assert result["gold_speech_samples"] == 1999 * 48


def test_float_rounding_artifacts_preserve_frame_edges():
    result = score(gold(), predictions=[pred("speech", 0, 1.0000000000000002)])
    assert result["gold_speech_predicted_speech_samples"] == 1000


def test_unclassified_tail_remains_unclassified():
    result = score(gold(), predictions=[])
    assert result["confusion"]["singing"]["unclassified"] == 1499
    assert result["speech_detected_rate"] == 0


def test_missing_denominator_does_not_claim_full_recall():
    rows = fixture(("2s", "00.000"), ("2e", "02.000"))
    result = score(rows, predictions=[pred("music", 0, 2)])
    assert result["speech_detected_rate"] is None
    assert result["singing_predicted_music_rate"] == 1.0


def test_aggregate_is_sample_weighted_and_not_average_of_percentages():
    first = score(gold(), predictions=[pred("speech", 0, 1)])
    second = score(fixture(("1s", "00.000"), ("1e", "10.000")), predictions=[])
    overall = combine_mavc_scores([first, second])
    assert overall["gold_speech_samples"] == 11999
    assert overall["gold_speech_predicted_speech_samples"] == 1000
    assert overall["speech_detected_rate"] == round(1000 / 11999, 7)


def test_rejects_sung_event_outside_audio_clock():
    rows = fixture(("2s", "29.500"), ("2e", "30.030"))
    with pytest.raises(MAVCScoringError, match="voiced interval"):
        score(rows)


def test_rejects_silence_tail_beyond_50ms():
    rows = fixture(("3s", "29.950"), ("3e", "30.100"))
    with pytest.raises(MAVCScoringError, match="silence tail"):
        score(rows)


@pytest.mark.parametrize("bad", [
    [pred("music", 0, 1), pred("speech", 0.5, 2)],
    [pred("singing", 0, 2)],
    [pred("speech", 0, 30.01)],
    [pred("music", 1, 1)],
    [pred("speech", 0, float("nan"))],
    [pred("speech", 0, float("inf"))],
    [pred("speech", -1, 1)],
    [{"label": "music", "start_sec": 0, "end_sec": 1, "confidence": 0.9}],
])
def test_bad_model_predictions_rejected(bad):
    with pytest.raises(MAVCScoringError):
        score(gold(), predictions=bad)


@pytest.mark.parametrize("rate,total", [(0, 30000), (1000, 0), (True, 30000), (1000, True)])
def test_bad_pcm_clock_rejected(rate, total):
    with pytest.raises(MAVCScoringError):
        score(gold(), sample_rate=rate, total_samples=total)


def test_aggregate_requires_at_least_one_real_clip():
    with pytest.raises(MAVCScoringError, match="no clip"):
        combine_mavc_scores([])
