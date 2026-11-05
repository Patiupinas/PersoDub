"""Source-bound EBU R128 loudness normalization for the Overdub base track.

A single deterministic, reviewable two-pass FFmpeg transform owns source-base
normalization. The A4 approval plan remains bound to the untouched decoded
source; the selectable Original MP4 audio stream is never replaced.
"""
import hashlib
import json
import math
import os
import re
import subprocess
import wave
from pathlib import Path

from app.audio.pcm import NCHANNELS, SAMPWIDTH, SR

SOURCE_LOUDNESS_PROFILE = "r128_source_loudnorm_two_pass_v1"
SOURCE_TARGET_LUFS = -22.0
SOURCE_TRUE_PEAK_DBTP = -1.5
SOURCE_LRA = 20.0


class SourceLoudnessError(ValueError):
    """Source normalization cannot produce a verifiable base track."""


def _sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _wav_frames(path):
    try:
        with wave.open(str(path), "rb") as audio:
            if (audio.getnchannels() != NCHANNELS or audio.getsampwidth() != SAMPWIDTH
                    or audio.getframerate() != SR or audio.getcomptype() != "NONE"):
                raise SourceLoudnessError("Source baseline requires 48 kHz stereo PCM16 WAV")
            frames = audio.getnframes()
            if frames <= 0:
                raise SourceLoudnessError("Source baseline contains no audio frames")
            return frames
    except (wave.Error, EOFError) as error:
        raise SourceLoudnessError("Source baseline WAV is unreadable") from error


def _loudnorm_report(argv, duration):
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=max(120, duration * 2),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise SourceLoudnessError("FFmpeg loudness probe was unavailable or timed out") from error
    if result.returncode:
        lines = result.stderr.strip().splitlines()
        detail = lines[-1][:160] if lines else f"exit status {result.returncode}"
        raise SourceLoudnessError("FFmpeg loudness normalization failed: " + detail)
    matches = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', result.stderr, re.S)
    if not matches:
        raise SourceLoudnessError("FFmpeg loudnorm did not return EBU R128 statistics")
    payload = json.loads(matches[-1])
    for key in ("input_i", "input_tp", "input_lra", "input_thresh",
                "output_i", "output_tp", "target_offset"):
        try:
            payload[key] = float(payload[key])
        except (ValueError, KeyError, TypeError) as error:
            raise SourceLoudnessError("Invalid loudnorm statistic: " + key) from error
    return payload


def _valid_cache(receipt, *, source_sha, frames, normalized_path):
    if not isinstance(receipt, dict):
        return False
    expected = {
        "schema_version": 1,
        "profile": SOURCE_LOUDNESS_PROFILE,
        "source_wav_sha256": source_sha,
        "source_frames": frames,
        "target_lufs": SOURCE_TARGET_LUFS,
        "true_peak_ceiling_dbtp": SOURCE_TRUE_PEAK_DBTP,
        "target_lra": SOURCE_LRA,
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        return False
    if not normalized_path.is_file():
        return False
    try:
        if _wav_frames(normalized_path) != frames:
            return False
        return _sha_file(normalized_path) == receipt.get("normalized_wav_sha256")
    except (OSError, SourceLoudnessError):
        return False


def normalize_overdub_base(source_wav, normalized_wav, receipt_path):
    """Build or reuse a measured, same-sample-clock normalized base WAV.

    Match -22 LUFS with maximum -1.5 dBTP while preserving original duration.
    Prefer linear processing, allowing FFmpeg's true-peak-limited dynamic
    fallback where fixed gain would exceed the ceiling. Report both modes.
    """
    source = Path(source_wav)
    output = Path(normalized_wav)
    receipt_file = Path(receipt_path)
    if len({source.resolve(), output.resolve(), receipt_file.resolve()}) != 3:
        raise SourceLoudnessError("Normalized base and receipt must be separate from source")
    frames = _wav_frames(source)
    duration = frames / SR
    source_sha = _sha_file(source)
    if output.exists() and receipt_file.exists():
        try:
            cached = json.loads(receipt_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = None
        if _valid_cache(cached, source_sha=source_sha, frames=frames,
                        normalized_path=output):
            return cached

    base = (
        f"loudnorm=I={SOURCE_TARGET_LUFS}:TP={SOURCE_TRUE_PEAK_DBTP}"
        f":LRA={SOURCE_LRA}"
    )
    first = _loudnorm_report([
        "ffmpeg", "-nostdin", "-hide_banner", "-nostats",
        "-i", str(source), "-af", base + ":print_format=json",
        "-f", "null", "-",
    ], duration)
    if not math.isfinite(first["input_i"]):
        raise SourceLoudnessError("The original track has no measurable programme loudness")

    measured = [
        f"measured_I={first['input_i']}",
        f"measured_TP={first['input_tp']}",
        f"measured_LRA={first['input_lra']}",
        f"measured_thresh={first['input_thresh']}",
        f"offset={first['target_offset']}",
        "linear=true",
        "print_format=json",
    ]
    # FFmpeg's loudnorm may run at 192 kHz internally. Resample *before*
    # atrim=end_sample, otherwise the output could silently lose 3/4 of its
    # time; source syllables and A4 vocal exercises must stay on the clock.
    filter_chain = (base + ":" + ":".join(measured)
                    + f",aresample={SR},apad,atrim=end_sample={frames}")
    tmp_wav = output.with_name(output.name + ".part.wav")
    tmp_receipt = receipt_file.with_name(receipt_file.name + ".part")
    if tmp_wav.exists() or tmp_receipt.exists():
        raise SourceLoudnessError("An unfinished source normalization already exists")

    output.parent.mkdir(parents=True, exist_ok=True)
    receipt_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        second = _loudnorm_report([
            "ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-y",
            "-i", str(source), "-af", filter_chain,
            "-ar", str(SR), "-ac", str(NCHANNELS),
            "-c:a", "pcm_s16le", str(tmp_wav),
        ], duration)
        if _wav_frames(tmp_wav) != frames:
            raise SourceLoudnessError("Normalization changed the source audio sample clock")
        verified = _loudnorm_report([
            "ffmpeg", "-nostdin", "-hide_banner", "-nostats",
            "-i", str(tmp_wav), "-af", base + ":print_format=json",
            "-f", "null", "-",
        ], duration)
        measured_lufs = verified["input_i"]
        measured_peak = verified["input_tp"]
        if (abs(measured_lufs - SOURCE_TARGET_LUFS) > 0.75
                or measured_peak > SOURCE_TRUE_PEAK_DBTP + 0.2):
            raise SourceLoudnessError(
                "Normalized source did not reach a verified loudness/true-peak target"
            )
        if _sha_file(source) != source_sha:
            raise SourceLoudnessError("Original source changed during normalization")
        normalized_sha = _sha_file(tmp_wav)
        receipt = {
            "schema_version": 1,
            "profile": SOURCE_LOUDNESS_PROFILE,
            "source_wav_sha256": source_sha,
            "normalized_wav_sha256": normalized_sha,
            "source_frames": frames,
            "sample_rate": SR,
            "target_lufs": SOURCE_TARGET_LUFS,
            "true_peak_ceiling_dbtp": SOURCE_TRUE_PEAK_DBTP,
            "target_lra": SOURCE_LRA,
            "input_integrated_lufs": first["input_i"],
            "input_true_peak_dbtp": first["input_tp"],
            "normalized_integrated_lufs": measured_lufs,
            "normalized_true_peak_dbtp": measured_peak,
            "normalization_type": second.get("normalization_type"),
            "source_clock_unchanged": True,
            "original_selectable_audio_preserved": True,
        }
        tmp_receipt.write_text(json.dumps(receipt, indent=2) + "\n",
                               encoding="utf-8")
        os.replace(tmp_wav, output)
        os.replace(tmp_receipt, receipt_file)
        return receipt
    finally:
        for tmp in (tmp_wav, tmp_receipt):
            if tmp.exists():
                tmp.unlink()


def validate_normalized_base(source_wav, normalized_wav, receipt):
    """Bind normalized mixer audio to exactly the unchanged A4 source WAV."""
    frames = _wav_frames(source_wav)
    source_sha = _sha_file(source_wav)
    if not _valid_cache(receipt, source_sha=source_sha, frames=frames,
                        normalized_path=Path(normalized_wav)):
        raise SourceLoudnessError("The normalized base does not match the A4 source")
    return frames
