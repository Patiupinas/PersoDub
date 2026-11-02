"""Real PCM invariants for the private unapproved lesson playback path."""
import wave

import numpy as np
import pytest

from benchmarks.persodub.research_full_preview import (
    read_source_pcm,
    splice_unapproved_pcm,
    write_pcm,
)


def _voice(path, frames=4800, level=6000):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(np.full(frames, level, dtype="<i2").tobytes())


def _manifest(cases):
    return {"reviewed_a4": False, "cases": cases}


def _case(label, start, limit, file):
    return {"id": label, "start": start, "slot_end": limit, "output_file": file}


def test_research_preview_preserves_exact_original_outside_voice(tmp_path):
    original = np.tile(np.array([[16000, -12000]], dtype="<i2"), (48000, 1))
    _voice(tmp_path / "voice.wav")
    mixed, mask, rows = splice_unapproved_pcm(original,
        _manifest([_case("v", 0.2, 0.4, "voice.wav")]), tmp_path, offset_s=0)
    assert mask.sum() == 4800
    assert np.array_equal(mixed[~mask], original[~mask])
    assert np.any(mixed[mask] != original[mask])
    assert rows[0]["source_authority"] == "UNREVIEWED_MODEL_AUTHORED_DRAFT"
    assert np.array_equal(original[~mask], np.tile([16000, -12000], (43200, 1)))
    out = tmp_path / "result.wav"
    write_pcm(out, mixed)
    assert np.array_equal(read_source_pcm(out), mixed)
    with pytest.raises(FileExistsError):
        write_pcm(out, mixed)


@pytest.mark.parametrize("cases", [
    [_case("a", 0.2, 0.25, "voice.wav")],
    [_case("a", 0.95, 1.1, "voice.wav")],
    [_case("a", 0.2, 0.8, "voice.wav"),
     _case("b", 0.23, 0.8, "voice.wav")],
])
def test_research_preview_rejects_outside_video_slot_or_overlaps(tmp_path, cases):
    _voice(tmp_path / "voice.wav")
    with pytest.raises(ValueError):
        splice_unapproved_pcm(np.zeros((48000, 2), dtype="<i2"),
                              _manifest(cases), tmp_path, offset_s=0)


def test_research_preview_rejects_fake_human_review_flag(tmp_path):
    _voice(tmp_path / "voice.wav")
    with pytest.raises(ValueError):
        splice_unapproved_pcm(np.zeros((48000, 2), dtype="<i2"),
                              {"reviewed_a4": True, "cases": [
                                  _case("a", 0.2, 0.8, "voice.wav")]},
                              tmp_path, offset_s=0)


def test_case_specific_offset_overrides_base_clip_offset(tmp_path):
    _voice(tmp_path / "line.wav")
    source = np.zeros((48000, 2), dtype="<i2")
    mixed, mask, _rows = splice_unapproved_pcm(
        source, _manifest([dict(_case("r", 0.2, 0.7, "line.wav"),
                                offset_s=0.0)]), tmp_path, offset_s=145.0)
    assert np.flatnonzero(mask)[0] == 9600
    assert len(mixed) == 48000


def test_legacy_early_voice_is_not_placed_before_original_speech(tmp_path):
    # Historic case d started at 168.36s despite original English at 169.36s.
    _voice(tmp_path / "d.wav", frames=1 * 48000)
    source = np.zeros((3 * 48000, 2), dtype="<i2")
    row = dict(_case("d", 0.36, 2.6, "d.wav"),
               source_start=1.36, source_end=2.6)
    mixed, mask, receipt = splice_unapproved_pcm(
        source, _manifest([row]), tmp_path, offset_s=0)
    assert np.flatnonzero(mask)[0] == round(1.36 * 48000)
    assert receipt[0]["start_frame"] == round(1.36 * 48000)
    assert np.array_equal(mixed[~mask], source[~mask])


def test_legacy_overlong_voice_is_rejected_on_actual_source_onset(tmp_path):
    _voice(tmp_path / "d.wav", frames=3 * 48000)
    source = np.zeros((4 * 48000, 2), dtype="<i2")
    row = dict(_case("d", 0.36, 2.6, "d.wav"),
               source_start=1.36, source_end=2.6)
    with pytest.raises(ValueError, match="exceeds source slot"):
        splice_unapproved_pcm(source, _manifest([row]), tmp_path, offset_s=0)
