"""Subtitle QA uses only explicitly unapproved research clip metadata."""

import pytest

from benchmarks.persodub.research_subtitle_mux import draft_russian_cues


def _base():
    return {"cases": [{
        "id": "a", "start": 0.2, "slot_end": 5.0,
        "audio_duration": 1.92, "text": "Пример", "a4_reviewed": False,
    }]}


def test_source_offset_and_actual_voice_length_are_preserved():
    assert draft_russian_cues(_base()) == [
        {"start": 145.2, "end": 147.11999999999998, "text": "Пример"},
    ]


def test_extra_fitting_speech_is_sorted_and_overruns_are_omitted():
    extra = {"status": "OBSERVED_UNREVIEWED_TTS_RESEARCH", "files": [
        {"id": "r3", "start": 200.0, "slot_end": 202.0,
         "duration_seconds": 1.0, "text": "Позже",
         "human_a4_approved": False, "status": "FITS_SOURCE_SLOT_UNREVIEWED"},
        {"id": "r1", "start": 0.0, "slot_end": 2.0,
         "duration_seconds": 3.0, "text": "Не поместилось",
         "human_a4_approved": False, "status": "OVERRUN_NOT_USED"},
        {"id": "r2", "start": 3.0, "slot_end": 6.0,
         "duration_seconds": 2.0, "text": "Раньше",
         "human_a4_approved": False, "status": "FITS_SOURCE_SLOT_UNREVIEWED"},
    ]}
    assert [row["text"] for row in draft_russian_cues(_base(), extra)] == [
        "Раньше", "Пример", "Позже",
    ]


def test_synthetic_review_approval_cannot_replace_source_authority():
    bad = _base()
    bad["cases"][0]["a4_reviewed"] = True
    with pytest.raises(ValueError):
        draft_russian_cues(bad)
