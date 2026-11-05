"""Infer a broad speaking-voice register from short source-only speech excerpts.

Executed in the already installed engines Python, not the lightweight API
venv. The result is a coarse male/female-sounding TTS preset routing hint,
not a claim about a person's identity or biological sex.
"""
import argparse
import json
import math

import numpy as np
import soundfile as sf


def analyze(path, samples):
    import librosa

    answers = {}
    with sf.SoundFile(path) as source:
        if source.samplerate < 8000 or source.channels not in (1, 2):
            raise ValueError("Unsupported source audio for voice-register analysis")
        for speaker, spans in samples.items():
            pitch_quartiles = []
            evidence = []
            for span in spans[:3]:
                start = float(span["start"])
                end = float(span["end"])
                if not (math.isfinite(start) and math.isfinite(end)
                        and 0 <= start < end <= source.frames / source.samplerate):
                    raise ValueError("Invalid bounded source speaker span")
                first = round(start * source.samplerate)
                count = round((end - start) * source.samplerate)
                if count < round(1.0 * source.samplerate):
                    continue
                source.seek(first)
                signal = source.read(count, dtype="float32", always_2d=True).mean(axis=1)
                signal = librosa.resample(signal, orig_sr=source.samplerate, target_sr=16000)
                f0, voiced, _ = librosa.pyin(
                    signal, fmin=65.4, fmax=450, sr=16000,
                    frame_length=2048, hop_length=256, fill_na=np.nan,
                )
                good = f0[np.isfinite(f0)]
                voiced_ratio = float(good.size / max(len(f0), 1))
                if good.size < 24 or voiced_ratio < 0.25:
                    continue
                pitch_quartiles.append(float(np.percentile(good, 25)))
                evidence.append({"start": start, "end": end,
                                 "p25_hz": round(pitch_quartiles[-1], 2),
                                 "voiced_ratio": round(voiced_ratio, 3)})
            # Use lower quartiles from multiple snippets rather than a single
            # median: an instructor can sing high notes inside speech cues.
            q25 = float(np.median(pitch_quartiles)) if pitch_quartiles else None
            answers[speaker] = {
                "register": "male" if q25 is not None and q25 <= 150.0 else (
                    "female" if q25 is not None and q25 >= 170.0 else "review"),
                "speech_pitch_p25_hz": round(q25, 2) if q25 is not None else None,
                "evidence": evidence,
            }
    return answers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    with open(args.input, encoding="utf-8") as stream:
        payload = json.load(stream)
    result = analyze(payload["vocals_wav_path"], payload["samples"])
    with open(args.output, "w", encoding="utf-8") as stream:
        json.dump({"version": 1, "speakers": result}, stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
