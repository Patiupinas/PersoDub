"""Experimental S2ST video preview preserves selectable original audio."""
import json
import math
import shutil
import struct
import subprocess
import wave

import pytest

from app.experimental.s2st_preview import render


@pytest.fixture
def media(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg required")
    source = tmp_path / "english.mp4"
    rus = tmp_path / "russian.wav"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=blue:s=120x80:r=12:d=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(source)],
        capture_output=True, check=True, timeout=50,
    )
    with wave.open(str(rus), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        samples = (struct.pack("<h", int(7000 * math.sin(i * math.pi * 2 * 880 / 16000)))
                   for i in range(16000 * 2))
        output.writeframes(b"".join(samples))
    return source, rus


def test_two_tracks_original_preserved_and_translation_padded(media, tmp_path):
    source, ru = media
    output = tmp_path / "overdub.mp4"
    receipt = render(source, ru, 0, 3, output)
    assert receipt["status"] == "experimental_speech_clip_overdub"
    assert output.is_file()
    assert receipt["translated_duration_s"] == 2.0
    assert receipt["tracks"] == ["Overdub", "Original"]
    assert receipt["record"]["action_frames"]["PRESERVE"] > 0
    assert receipt["record"]["action_frames"]["TRANSLATE"] > 0
    assert receipt["needs_listening_review"] is True
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "json", str(output)],
        capture_output=True, text=True, check=True,
    )
    streams = json.loads(probe.stdout)["streams"]
    assert sum(s["codec_type"] == "audio" for s in streams) == 2
    assert sum(s["codec_type"] == "video" for s in streams) == 1
    assert not list(tmp_path.glob("persodub-s2st-preview-*"))


def test_refuses_to_truncate_translated_speech_or_replace_existing(media, tmp_path):
    source, ru = media
    out = tmp_path / "rejected.mp4"
    with pytest.raises(ValueError, match="cannot auto-place"):
        render(source, ru, 0, 1.0, out)
    assert not out.exists()
    with pytest.raises(ValueError, match="new"):
        render(source, ru, 0, 3.0, source)
    assert source.exists()


def test_rejects_out_of_bounds_and_invalid_timestamps(media, tmp_path):
    source, ru = media
    out = tmp_path / "outside.mp4"
    with pytest.raises(ValueError, match="outside original"):
        render(source, ru, 200, 203, out)
    with pytest.raises(ValueError, match="Non-finite"):
        render(source, ru, float("nan"), 3, out)
    with pytest.raises(ValueError, match="bounded"):
        render(source, ru, 0, 34, out)



def test_short_source_too_ambiguous_even_when_tts_fits(media, tmp_path):
    source, ru = media
    shortened = tmp_path / "short_ru.wav"
    with wave.open(str(shortened), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\x00\x00" * 8000)
    with pytest.raises(ValueError, match="short_source_needs"):
        render(source, shortened, 0, 1.2, tmp_path / "unreviewed.mp4")
