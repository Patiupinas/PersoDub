"""Source-bound four-second AST audio-event observations for Overdub review.

Run with an isolated Torch/Transformers Python. This reads an already-installed
pinned model locally, produces coarse observations, and never chooses A4 actions.
"""
import argparse
import hashlib
import json
import subprocess
import tempfile
import wave
from pathlib import Path

GROUPS = {
    "speech": ["Speech", "Male speech, man speaking", "Female speech, woman speaking",
               "Conversation", "Narration, monologue", "Whispering"],
    "singing": ["Singing", "Male singing", "Female singing", "Child singing",
                "Humming", "Chant", "Yodeling", "Rapping"],
    "laughing": ["Laughter", "Baby laughter", "Giggle", "Snicker", "Belly laugh", "Chuckle, chortle"],
    "crying_baby": ["Baby cry, infant cry", "Crying, sobbing", "Whimper", "Wail, moan"],
    "coughing": ["Cough", "Throat clearing"],
    "sneezing": ["Sneeze", "Sniff"],
    "breathing": ["Breathing", "Gasp", "Pant", "Wheeze", "Sigh"],
}
MODEL = "MIT/ast-finetuned-audioset-12-12-0.447"
WEIGHTS_SHA = "d87987744d05c134a9f4294568888832b94ad3a9a2d62a3e3a8de5d793eb1918"


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as file:
        for data in iter(lambda: file.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def analyze(source_path, model_path):
    import numpy as np
    import torch
    from transformers import ASTFeatureExtractor, ASTForAudioClassification

    if _sha(Path(model_path) / "model.safetensors") != WEIGHTS_SHA:
        raise ValueError("AST checkpoint SHA does not match tested model weights")
    with wave.open(str(source_path), "rb") as source:
        if (source.getnchannels(), source.getframerate(), source.getsampwidth()) != (2, 48000, 2):
            raise ValueError("Original source must be 48 kHz stereo PCM16")
        total = source.getnframes()
    if not 0 < total <= 1800 * 48000:
        raise ValueError("30 minutes is the maximum AST pilot duration")
    with tempfile.TemporaryDirectory(prefix="persodub-ast-") as scratch:
        wav16 = Path(scratch) / "mono.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(source_path),
             "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav16)],
            check=True, timeout=120, capture_output=True,
        )
        feature = ASTFeatureExtractor.from_pretrained(str(model_path), local_files_only=True)
        network = ASTForAudioClassification.from_pretrained(str(model_path), local_files_only=True).eval()
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        network = network.to(device)
        classes = {str(label): int(key) for key, label in network.config.id2label.items()}
        groups = {kind: [classes[label] for label in labels if label in classes]
                  for kind, labels in GROUPS.items()}
        if any(not ids for ids in groups.values()):
            raise ValueError("AST model has incompatible label ontology")
        result = []
        with wave.open(str(wav16), "rb") as wav:
            n = wav.getnframes()
            window, stride = 64000, 32000
            starts = list(range(0, max(1, n - window + 1), stride))
            if n > window and starts[-1] < n - window:
                starts.append(n - window)
            for offset in starts:
                wav.setpos(offset)
                pcm = wav.readframes(min(window, n - offset))
                audio = np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768
                inputs = feature(audio, sampling_rate=16000, return_tensors="pt")
                with torch.inference_mode():
                    logits = network(inputs.input_values.to(device)).logits[0].float()
                    scores_all = torch.sigmoid(logits).cpu().numpy()
                scores = {kind: round(float(max(scores_all[ids])), 6)
                          for kind, ids in groups.items()}
                result.append({
                    "start_frame": offset * 3,
                    "end_frame": min(total, (offset + len(audio)) * 3),
                    "scores": scores,
                })
    return {
        "schema_version": 1, "source_wav_sha256": _sha(source_path),
        "sample_rate": 48000, "total_frames": total, "model": MODEL,
        "model_weights_sha256": WEIGHTS_SHA, "windows": result,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.resolve() == args.original.resolve():
        raise ValueError("Output must be new and distinct from the source")
    out = analyze(args.original, args.model_dir)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(out, file, indent=2)
        file.write("\n")
    print(json.dumps({"windows": len(out["windows"]), "model": MODEL}))


if __name__ == "__main__":
    main()
