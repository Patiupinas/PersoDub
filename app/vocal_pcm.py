"""Offline, sample-accurate WAV assembly for selective vocal dubbing.

This optional module is not connected to the standard PersoDub pipeline.
It is intentionally conservative: TRANSLATE takes a prepared speech WAV and
silence-pads its remaining slot; PRESERVE and REVIEW copy the original source
PCM verbatim. No background/stem mixing, time-stretch, or resampling occurs.
"""

import argparse
import hashlib
import json
import os
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from app.vocal_decisions import DecisionManifest, parse_decision_manifest


CHUNK_FRAMES = 65536


class PCMAssemblyError(ValueError):
    """An input or integrity condition would make the rendered audio unsafe."""


@dataclass(frozen=True)
class AssemblyReport:
    output_pcm_sha256: str
    total_samples: int
    translated_samples: int
    protected_samples: int
    tts_audio_samples: int
    silence_padding_samples: int


def _check_wav(reader, label):
    if reader.getcomptype() != "NONE" or reader.getsampwidth() != 2:
        raise PCMAssemblyError(f"{label}: requires uncompressed 16-bit PCM WAV")
    if reader.getnchannels() not in (1, 2):
        raise PCMAssemblyError(f"{label}: requires mono or stereo PCM WAV")
    if reader.getframerate() <= 0:
        raise PCMAssemblyError(f"{label}: invalid sample rate")
    return reader.getframerate(), reader.getnchannels(), reader.getsampwidth()


def _read_exact(reader, frames, frame_bytes, label):
    data = reader.readframes(frames)
    if len(data) != frames * frame_bytes:
        raise PCMAssemblyError(f"{label}: truncated PCM data (expected {frames} frames)")
    return data


def _digest_wav(path, label):
    """Hash decoded PCM bytes, not the WAV container header, in bounded RAM."""
    digest = hashlib.sha256()
    with wave.open(str(path), "rb") as reader:
        layout = _check_wav(reader, label)
        count = reader.getnframes()
        frame_bytes = layout[1] * layout[2]
        remaining = count
        while remaining:
            take = min(remaining, CHUNK_FRAMES)
            digest.update(_read_exact(reader, take, frame_bytes, label))
            remaining -= take
    return layout, count, digest.hexdigest()


def _check_protected(source_path, output_path, manifest):
    """Independently compare protected decoded PCM bytes before atomic publish."""
    checked = 0
    with wave.open(str(source_path), "rb") as original, wave.open(str(output_path), "rb") as rendered:
        original_layout = _check_wav(original, "source")
        output_layout = _check_wav(rendered, "output")
        if original_layout != output_layout or rendered.getnframes() != manifest.total_samples:
            raise PCMAssemblyError("output: format or duration changed")
        if original.getnframes() != manifest.total_samples:
            raise PCMAssemblyError("source: duration changed during assembly")
        frame_bytes = original_layout[1] * original_layout[2]
        for span in manifest.spans:
            if span.action == "TRANSLATE":
                continue
            original.setpos(span.start_sample)
            rendered.setpos(span.start_sample)
            remaining = span.end_sample - span.start_sample
            while remaining:
                take = min(remaining, CHUNK_FRAMES)
                before = _read_exact(original, take, frame_bytes, f"source {span.segment_id}")
                after = _read_exact(rendered, take, frame_bytes, f"output {span.segment_id}")
                if before != after:
                    raise PCMAssemblyError(f"{span.segment_id}: protected PCM was modified")
                checked += take
                remaining -= take
    return checked


def verify_preserved_wav(source_wav, output_wav, raw_manifest):
    """Verify PCM provenance and equality of every PRESERVE/REVIEW frame.

    This validates intermediate PCM WAV; it does not certify later lossy AAC
    encoding, video PTS synchronization, or suitability of the classification.
    """
    manifest = parse_decision_manifest(raw_manifest)
    source_layout, frames, pcm_hash = _digest_wav(source_wav, "source")
    if frames != manifest.total_samples or source_layout[0] != manifest.sample_rate:
        raise PCMAssemblyError("source: decoded PCM format disagrees with manifest")
    if pcm_hash != manifest.pcm_sha256:
        raise PCMAssemblyError("source: PCM SHA-256 disagrees with manifest")
    return _check_protected(source_wav, output_wav, manifest)


def _preflight(source, tts_paths, manifest):
    source_layout, samples, pcm_hash = _digest_wav(source, "source")
    if samples != manifest.total_samples or source_layout[0] != manifest.sample_rate:
        raise PCMAssemblyError("source: decoded PCM format disagrees with manifest")
    if pcm_hash != manifest.pcm_sha256:
        raise PCMAssemblyError("source: PCM SHA-256 disagrees with manifest")

    expected = {s.segment_id for s in manifest.spans if s.action == "TRANSLATE"}
    if not isinstance(tts_paths, Mapping) or any(not isinstance(k, str) for k in tts_paths):
        raise PCMAssemblyError("TTS inputs: expected segment-id to WAV path mapping")
    keys = set(tts_paths)
    if keys != expected:
        raise PCMAssemblyError(f"TTS inputs: missing {sorted(expected - keys)}, unexpected {sorted(keys - expected)}")

    tts_meta = {}
    for span in manifest.spans:
        if span.action != "TRANSLATE":
            continue
        path = Path(tts_paths[span.segment_id])
        if path.resolve() == source.resolve():
            raise PCMAssemblyError(f"{span.segment_id}: source WAV cannot be TTS input")
        layout, frames, checksum = _digest_wav(path, f"TTS {span.segment_id}")
        if layout != source_layout:
            raise PCMAssemblyError(f"TTS {span.segment_id}: sample rate, channels or bit depth mismatch")
        limit = span.end_sample - span.start_sample
        if frames < 1 or frames > limit:
            raise PCMAssemblyError(f"TTS {span.segment_id}: must contain 1..{limit} frames (got {frames})")
        tts_meta[span.segment_id] = (path, frames, checksum)
    return source_layout, tts_meta


def assemble_vocal_wav(source_wav, output_wav, raw_manifest, tts_wavs):
    """Assemble WAV atomically after strict validation and integrity checks.

    Existing output remains unchanged on validation, read, or integrity errors.
    No operation ever modifies the source, TTS input WAVs, or protected spans.
    Output PCM contains one source-backed frame per decision frame; TTS that
    ends early is padded with silence and TTS that overflows its slot is refused.
    """
    manifest = parse_decision_manifest(raw_manifest)
    source, output = Path(source_wav), Path(output_wav)
    if source.resolve() == output.resolve():
        raise PCMAssemblyError("output path cannot overwrite source WAV")
    if not output.parent.is_dir():
        raise PCMAssemblyError("output: parent directory does not exist")
    if not isinstance(tts_wavs, Mapping):
        raise PCMAssemblyError("TTS inputs: expected segment-id to WAV path mapping")
    for segment_id, tts_path in tts_wavs.items():
        if output.resolve() == Path(tts_path).resolve():
            raise PCMAssemblyError(f"output path cannot overwrite TTS {segment_id}")

    layout, tts_meta = _preflight(source, tts_wavs, manifest)
    rate, channels, width = layout
    frame_bytes = channels * width
    temp_path = None
    output_digest = hashlib.sha256()
    second_source_digest = hashlib.sha256()
    translated = protected = spoken = silence = 0
    try:
        fd, temp_path = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".wav.tmp", dir=str(output.parent))
        os.close(fd)
        with wave.open(str(source), "rb") as original, wave.open(str(temp_path), "wb") as rendered:
            if _check_wav(original, "source") != layout or original.getnframes() != manifest.total_samples:
                raise PCMAssemblyError("source: format or length changed during assembly")
            rendered.setnchannels(channels)
            rendered.setsampwidth(width)
            rendered.setframerate(rate)
            rendered.setnframes(manifest.total_samples)
            for span in manifest.spans:
                remaining = span.end_sample - span.start_sample
                if span.action in ("PRESERVE", "REVIEW"):
                    protected += remaining
                else:
                    translated += remaining
                # Every source byte is re-read/hash-checked even for translated regions.
                tts = None
                frames_left = 0
                tts_digest = hashlib.sha256()
                if span.action == "TRANSLATE":
                    path, frames_left, expected_hash = tts_meta[span.segment_id]
                    tts = wave.open(str(path), "rb")
                    if _check_wav(tts, f"TTS {span.segment_id}") != layout or tts.getnframes() != frames_left:
                        tts.close()
                        raise PCMAssemblyError(f"TTS {span.segment_id}: changed during assembly")
                try:
                    while remaining:
                        take = min(remaining, CHUNK_FRAMES)
                        source_data = _read_exact(original, take, frame_bytes, "source")
                        second_source_digest.update(source_data)
                        if tts is None:
                            output_data = source_data
                        else:
                            voice_frames = min(frames_left, take)
                            voice_data = _read_exact(tts, voice_frames, frame_bytes, f"TTS {span.segment_id}")
                            tts_digest.update(voice_data)
                            frames_left -= voice_frames
                            spoken += voice_frames
                            padded = take - voice_frames
                            silence += padded
                            output_data = voice_data + (b"\x00" * (padded * frame_bytes))
                        rendered.writeframesraw(output_data)
                        output_digest.update(output_data)
                        remaining -= take
                    if tts is not None and (frames_left != 0 or tts_digest.hexdigest() != expected_hash):
                        raise PCMAssemblyError(f"TTS {span.segment_id}: content changed during assembly")
                finally:
                    if tts is not None:
                        tts.close()
        if second_source_digest.hexdigest() != manifest.pcm_sha256:
            raise PCMAssemblyError("source: PCM changed during assembly")
        if _check_protected(source, temp_path, manifest) != protected:
            raise PCMAssemblyError("output: protected frame count mismatch")
        # Do not publish anything until the complete WAV and its protected bytes pass checks.
        with open(temp_path, "rb+") as complete:
            os.fsync(complete.fileno())
        os.replace(temp_path, output)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
    return AssemblyReport(output_digest.hexdigest(), manifest.total_samples,
                          translated, protected, spoken, silence)


def main(argv=None):
    """Small model-free CLI for testing a valid decisions.json with synthetic WAVs."""
    parser = argparse.ArgumentParser(description="Offline selective dubbing PCM assembly (no models)")
    parser.add_argument("--source", required=True, help="Original decoded PCM16 WAV")
    parser.add_argument("--decisions", required=True, help="Schema v1 decisions.json")
    parser.add_argument("--output", required=True, help="Output WAV; written atomically")
    parser.add_argument("--tts", action="append", default=[], metavar="SEGMENT_ID=WAV",
                        help="Prepared translated speech WAV (repeat for each TRANSLATE segment)")
    args = parser.parse_args(argv)
    mapping = {}
    for item in args.tts:
        segment_id, separator, path = item.partition("=")
        if not separator or not segment_id or not path or segment_id in mapping:
            parser.error(f"bad or duplicate --tts {item!r}; expected SEGMENT_ID=WAV")
        mapping[segment_id] = path
    try:
        with open(args.decisions, encoding="utf-8") as reader:
            decisions = json.load(reader)
        result = assemble_vocal_wav(args.source, args.output, decisions, mapping)
    except (OSError, EOFError, wave.Error, ValueError) as exc:
        parser.exit(2, f"PCM assembly failed: {exc}\n")
    print(json.dumps(result.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
