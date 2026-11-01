"""Contracts for read-only, source-audio Whisper cross-check."""
import csv
import hashlib

import pytest

from benchmarks.persodub.source_asr_crosscheck import (
    crosscheck,
    ordered_reference_coverage,
    read_review_rows,
)


def _make_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "start_s", "end_s", "source_cues", "english_asr",
            "russian_translation",
        ])
        writer.writeheader()
        writer.writerows(rows)
    return path


def _row(start="4", end="7", text="Please sing three notes.",
         translated="Пожалуйста, спой три ноты."):
    return {
        "start_s": start,
        "end_s": end,
        "source_cues": "2",
        "english_asr": text,
        "russian_translation": translated,
    }


def test_independent_audio_check_never_claims_wer_or_gold(tmp_path):
    media = tmp_path / "input.mp4"
    media.write_bytes(b"source bytes retained")
    source = _make_csv(tmp_path / "review.csv", [_row()])
    media_sha = hashlib.sha256(media.read_bytes()).hexdigest()
    inputs = []

    def fake_decode(path, start, duration):
        inputs.append((path, start, duration))
        return [0.1, 0.2, 0.3]

    result = crosscheck(
        media, source,
        transcriber=lambda waveform: "And please sing three notes, now.",
        decoder=fake_decode,
        model_metadata={"method": "fake"},
    )

    assert len(inputs) == 1
    assert inputs[0][0] == media.resolve()
    assert inputs[0][1] == pytest.approx(2.2)
    assert inputs[0][2] == pytest.approx(6.6)
    assert result["source"]["media_sha256"] == media_sha
    assert result["crosscheck_asr"]["method"] == "fake"
    assert result["independent_ground_truth"] is False
    assert result["status"] == "OBSERVED"
    assert result["method"]["verified_translation"] is False
    assert result["rows"][0]["ordered_source_word_coverage"] == 1.0
    assert result["rows"][0]["human_transcript_verified"] is False
    assert result["rows"][0]["human_translation_verified"] is False
    assert media.read_bytes() == b"source bytes retained"


def test_very_fast_source_cue_is_flagged_but_not_rejected(tmp_path):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"media")
    review = _make_csv(tmp_path / "review.csv", [_row(
        "145.64", "146.72",
        "sing each note steadily and keep your shoulders loose while breathing "
        "and continue practicing until your voice feels relaxed and clear",
        "Пой мягко и ровно.",
    )])
    report = crosscheck(
        media, review,
        transcriber=lambda waveform: "Try to relax your muscles.",
        decoder=lambda *args: [0.0],
    )
    line = report["rows"][0]
    assert line["original_cue_words_per_second"] > 6.0
    assert "original_cue_timing_review" in line["diagnostic_flags"]


def test_short_initial_window_is_clamped_and_empty_asr_flagged(tmp_path):
    media = tmp_path / "input.mp4"
    media.write_bytes(b"mp4")
    review = _make_csv(tmp_path / "input.csv", [_row("0.3", "1.0")])
    decoded = []
    report = crosscheck(
        media, review,
        transcriber=lambda waveform: "",
        decoder=lambda path, start, duration: (
            decoded.append((start, duration)) or [0.0]
        ),
    )
    assert decoded == [(0.0, 2.8)]
    assert report["summary"]["reviewed_intervals"] == 1
    assert "independent_asr_empty" in report["rows"][0]["diagnostic_flags"]


def test_ordered_lexical_coverage_is_not_wer():
    assert ordered_reference_coverage(
        "Sing slowly three notes.",
        "Right. Sing slowly three notes. Okay."
    ) == 1.0
    assert ordered_reference_coverage("Sing three notes.", "Sing softly.") < 1
    assert ordered_reference_coverage("", "words") is None


@pytest.mark.parametrize("rows", [
    [],
    [_row("3", "3")],
    [_row("9", "2")],
    [_row("-1", "2")],
    [_row("nan", "2")],
    [_row("2", "100")],
    [_row(), _row("1", "2")],
    [_row(text="")],
    [_row(translated="")],
])
def test_bad_review_csv_is_rejected(tmp_path, rows):
    path = _make_csv(tmp_path / "input.csv", rows)
    with pytest.raises(ValueError):
        read_review_rows(path)


def test_padding_range_and_missing_files_are_rejected(tmp_path):
    media = tmp_path / "source.mp4"
    review = _make_csv(tmp_path / "input.csv", [_row()])
    with pytest.raises(ValueError, match="both exist"):
        crosscheck(media, review, transcriber=lambda _: "hi")
    media.write_bytes(b"mp4")
    with pytest.raises(ValueError, match="Padding"):
        crosscheck(media, review, transcriber=lambda _: "hi", padding=-1)
    with pytest.raises(ValueError, match="Padding"):
        crosscheck(media, review, transcriber=lambda _: "hi", padding=7)
