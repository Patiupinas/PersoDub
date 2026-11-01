"""Experimental bounded source-video ASR for the existing Whisper worker.

This module never assigns A4 translate/preserve actions. It only creates
machine-transcribed source-language cues from independent overlapping audio
windows; no source video, cached dub or user-provided subtitle is rewritten.
The 30-minute ceiling is explicit until durable long-form checkpoints exist.
"""
from __future__ import annotations

import math
import subprocess

WINDOW_SECONDS = 34.0
OVERLAP_SECONDS = 5.0
MAX_SOURCE_SECONDS = 30 * 60
SAMPLE_RATE = 16000
SUPPORTED_LANGUAGES = frozenset(("en", "de", "es"))


def plan_source_windows(duration, window=WINDOW_SECONDS, overlap=OVERLAP_SECONDS):
    """Use symmetric overlapping observations and disjoint ownership cores."""
    if (type(duration) not in (int, float)
            or not math.isfinite(duration) or duration <= 0
            or duration > MAX_SOURCE_SECONDS
            or not 10 <= window <= WINDOW_SECONDS
            or not 0 <= overlap < window / 2):
        raise ValueError("Unsupported bounded source duration or window settings")
    result = []
    step = window - overlap
    start = 0.0
    while start < duration - 0.0005:
        end = min(start + window, duration)
        result.append({"start": round(start, 3), "end": round(end, 3)})
        if end >= duration - 0.0005:
            break
        start += step
    for i, row in enumerate(result):
        row["core_start"] = (
            0.0 if i == 0
            else round((result[i - 1]["end"] + row["start"]) / 2, 3)
        )
        row["core_end"] = (
            round(duration, 3) if i == len(result) - 1
            else round((row["end"] + result[i + 1]["start"]) / 2, 3)
        )
    return result


def source_duration(path):
    """Read container duration once instead of decoding the whole recording."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True, timeout=20,
    )
    return float(result.stdout.strip())


def decode_window(path, start, length):
    """Decode only up to 34 seconds of the original 16k mono source audio."""
    import numpy as np

    if (not math.isfinite(start) or not math.isfinite(length)
            or start < 0 or length <= 0 or length > WINDOW_SECONDS + 0.001):
        raise ValueError("Invalid source PCM decode window")
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-i", str(path), "-map", "0:a:0",
        "-t", f"{length:.3f}", "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1",
    ]
    result = subprocess.run(
        command, check=True, capture_output=True, timeout=75,
    )
    pcm = np.frombuffer(result.stdout, dtype="<f4")
    if len(pcm) < 1000 or not np.all(np.isfinite(pcm)):
        raise ValueError("Original source PCM window was empty or non-finite")
    return pcm.copy()


def merge_owned_cues(windows, decoded, duration):
    """Keep each recognized word once, using its original source-audio clock.

    Each decoded item contains the corresponding window's segment objects.
    Words are sorted by their source origin, not by confidence or sentence text.
    An unscored transcript fragment cannot be merged without valid word times.
    """
    if len(windows) != len(decoded):
        raise ValueError("Missing bounded ASR window")
    cues = []
    for i, (window, segments) in enumerate(zip(windows, decoded)):
        if segments is None:
            raise ValueError("Missing ASR segments")
        for segment in segments:
            words = list(getattr(segment, "words", None) or [])
            text = str(getattr(segment, "text", "")).strip()
            if text and not words:
                raise ValueError("Bounded source ASR returned text without word timestamps")
            owned = []
            for word in words:
                left = float(word.start) + window["start"]
                right = float(word.end) + window["start"]
                if (not math.isfinite(left) or not math.isfinite(right)
                        or right <= left or left < window["start"] - 0.05
                        or right > window["end"] + 0.25):
                    raise ValueError("Invalid source ASR word timing")
                midpoint = (left + right) / 2
                belongs = window["core_start"] <= midpoint < window["core_end"]
                if i == len(windows) - 1 and midpoint == window["core_end"]:
                    belongs = True
                if belongs:
                    owned.append({
                        "start": round(max(0.0, left), 3),
                        "end": round(min(duration, right), 3),
                        "word": str(word.word),
                    })
            if not owned:
                continue
            if owned[-1]["end"] <= owned[0]["start"]:
                raise ValueError("Source ASR produced an empty cue")
            cues.append({
                "start": owned[0]["start"], "end": owned[-1]["end"],
                "text": "".join(x["word"] for x in owned).strip(),
                "words": owned,
            })
    if not cues:
        raise ValueError("Bounded source ASR found no timestamped speech")
    last = -1.0
    for cue in cues:
        if not cue["text"] or cue["start"] < last - 0.001:
            raise ValueError("Bounded source ASR cues are empty or out of time order")
        last = cue["start"]
    return cues


def transcribe_bounded_source(model, path, language, *, duration_reader=source_duration,
                              decoder=decode_window):
    """Transcribe source words in bounded windows; never reinterpret vocal actions."""
    if not isinstance(language, str) or language not in SUPPORTED_LANGUAGES:
        raise ValueError("Bounded source ASR currently supports explicit en, de or es only")
    duration = duration_reader(path)
    windows = plan_source_windows(duration)
    decoded = []
    for row in windows:
        pcm = decoder(path, row["start"], row["end"] - row["start"])
        # Preserve the research probe's exact large-v3 decoder settings.
        segments, info = model.transcribe(
            pcm, language=language, beam_size=5, word_timestamps=True,
            condition_on_previous_text=True, vad_filter=False,
        )
        decoded.append(list(segments))
    return merge_owned_cues(windows, decoded, duration), language
