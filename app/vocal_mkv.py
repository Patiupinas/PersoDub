"""Lossless multi-track MKV mux for already-assembled selective dubbing.

This leaf module does not translate, synthesize, edit PCM, or create subtitles.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

_SOURCE_LANGUAGES = {"en": "eng", "de": "deu", "es": "spa", "mul": "mul"}


def _probe(path):
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path),
    ], text=True, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {Path(path).name}: {result.stderr.strip()[-300:]}")
    return json.loads(result.stdout)["streams"]


def _streams(path, kind):
    return [stream for stream in _probe(path) if stream["codec_type"] == kind]


def inspect_master(path, *, source_language):
    """Return checked stream metadata; do not infer success from ffmpeg exit alone."""
    streams = _probe(path)
    video = [s for s in streams if s["codec_type"] == "video"]
    audio = [s for s in streams if s["codec_type"] == "audio"]
    subs = [s for s in streams if s["codec_type"] == "subtitle"]
    if len(video) != 1 or len(audio) != 2 or len(subs) != 3:
        raise ValueError("Expected exactly 1 video, 2 audio and 3 subtitle tracks")
    expected = ["rus", _SOURCE_LANGUAGES[source_language]]
    if [s.get("tags", {}).get("language") for s in audio] != expected:
        raise ValueError("Audio stream language metadata does not match the contract")
    if any(track["codec_name"] != "flac" or track.get("sample_fmt") != "s16" for track in audio):
        raise ValueError("Both master audio tracks must be lossless 16-bit FLAC")
    if [s.get("disposition", {}).get("default", 0) for s in audio] != [1, 0]:
        raise ValueError("Russian audio must be the sole default track")
    if [s.get("tags", {}).get("language") for s in subs] != [expected[1], "rus", "mul"]:
        raise ValueError("Subtitle stream language metadata does not match the contract")
    if [s.get("codec_name") for s in subs] != ["subrip", "subrip", "ass"]:
        raise ValueError("Expected source/RU SubRip and bilingual ASS")
    return {"video": video[0], "audios": audio, "subtitles": subs}


def build_master(*, source_video, dubbed_pcm_wav, source_srt, russian_srt,
                 bilingual_ass, output_mkv, source_language):
    """Mux a finished PCM dub, original A/V, and three switchable subtitle tracks.

    Video is stream-copied. Both decoded audio tracks are encoded as 16-bit
    lossless FLAC to preserve AAC decoder priming and exact source PCM samples. Inputs remain unchanged, output is published atomically.
    """
    if source_language not in _SOURCE_LANGUAGES:
        raise ValueError("source_language must be en, de, es or mul")
    input_paths = [Path(p).resolve() for p in (
        source_video, dubbed_pcm_wav, source_srt, russian_srt, bilingual_ass)]
    output = Path(output_mkv).resolve()
    if output.suffix.lower() != ".mkv":
        raise ValueError("Master output must be a .mkv file")
    if output in input_paths or output.exists():
        raise ValueError("Output already exists or would overwrite an input")
    for path in input_paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    if not _streams(input_paths[0], "video") or not _streams(input_paths[0], "audio"):
        raise ValueError("Source video must contain video and original audio")
    if not _streams(input_paths[1], "audio"):
        raise ValueError("Dubbed PCM input must contain an audio stream")

    lang = _SOURCE_LANGUAGES[source_language]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".vocal-mkv-",
                                         suffix=".mkv", delete=False) as destination:
            temporary = Path(destination.name)
        args = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error"]
        for path in input_paths:
            args += ["-i", str(path)]
        args += [
            "-map", "0:v:0", "-map", "1:a:0", "-map", "0:a:0",
            "-map", "2:s:0", "-map", "3:s:0", "-map", "4:s:0",
            "-map_metadata", "0", "-map_chapters", "0",
            "-c:v", "copy", "-c:a:0", "flac", "-sample_fmt:a:0", "s16",
            "-c:a:1", "flac", "-sample_fmt:a:1", "s16", "-c:s", "copy",
            "-metadata:s:a:0", "language=rus",
            "-metadata:s:a:0", "title=Russian dubbed explanations",
            "-disposition:a:0", "default",
            "-metadata:s:a:1", f"language={lang}",
            "-metadata:s:a:1", "title=Original audio",
            "-disposition:a:1", "0",
            "-metadata:s:s:0", f"language={lang}",
            "-metadata:s:s:0", "title=Original transcript",
            "-metadata:s:s:1", "language=rus",
            "-metadata:s:s:1", "title=Russian translation",
            "-metadata:s:s:2", "language=mul",
            "-metadata:s:s:2", "title=Bilingual subtitles",
            "-disposition:s:0", "0", "-disposition:s:1", "0", "-disposition:s:2", "0",
            str(temporary),
        ]
        process = subprocess.run(args, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace")
        if process.returncode != 0:
            raise RuntimeError(f"MKV mux failed: {process.stderr.strip()[-500:]}")
        checked = inspect_master(temporary, source_language=source_language)
        original_video = _streams(input_paths[0], "video")[0]
        if checked["video"]["codec_name"] != original_video["codec_name"]:
            raise ValueError("Video codec changed during intended stream-copy")
        os.replace(temporary, output)
        temporary = None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return output
