"""Deterministic fixtures for the real Russian fixed-voice listening programme."""
from benchmarks.persodub.ru_voice_showcase import (
    RUSSIAN_CONTROL,
    VOICE_IDS,
    render_page,
)


def test_five_stable_speaker_ids_are_available_for_russian_voice_trials():
    assert len(VOICE_IDS) == len(set(VOICE_IDS)) == 5
    assert len(RUSSIAN_CONTROL) > 100


def test_offline_preview_escapes_script_data_and_has_five_audio_controls():
    entries = [{"voice": name, "wav": name + ".wav"} for name in VOICE_IDS]
    rendered = render_page(entries, "<script>alert('bad')</script>")
    assert rendered.count("<audio controls") == 5
    assert "<script>alert" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "https://" not in rendered
    assert all(name + ".wav" in rendered for name in VOICE_IDS)
