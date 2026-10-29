"""Generate and verify a reproducible, model-free selective-dubbing demonstration.

Synthetic oscillators are NOT real speech, singing, or trained model output.
Their only purpose is to prove sample-level handoff between the decision
contract, PCM assembler and safety benchmark without external dependencies.
"""

import argparse
import hashlib
import json
import math
import struct
import wave
from pathlib import Path

from app.vocal_benchmark import score_vocal_decisions
from app.vocal_pcm import assemble_vocal_wav, verify_preserved_wav

RATE = 48000
CHANNELS = 2
SECONDS = 4
FRAME_BYTES = CHANNELS * 2


def _tone_frames(frequency, count, amplitude, *, start=0):
    """Produce bounded deterministic stereo PCM16 tone chunks."""
    for offset in range(0, count, 4096):
        frames = min(4096, count - offset)
        pcm = bytearray()
        for index in range(offset, offset + frames):
            sample = round(amplitude * math.sin(2 * math.pi * frequency * (start + index) / RATE))
            pcm.extend(struct.pack("<hh", sample, -sample // 2))
        yield bytes(pcm)


def _write_wav(path, frequencies, frame_counts):
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(CHANNELS)
        writer.setsampwidth(2)
        writer.setframerate(RATE)
        start = 0
        for frequency, count in zip(frequencies, frame_counts):
            for chunk in _tone_frames(frequency, count, 7000, start=start):
                writer.writeframesraw(chunk)
            start += count


def _source_hashes(path):
    file_sha = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(262144), b""):
            file_sha.update(chunk)
    raw_sha = hashlib.sha256()
    with wave.open(str(path), "rb") as reader:
        for _ in range(0, reader.getnframes(), 4096):
            raw_sha.update(reader.readframes(4096))
    return file_sha.hexdigest(), raw_sha.hexdigest()


def _gold(source_sha, pcm_sha):
    return {
        "schema_version": 1,
        "source_sha256": source_sha,
        "pcm_sha256": pcm_sha,
        "sample_rate": RATE,
        "total_samples": SECONDS * RATE,
        "model_revisions": {"classifier": "manual-synthetic-demo-v1"},
        "segments": [
            {
                "segment_id": "intro-and-vowel",
                "start_sample": 0,
                "end_sample": 3 * RATE,
                "action": "MIXED",
                "children": [
                    {"segment_id": "speech-de", "start_sample": 0, "end_sample": RATE,
                     "action": "TRANSLATE", "source_language": "de", "source_text": "Jetzt ein A."},
                    {"segment_id": "sung-a", "start_sample": RATE, "end_sample": 2 * RATE,
                     "action": "PRESERVE", "reason": "synthetic sustained vowel placeholder"},
                    {"segment_id": "speech-en", "start_sample": 2 * RATE, "end_sample": 3 * RATE,
                     "action": "TRANSLATE", "source_language": "en", "source_text": "Sing this."},
                ],
            },
            {"segment_id": "uncertain-overlap", "start_sample": 3 * RATE,
             "end_sample": 4 * RATE, "action": "REVIEW",
             "reason": "synthetic ambiguous demonstration placeholder"},
        ],
    }


def _unsafe(gold):
    """Make a semantically wrong prediction that translates ONE protected frame."""
    from copy import deepcopy

    predicted = deepcopy(gold)
    predicted["model_revisions"] = {"classifier": "intentionally-unsafe-demo-v1"}
    children = predicted["segments"][0]["children"]
    children[1]["end_sample"] = 2 * RATE - 1
    children[2]["start_sample"] = 2 * RATE - 1
    return predicted


def create_demo(directory):
    """Produce synthetic WAV/JSON and execute both independent safety checks.

    The target directory must be nonexistent or empty. Nothing in it is
    downloaded or derived from commercial recordings or third-party voices.
    """
    folder = Path(directory)
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        raise FileExistsError(f"refusing to overwrite non-empty directory: {folder}")
    folder.mkdir(parents=True, exist_ok=True)

    original = folder / "original.synthetic.wav"
    out = folder / "dubbed.synthetic.wav"
    tts1 = folder / "speech-de.synthetic.wav"
    tts2 = folder / "speech-en.synthetic.wav"
    _write_wav(original, [220, 440, 330, 110], [RATE] * SECONDS)
    _write_wav(tts1, [600], [RATE // 2])
    _write_wav(tts2, [720], [RATE * 3 // 4])

    source_sha, pcm_sha = _source_hashes(original)
    gold = _gold(source_sha, pcm_sha)
    predicted_good = _gold(source_sha, pcm_sha)
    predicted_good["model_revisions"] = {"classifier": "intentionally-safe-demo-v1"}
    predicted_unsafe = _unsafe(gold)

    manifests = {
        "gold.synthetic.json": gold,
        "predicted-safe.synthetic.json": predicted_good,
        "predicted-unsafe.synthetic.json": predicted_unsafe,
    }
    for filename, data in manifests.items():
        (folder / filename).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    tts = {"speech-de": tts1, "speech-en": tts2}
    assembly = assemble_vocal_wav(original, out, predicted_good, tts)
    verified = verify_preserved_wav(original, out, gold)
    good = score_vocal_decisions(gold, predicted_good)
    bad = score_vocal_decisions(gold, predicted_unsafe)
    if verified != 2 * RATE or good["vocal_preservation"]["wrongly_translated_samples"] != 0:
        raise RuntimeError("synthetic demo failed preservation verification")
    if bad["vocal_preservation"]["wrongly_translated_samples"] != 1:
        raise RuntimeError("synthetic unsafe example was not detected")
    report = {
        "schema_version": 1,
        "note": "synthetic tones, not actual speech/vocal audio or classifier results",
        "output_pcm_sha256": assembly.output_pcm_sha256,
        "source_sha256": source_sha,
        "pcm_sha256": pcm_sha,
        "frames": assembly.total_samples,
        "protected_frames_verified": verified,
        "translated_frames": assembly.translated_samples,
        "tts_audio_frames": assembly.tts_audio_samples,
        "silence_padding_frames": assembly.silence_padding_samples,
        "safe_wrongly_translated_vocal_frames": good["vocal_preservation"]["wrongly_translated_samples"],
        "unsafe_wrongly_translated_vocal_frames": bad["vocal_preservation"]["wrongly_translated_samples"],
    }
    (folder / "report.synthetic.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                                   encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create a fully local synthetic vocal preservation demo")
    parser.add_argument("--directory", type=Path, required=True, help="New/empty folder for generated WAV+JSON")
    args = parser.parse_args(argv)
    try:
        result = create_demo(args.directory)
    except (OSError, ValueError, RuntimeError, wave.Error) as exc:
        parser.exit(2, f"Offline demo failed: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
