"""Unit and real-FFmpeg smoke checks for the independent MKV export module."""

import math
import shutil
import struct
import subprocess
import wave

import pytest

from app.vocal_mkv import build_master, inspect_master


HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def write_pcm(path, *, change_intro=False):
    frames = bytearray()
    for n in range(48000 * 2):
        sample = int(12000 * math.sin(2 * math.pi * (440 if change_intro and n < 48000 else 220) * n / 48000))
        frames.extend(struct.pack("<hh", sample, sample))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(frames)
    return bytes(frames)


def decoded_pcm(path, index):
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-i", str(path),
                           "-map", f"0:a:{index}", "-f", "s16le", "-c:a", "pcm_s16le", "-"],
                          capture_output=True, check=True)
    return proc.stdout


def srt(path, text):
    path.write_text(f"1\n00:00:00,000 --> 00:00:01,500\n{text}\n", encoding="utf-8")


def make_inputs(tmp_path):
    original = tmp_path / "original.wav"
    dubbed = tmp_path / "ru.wav"
    original_bytes = write_pcm(original)
    dubbed_bytes = write_pcm(dubbed, change_intro=True)
    video = tmp_path / "lecture.mkv"
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=160x120:r=25:d=2", "-i", str(original),
                    "-c:v", "mpeg4", "-c:a", "flac", "-map", "0:v:0", "-map", "1:a:0",
                    str(video)], capture_output=True, check=True)
    original_srt, ru_srt, dual = (tmp_path / x for x in ("de.srt", "ru.srt", "dual.ass"))
    srt(original_srt, "Hallo")
    srt(ru_srt, "Привет")
    dual.write_text(
        r"""[Script Info]
ScriptType: v4.00+
PlayResX: 160
PlayResY: 120
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,15,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,10,10,5,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.50,Default,,0,0,0,,Hallo\NПривет
""", encoding="utf-8")
    return video, dubbed, original_srt, ru_srt, dual, original_bytes, dubbed_bytes


def test_validates_language_and_output_path(tmp_path):
    with pytest.raises(ValueError, match="source_language"):
        build_master(source_video="x", dubbed_pcm_wav="a", source_srt="b", russian_srt="c",
                     bilingual_ass="d", output_mkv=tmp_path / "out.mkv", source_language="xyz")
    with pytest.raises(ValueError, match=".mkv"):
        build_master(source_video="x", dubbed_pcm_wav="a", source_srt="b", russian_srt="c",
                     bilingual_ass="d", output_mkv=tmp_path / "out.mp4", source_language="de")


@pytest.mark.skipif(not HAS_FFMPEG, reason="requires local FFmpeg and ffprobe")
def test_mkv_has_two_independent_audio_and_three_subtitle_tracks(tmp_path):
    video, dubbed, de, ru, dual, original_data, dubbed_data = make_inputs(tmp_path)
    result = tmp_path / "lecture.ru.mkv"
    build_master(source_video=video, dubbed_pcm_wav=dubbed, source_srt=de,
                 russian_srt=ru, bilingual_ass=dual, output_mkv=result, source_language="de")
    assert result.exists()
    streams = inspect_master(result, source_language="de")
    assert streams["audios"][0]["disposition"]["default"] == 1
    assert streams["audios"][1]["disposition"]["default"] == 0
    assert [s["codec_name"] for s in streams["subtitles"]] == ["subrip", "subrip", "ass"]
    assert decoded_pcm(result, 0) == dubbed_data
    assert decoded_pcm(result, 1) == original_data
    assert dubbed_data[:48000 * 4] != original_data[:48000 * 4]
    assert dubbed_data[48000 * 4:] == original_data[48000 * 4:]
    with pytest.raises(ValueError, match="already exists"):
        build_master(source_video=video, dubbed_pcm_wav=dubbed, source_srt=de,
                     russian_srt=ru, bilingual_ass=dual, output_mkv=result, source_language="de")


@pytest.mark.skipif(not HAS_FFMPEG, reason="requires local FFmpeg and ffprobe")
def test_mkv_mixed_original_language_tag(tmp_path):
    video, dubbed, de, ru, dual, _, _ = make_inputs(tmp_path)
    result = tmp_path / "mixed.ru.mkv"
    build_master(source_video=video, dubbed_pcm_wav=dubbed, source_srt=de,
                 russian_srt=ru, bilingual_ass=dual, output_mkv=result, source_language="mul")
    report = inspect_master(result, source_language="mul")
    assert report["audios"][1]["tags"]["language"] == "mul"
