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
import wave
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
    speech_dub_db: float = -2.0
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


class _Envelope:
    """Piecewise gains with bounded cosine transitions at verified boundaries."""

    def __init__(self, spans, levels):
        self.spans = spans
        self.starts = [span.start for span in spans]
        self.original_speech, self.dub_speech = levels.translate_gains
        self.transitions = {}
        target = round(levels.fade_ms * SR / 1000.0)
        for j in range(1, len(spans)):
            left, right = spans[j - 1], spans[j]
            if left.action == right.action:
                continue
            half = min(target // 2, (left.end - left.start) // 3,
                       (right.end - right.start) // 3)
            if half:
                self.transitions[j] = (right.start - half, right.start + half)

    def _gains(self, action):
        if action == "TRANSLATE":
            return self.original_speech, self.dub_speech
        return 1.0, 0.0

    def at(self, frame):
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
    tail beyond the source (trimmed). Longer overruns are rejected.
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
        if tail_trimmed > round(0.05 * SR):
            raise OverdubError("Translated WAV must not outlast the source by over 50 ms")
        spans = _parse_plan(data, frames, _sha_file(src_path))
        envelope = _Envelope(spans, levels)
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
        },
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
    parser.add_argument("--dub-speech-db", type=float, default=-2.0)
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
