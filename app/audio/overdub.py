"""Sample-accurate, opt-in dialogue overdub on an untouched original soundtrack.

An explicit source-bound event plan owns the choice TRANSLATE/PRESERVE/REVIEW.
The audio renderer never reclassifies activity or decides translation policy.
Both source and translated audio are 48 kHz stereo PCM16; output stays on that
clock. Bounded 0.1-second chunks avoid loading long recordings into memory.
"""

import argparse
import bisect
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

from app.audio.pcm import NCHANNELS, SAMPWIDTH, SR

CHUNK_FRAMES = 4800
ACTIONS = frozenset({"TRANSLATE", "PRESERVE", "REVIEW"})
EVENT_FIELDS = frozenset({"start_frame", "end_frame", "action"})
PLAN_FIELDS = frozenset({
    "schema_version", "sample_rate", "total_frames",
    "source_wav_sha256", "events",
})
FRAME_BYTES = NCHANNELS * SAMPWIDTH


class OverdubError(ValueError):
    """The selected source, approved event clock or audio format is invalid."""


@dataclass(frozen=True)
class OverdubLevels:
    """Per-event dB targets; the total gain cannot exceed unity."""

    speech_original_db: float = -16.0
    speech_dub_db: float = -16.0
    fade_ms: float = 300.0

    def __post_init__(self):
        for value in (self.speech_original_db, self.speech_dub_db, self.fade_ms):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise OverdubError("Overdub levels must be finite numeric values")
        if not -60 <= self.speech_original_db <= 0 or not -60 <= self.speech_dub_db <= 0:
            raise OverdubError("Speech gains must remain within -60..0 dB")
        if not 0 <= self.fade_ms <= 2000:
            raise OverdubError("Fade length must be within 0..2000 ms")
        if sum(self.translate_gains) > 1.0 + 1e-9:
            raise OverdubError("Speech gains must sum to at most unity to avoid clipping")

    @property
    def translate_gains(self):
        return (10 ** (self.speech_original_db / 20.0),
                10 ** (self.speech_dub_db / 20.0))


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    action: str


def _sha_file(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _integer(value, where, minimum=0):
    if type(value) is not int or value < minimum:
        raise OverdubError(f"{where}: expected an integer >= {minimum}")
    return value


def _open_pcm(path):
    src = wave.open(str(path), "rb")
    if (
        src.getnchannels() != NCHANNELS or src.getframerate() != SR
        or src.getsampwidth() != SAMPWIDTH or src.getcomptype() != "NONE"
    ):
        src.close()
        raise OverdubError("Both tracks must be PCM16 stereo 48000 Hz WAV")
    return src


def _parse_plan(data, source_frames, source_sha):
    if type(data) is not dict or set(data) != PLAN_FIELDS or data["schema_version"] != 1:
        raise OverdubError("Unexpected overdub plan version or fields")
    if (
        _integer(data["sample_rate"], "sample_rate", 1) != SR
        or _integer(data["total_frames"], "total_frames", 1) != source_frames
        or data["source_wav_sha256"] != source_sha
    ):
        raise OverdubError("Event plan does not match the exact original 48 kHz source WAV")
    events = data["events"]
    if type(events) is not list or not events:
        raise OverdubError("Nonempty, complete event partition required")
    spans = []
    previous_end = 0
    for i, event in enumerate(events):
        if type(event) is not dict or set(event) != EVENT_FIELDS:
            raise OverdubError(f"events[{i}]: unexpected fields")
        start = _integer(event["start_frame"], f"events[{i}].start_frame")
        end = _integer(event["end_frame"], f"events[{i}].end_frame", 1)
        action = event["action"]
        if start != previous_end or not start < end <= source_frames:
            raise OverdubError(f"events[{i}]: gap, overlap or source boundary error")
        if type(action) is not str or action not in ACTIONS:
            raise OverdubError(f"events[{i}]: unknown A4 action")
        spans.append(_Span(start, end, action))
        previous_end = end
    if previous_end != source_frames:
        raise OverdubError("Event plan must cover the complete original source")
    return spans


def _voice_activity_intervals(voice, frames):
    """Locate actual Russian TTS speech, independent of subtitle windows.

    Keep brief intra-sentence pauses ducked, but restore the source rapidly
    when the dubbed voice ends, including within a longer A4 speech cue.
    This scans the WAV in bounded blocks without loading the whole recording.
    """
    window = round(SR * 0.02)
    active = []
    for start in range(0, min(frames, voice.getnframes()), window):
        length = min(window, frames - start)
        data = voice.readframes(length)
        values = array("h")
        values.frombytes(data)
        if sys.byteorder != "little":
            values.byteswap()
        if any(abs(value) >= 100 for value in values):
            active.append((start, start + length))
    voice.rewind()
    if not active:
        return []
    lead = round(SR * 0.03)
    hold = round(SR * 0.06)
    bridge = round(SR * 0.12)
    merged = []
    for a, b in active:
        start = max(0, a - lead)
        end = min(frames, b + hold)
        if merged and start <= merged[-1][1] + bridge:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


class _Envelope:
    """Piecewise gains with bounded cosine transitions at verified boundaries."""

    def __init__(self, spans, levels, voice_activity=None):
        self.spans = spans
        self.voice_activity = voice_activity
        self.voice_starts = [a for a, _ in voice_activity] if voice_activity is not None else None
        self.starts = [span.start for span in spans]
        self.original_speech, self.dub_speech = levels.translate_gains
        self.transitions = {}
        target = round(levels.fade_ms * SR / 1000.0)
        for j in range(1, len(spans)):
            left, right = spans[j - 1], spans[j]
            if (left.action == "TRANSLATE") == (right.action == "TRANSLATE"):
                continue
            # Keep every protected source frame at exactly (1.0, 0.0).
            # Both fades live entirely inside the adjacent TRANSLATE span.
            if right.action == "TRANSLATE":
                length = min(target, (right.end - right.start) // 3)
                if length:
                    self.transitions[j] = (right.start, right.start + length)
            else:
                length = min(target, (left.end - left.start) // 3)
                if length:
                    self.transitions[j] = (right.start - length, right.start)

    def _gains(self, action):
        if action == "TRANSLATE":
            return self.original_speech, self.dub_speech
        return 1.0, 0.0

    def _base_at(self, frame):
        # At a boundary, either of the adjacent partitions may own the ramp.
        i = bisect.bisect_right(self.starts, frame) - 1
        for j in (i, i + 1):
            edge = self.transitions.get(j)
            if edge and edge[0] <= frame < edge[1]:
                a, b = edge
                fraction = (frame - a) / (b - a)
                weight = 0.5 - 0.5 * math.cos(math.pi * fraction)
                before = self._gains(self.spans[j - 1].action)
                after = self._gains(self.spans[j].action)
                return (
                    before[0] + (after[0] - before[0]) * weight,
                    before[1] + (after[1] - before[1]) * weight,
                )
        return self._gains(self.spans[i].action)

    def at(self, frame):
        source_gain, dubbing_gain = self._base_at(frame)
        if self.voice_starts is None:
            return source_gain, dubbing_gain
        # Keep every PRESERVE/REVIEW original frame bit-identical.
        index = bisect.bisect_right(self.starts, frame) - 1
        if self.spans[index].action != "TRANSLATE":
            return 1.0, 0.0
        i = bisect.bisect_right(self.voice_starts, frame) - 1
        if i < 0 or frame >= self.voice_activity[i][1]:
            return 1.0, 0.0
        begin, end = self.voice_activity[i]
        ramp = round(SR * 0.025)
        if frame < begin + ramp:
            fraction = min(1.0, (frame - begin) / ramp)
            weight = 0.5 - 0.5 * math.cos(math.pi * fraction)
        elif frame >= end - ramp:
            fraction = min(1.0, (end - frame) / ramp)
            weight = 0.5 - 0.5 * math.cos(math.pi * fraction)
        else:
            weight = 1.0
        return 1.0 + (source_gain - 1.0) * weight, dubbing_gain * weight


def _mix_chunk(original_pcm, dub_pcm, start_frame, envelope):
    n_frames = len(original_pcm) // FRAME_BYTES
    if len(original_pcm) != n_frames * FRAME_BYTES or len(dub_pcm) != len(original_pcm):
        raise OverdubError("Unaligned source/translated PCM frames")
    # 'h' is signed PCM16, and struct '<' makes the result portable across CPUs.
    a = struct.unpack("<%dh" % (n_frames * NCHANNELS), original_pcm)
    b = struct.unpack("<%dh" % (n_frames * NCHANNELS), dub_pcm)
    output = [0] * (n_frames * NCHANNELS)
    for i in range(n_frames):
        origin, dub = envelope.at(start_frame + i)
        for channel in range(NCHANNELS):
            idx = i * NCHANNELS + channel
            value = round(a[idx] * origin + b[idx] * dub)
            output[idx] = max(-32768, min(32767, value))
    return struct.pack("<%dh" % len(output), *output)



def select_translatable_cues(segments, approved_spans):
    """Permit TTS only for whole cues inside explicit source-bound A4 speech.

    A cue straddling a protected/unknown interval is left in the original
    source, not split into misleading translated words. Adjacent TRANSLATE
    intervals may be merged because a manual UI split does not mute audio.
    The approved right edge is copied into each selected cue for the Qwen
    duration and placement limits. Never mutate the complete source script.
    """
    translated = []
    for span in approved_spans:
        if span.action != "TRANSLATE":
            continue
        if translated and span.start == translated[-1][1]:
            translated[-1] = (translated[-1][0], span.end)
        else:
            translated.append((span.start, span.end))
    starts = [start for start, _end in translated]
    selected = []
    skipped = 0
    for source_cue_number, cue in enumerate(segments, start=1):
        start = cue.get("start")
        end = cue.get("end")
        if (type(start) not in (int, float)
                or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end <= start or not cue.get("text", "").strip()):
            skipped += 1
            continue
        a = round(start * SR)
        b = round(end * SR)
        idx = bisect.bisect_right(starts, a) - 1
        if idx < 0 or a >= b or b > translated[idx][1]:
            skipped += 1
            continue
        keep = dict(cue)
        keep["dub_limit_s"] = translated[idx][1] / SR
        keep["source_cue_number"] = source_cue_number
        selected.append(keep)
    return selected, skipped


def source_speech_coverage(source_cues, selected, total_frames):
    """Measure speech-cue selection, not musical-exercise or word-level truth.

    This explicitly distinguishes original-only gaps between source speech
    cues from spoken cues omitted by A4 selection. A completed MP4 and a
    successful mux alone never prove complete translated speech coverage.
    The clock is in original 48kHz PCM frames, not video-container duration.
    """
    if type(total_frames) is not int or total_frames <= 0:
        raise OverdubError("source PCM clock must contain positive frames")

    def cue_window(cue, where):
        if type(cue) is not dict or not (cue.get("text") or "").strip():
            return None
        a, b = cue.get("start"), cue.get("end")
        if (type(a) not in (int, float) or type(b) not in (int, float)
                or not math.isfinite(a) or not math.isfinite(b)
                or a < 0 or b <= a):
            return None
        begin, end = round(a * SR), round(b * SR)
        if begin < 0 or begin >= end or end > total_frames:
            raise OverdubError(f"{where}: speech cue outside original source clock")
        return begin, end

    def union_frames(intervals):
        total, last_end = 0, 0
        for begin, end in sorted(intervals):
            if end <= last_end:
                continue
            total += end - max(begin, last_end)
            last_end = end
        return total

    source_windows = {}
    for i, cue in enumerate(source_cues, 1):
        window = cue_window(cue, f"source cue {i}")
        if window is not None:
            source_windows[i] = window

    seen = set()
    translated_windows = []
    for cue in selected:
        source_no = cue.get("source_cue_number") if isinstance(cue, dict) else None
        if type(source_no) is not int or source_no not in source_windows:
            raise OverdubError("selected voice cue is not tied to a source speech cue")
        if source_no in seen:
            raise OverdubError("duplicate selected source speech cue")
        source = source_cues[source_no - 1]
        if (cue.get("start") != source.get("start") or
                cue.get("end") != source.get("end") or
                cue.get("text") != source.get("text")):
            raise OverdubError("selected voice cue differs from the source speech cue")
        seen.add(source_no)
        translated_windows.append(source_windows[source_no])

    source_frames = union_frames(source_windows.values())
    selected_frames = union_frames(translated_windows)
    if selected_frames > source_frames:
        raise OverdubError("selected speech exceeds source speech clock")
    absent = [i for i in range(1, len(source_cues) + 1) if i not in seen]
    if not source_cues:
        status = "NO_TRANSCRIBED_SPEECH"
    elif absent:
        status = "INCOMPLETE_SOURCE_SPEECH_COVERAGE"
    else:
        status = "ALL_TRANSCRIBED_SPEECH_CUES_SELECTED"
    return {
        "status": status,
        "source_cues": len(source_cues),
        "translated_cues": len(seen),
        "source_only_cues": len(absent),
        "uncovered_source_cue_numbers": absent,
        "source_cue_coverage_percent": (
            round(len(seen) * 100 / len(source_cues), 6) if source_cues else None
        ),
        "source_speech_seconds": round(source_frames / SR, 3),
        "translated_source_cue_seconds": round(selected_frames / SR, 3),
        "untranslated_source_cue_seconds": round((source_frames - selected_frames) / SR, 3),
        "source_speech_time_coverage_percent": (
            round(selected_frames * 100 / source_frames, 6) if source_frames else None
        ),
        "outside_source_cue_seconds": round((total_frames - source_frames) / SR, 3),
        "source_pcm_frames": total_frames,
        "human_verified_exercises": False,
        "metric_scope": "source_transcript_cue_windows_not_word_or_singing_gold",
    }


def validate_overdub_plan(source_wav, event_plan):
    """Validate the exact sample clock and original PCM hash before TTS."""
    with _open_pcm(source_wav) as source:
        return _parse_plan(
            json.loads(Path(event_plan).read_text(encoding="utf-8")),
            source.getnframes(), _sha_file(source_wav),
        )


def create_review_plan(source_wav, output_path):
    """Create a source-bound all-REVIEW template; never auto-approve dubbing."""
    dest = Path(output_path)
    if dest.exists() or dest.resolve() == Path(source_wav).resolve():
        raise OverdubError("Plan output must be new and separate from the WAV")
    with _open_pcm(source_wav) as source:
        frames = source.getnframes()
    if frames <= 0:
        raise OverdubError("Cannot create a plan for empty original audio")
    plan = {
        "schema_version": 1, "sample_rate": SR,
        "total_frames": frames, "source_wav_sha256": _sha_file(source_wav),
        "events": [
            {"start_frame": 0, "end_frame": frames, "action": "REVIEW"}
        ],
    }
    dest.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan


def write_silent_bed_like(background_wav, output_wav):
    """Create zero PCM at the separated background's duration, without loading it."""
    dest = Path(output_wav)
    if dest.exists() or dest.resolve() == Path(background_wav).resolve():
        raise OverdubError("Silent bed must use a new output path")
    with wave.open(str(background_wav), "rb") as source:
        if source.getframerate() <= 0 or source.getnframes() <= 0:
            raise OverdubError("Background contains no audio frames")
        frames = round(source.getnframes() * SR / source.getframerate())
    with wave.open(str(dest), "wb") as output:
        output.setnchannels(NCHANNELS)
        output.setsampwidth(SAMPWIDTH)
        output.setframerate(SR)
        zeros = b"\x00" * (CHUNK_FRAMES * FRAME_BYTES)
        for start in range(0, frames, CHUNK_FRAMES):
            output.writeframesraw(zeros[:min(CHUNK_FRAMES, frames - start) * FRAME_BYTES])
    return str(dest)


def extract_original_pcm(video_path, output_wav, duration=None):
    """Decode the video's first audio track onto the source-aligned 48k clock."""
    dest = Path(output_wav)
    if dest.exists() or dest.resolve() == Path(video_path).resolve():
        raise OverdubError("Original PCM output must be new and separate")
    args = [
        "ffmpeg", "-y", "-v", "error", "-i", str(video_path),
        "-map", "0:a:0", "-vn",
        "-af", "aresample=async=1:first_pts=0" + (
            ",apad" if duration is not None else ""
        ),
        "-ar", str(SR), "-ac", str(NCHANNELS), "-c:a", "pcm_s16le",
    ]
    if duration is not None:
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or (
            not math.isfinite(duration) or duration <= 0
        ):
            raise OverdubError("Source duration must be finite and positive")
        args += ["-t", f"{duration:.6f}"]
    result = subprocess.run(
        args + [str(dest)], capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        if dest.exists():
            dest.unlink()
        raise OverdubError("Could not decode the source audio: " + (
            result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "ffmpeg failed"
        ))
    with _open_pcm(dest) as src:
        if src.getnframes() <= 0:
            raise OverdubError("Original video has no usable audio samples")
    return str(dest)

def render_overdub(original_wav, dub_voice_wav, event_plan, output_wav, *,
                   levels=None):
    """Combine original + voice-only translated TTS using source-bound A4 spans.

    REVIEW and PRESERVE both pass original audio at its exact original samples
    and mute the dubbed voice. TRANSLATE keeps the original audible at a lower
    level while playing dubbed speech. Transitions are raised-cosine, and the
    sum of gain magnitudes is <=1 so the mixer never clips by summation.

    The dub WAV may end early (zero-padded) or have a <=50 ms encoder/separator
    tail beyond the source (trimmed). A longer, <=250 ms tail is accepted only
    when every extra PCM byte is zero: cached separator stems may include AAC
    stream padding beyond the source-video clock. A non-silent or larger
    overrun is rejected, so no synthesized speech is silently truncated.
    """
    levels = levels or OverdubLevels()
    if type(levels) is not OverdubLevels:
        raise OverdubError("Unsupported overdub gain profile")
    src_path = Path(original_wav)
    dub_path = Path(dub_voice_wav)
    out_path = Path(output_wav)
    if (
        len({src_path.resolve(), dub_path.resolve(), out_path.resolve()}) != 3
        or out_path.exists()
    ):
        raise OverdubError("Output must be new and separate from both inputs")
    data = json.loads(Path(event_plan).read_text(encoding="utf-8"))
    with _open_pcm(src_path) as source, _open_pcm(dub_path) as translated:
        frames = source.getnframes()
        tail_trimmed = max(0, translated.getnframes() - frames)
        short_tail = round(0.05 * SR)
        if tail_trimmed > short_tail:
            # The source clock is the original video's decoded PCM. A cached
            # separation stem can have 51 ms of codec padding even when all
            # TTS placements stop before the reviewed source end. A bounded,
            # entirely silent overhang is not speech and may be discarded.
            if tail_trimmed > round(0.25 * SR):
                raise OverdubError("Translated WAV must not outlast the source by over 250 ms")
            translated.setpos(frames)
            remaining = tail_trimmed
            while remaining:
                count = min(remaining, CHUNK_FRAMES)
                padding = translated.readframes(count)
                if len(padding) != count * FRAME_BYTES or padding.strip(b"\x00"):
                    raise OverdubError("Translated WAV must not outlast the source with audible audio")
                remaining -= count
            translated.rewind()
        spans = _parse_plan(data, frames, _sha_file(src_path))
        voice_activity = _voice_activity_intervals(translated, frames)
        envelope = _Envelope(spans, levels, voice_activity=voice_activity)
        pending = out_path.with_name(out_path.name + ".part")
        if pending.exists():
            raise OverdubError("Pending output file already exists")
        try:
            with wave.open(str(pending), "wb") as output:
                output.setnchannels(NCHANNELS)
                output.setsampwidth(SAMPWIDTH)
                output.setframerate(SR)
                for first in range(0, frames, CHUNK_FRAMES):
                    count = min(CHUNK_FRAMES, frames - first)
                    orig_pcm = source.readframes(count)
                    tts_pcm = translated.readframes(count)
                    tts_pcm = tts_pcm.ljust(len(orig_pcm), b"\x00")
                    if len(orig_pcm) != count * FRAME_BYTES:
                        raise OverdubError("Original WAV ended unexpectedly")
                    output.writeframesraw(_mix_chunk(orig_pcm, tts_pcm, first, envelope))
            os.replace(pending, out_path)
        finally:
            if pending.exists():
                pending.unlink()
    return {
        "schema_version": 1,
        "status": "rendered_approved_partition_overdub",
        "source_wav_sha256": data["source_wav_sha256"],
        "dub_voice_sha256": _sha_file(dub_path),
        "event_plan_sha256": _sha_file(event_plan),
        "overdub_sha256": _sha_file(out_path),
        "frames": frames,
        "dub_tail_trimmed_frames": tail_trimmed,
        "sample_rate": SR,
        "levels": {
            "original_under_speech_db": levels.speech_original_db,
            "dub_under_speech_db": levels.speech_dub_db,
            "fade_ms": levels.fade_ms,
            "voice_silence_release": "60ms hold plus 25ms final fade",
        },
        "voice_activity_intervals": len(voice_activity),
        "action_frames": {
            action: sum(s.end - s.start for s in spans if s.action == action)
            for action in ("TRANSLATE", "PRESERVE", "REVIEW")
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render source-bound dual-language overdub WAV")
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--dub-voice", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--original-speech-db", type=float, default=-16.0)
    parser.add_argument("--dub-speech-db", type=float, default=-16.0)
    parser.add_argument("--fade-ms", type=float, default=300)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        options = OverdubLevels(args.original_speech_db, args.dub_speech_db, args.fade_ms)
        result = render_overdub(
            args.original, args.dub_voice, args.events, args.output, levels=options
        )
        if args.receipt:
            if args.receipt.exists() or args.receipt.resolve() in {
                args.original.resolve(), args.dub_voice.resolve(),
                args.events.resolve(), args.output.resolve(),
            }:
                raise OverdubError("Receipt must be a new, separate file")
            args.receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, wave.Error) as exc:
        parser.exit(2, f"Overdub rejected: {exc}\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
