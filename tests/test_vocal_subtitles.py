"""Selective subtitle generation reuses PersoDub SRT and ASS builders."""

import pytest

from app.text.srt import parse_srt
from app.vocal_subtitles import build_subtitle_tracks


def segment(name, start, end, action, source="", ru=""):
    return {"id": name, "start_sample": start, "end_sample": end, "action": action,
            "source_text": source, "ru_text": ru}


def render(items):
    return build_subtitle_tracks(items, sample_rate=48000, width=1920, height=1080)


def test_source_russian_and_bilingual_are_switchable_and_aligned():
    result = render([
        segment("en1", 0, 48000, "TRANSLATE", "Hello", "Привет"),
        segment("vocal", 48000, 72000, "PRESERVE", "Aaaaa", "Аааа"),
        segment("review", 72000, 96000, "REVIEW", "hmm", "хм"),
        segment("de2", 96000, 144000, "TRANSLATE", "Guten Morgen", "Доброе утро"),
    ])
    source_cues = parse_srt(result["source_srt"])
    ru_cues = parse_srt(result["russian_srt"])
    assert [c["text"] for c in source_cues] == ["Hello", "Guten Morgen"]
    assert [c["text"] for c in ru_cues] == ["Привет", "Доброе утро"]
    assert [(c["start"], c["end"]) for c in ru_cues] == [(0.0, 1.0), (2.0, 3.0)]
    assert "Hello\\NПривет" in result["bilingual_ass"]
    assert "Guten Morgen\\NДоброе утро" in result["bilingual_ass"]
    assert "Aaaaa" not in result["source_srt"]
    assert result["translated_cues"] == 2 and result["protected_cues_skipped"] == 2


def test_fails_on_missing_translation_and_overlapping_cues():
    with pytest.raises(ValueError, match="both subtitle texts"):
        render([segment("bad", 0, 48000, "TRANSLATE", "Hello", "")])
    with pytest.raises(ValueError, match="overlap"):
        render([segment("1", 0, 96000, "TRANSLATE", "Hello", "Привет"),
                segment("2", 48000, 144000, "TRANSLATE", "World", "Мир")])


def test_rejects_ambiguous_action_and_invalid_subtitle_markup():
    with pytest.raises(ValueError, match="resolved leaf actions"):
        render([segment("amb", 0, 48000, "MIXED")])
    with pytest.raises(ValueError, match="time-arrow"):
        render([segment("bad", 0, 48000, "TRANSLATE", "abc --> def", "Текст")])
    with pytest.raises(ValueError, match="unique id"):
        render([segment("1", 0, 48000, "REVIEW"), segment("1", 48000, 96000, "PRESERVE")])


def test_all_protected_is_not_counted_as_translated():
    result = render([segment("only", 0, 48000, "PRESERVE")])
    assert parse_srt(result["source_srt"]) == []
    assert result["translated_cues"] == 0
    assert result["protected_cues_skipped"] == 1
