"""Verify the real cached Whisper pilot metadata without lyrics or media."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "docs"
PILOT = ROOT / "vocal-whisper-pitch-pilot" / "whisper-word-overlap.json"
PCM = ROOT / "vocal-mavc100-pilot" / "pcm-provenance.json"


def test_real_whisper_words_can_overlap_gold_singing():
    data = json.loads(PILOT.read_text(encoding="utf-8"))
    aggregate = data["aggregate"]
    assert data["model"] == "openai/whisper-small"
    assert data["model_checkpoint_sha256"] == (
        "9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794"
    )
    assert aggregate["clips"] == 3
    assert aggregate["word_intervals"] == 283
    assert aggregate["word_intervals_touching_singing"] == 93
    assert aggregate["overlapping_singing_seconds"] == 29.689
    assert aggregate["word_intervals_touching_speech"] == 74
    assert aggregate["overlapping_speech_seconds"] == 18.817
    assert sum(row["word_intervals"] for row in data["clips"]) == aggregate["word_intervals"]


def test_original_video_shas_and_source_disjointness_match_frozen_pcm_pilot():
    data = json.loads(PILOT.read_text(encoding="utf-8"))
    pcm = json.loads(PCM.read_text(encoding="utf-8"))
    expected = {record["clip_id"]: record["source_mp4_sha256"] for record in pcm}
    actual = {record["clip_id"]: record["source_sha256"] for record in data["clips"]}
    assert len(actual) == len(expected) == 3
    assert actual == expected
    assert set(data["clips"][0]) == {
        "clip_id", "source_sha256", "language", "segment_count", "word_intervals",
        "runtime_seconds", "overlap_with_MAVC100_labels",
    }
    for row in data["clips"]:
        assert row["language"] == "en"
        assert row["word_intervals"] > 0
        assert "transcript" not in row
        assert "words" not in row
        assert "lyrics" not in row
        assert set(row["overlap_with_MAVC100_labels"]) == {"speech", "singing", "silence"}
        assert all(record["word_intervals"] >= 0
                   for record in row["overlap_with_MAVC100_labels"].values())
