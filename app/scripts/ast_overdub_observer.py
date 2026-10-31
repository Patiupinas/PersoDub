"""Source-bound AST observations for long-form Overdub review.

Decode source audio once with FFmpeg and consume a bounded 4-second PCM
window with a 2-second step. No whole-recording 16-kHz WAV or audio array is
kept in RAM. The result is still a collection of *unapproved* model hints.
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
AST_RATE = 16000
WINDOW_SAMPLES = AST_RATE * 4
STRIDE_SAMPLES = AST_RATE * 2
SAMPLE_BYTES = 2


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as file:
        for data in iter(lambda: file.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


def _windows(chunks, *, window_samples=WINDOW_SAMPLES, stride_samples=STRIDE_SAMPLES):
    """Yield bounded overlapping mono PCM16 windows with a right-aligned tail.

    The final full window is aligned to the source ending when the remaining
    samples do not fill a normal stride. This is the same time grid as the
    original AST pilot's 4s/2s seek-based WAV implementation.
    """
    if not 0 < stride_samples <= window_samples:
        raise ValueError("Invalid AST window/stride")
    width = window_samples * SAMPLE_BYTES
    step = stride_samples * SAMPLE_BYTES
    buffer = bytearray()
    tail = bytearray()
    total = 0
    start = 0
    last_full_start = -1
    for chunk in chunks:
        if len(chunk) % SAMPLE_BYTES:
            raise ValueError("Misaligned 16-bit PCM in AST decoder")
        if not chunk:
            continue
        total += len(chunk) // SAMPLE_BYTES
        buffer.extend(chunk)
        tail.extend(chunk)
        if len(tail) > width:
            del tail[:-width]
        while len(buffer) >= width:
            yield start, bytes(buffer[:width])
            last_full_start = start
            del buffer[:step]
            start += stride_samples
    if total == 0:
        raise ValueError("AST decoder returned no audio samples")
    if total < window_samples:
        yield 0, bytes(tail)
    elif last_full_start < total - window_samples:
        # Keep the final four seconds even when the last 2-second hop is partial.
        yield total - window_samples, bytes(tail)


def _ffmpeg_pcm_chunks(source_path):
    """Stream the whole recording without a temp mono WAV or a wall-clock cap."""
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(source_path),
        "-map", "0:a:0", "-vn", "-ar", str(AST_RATE),
        "-ac", "1", "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1",
    ]
    # Errors go to a disk-backed spool so a noisy multi-hour source cannot
    # fill an unread stderr pipe and block the FFmpeg stdout decoder.
    with tempfile.TemporaryFile(mode="w+b") as errors, subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=errors,
    ) as proc:
        assert proc.stdout is not None
        try:
            yield from iter(lambda: proc.stdout.read(65536), b"")
            if proc.wait() != 0:
                errors.seek(0, 2)
                errors.seek(max(0, errors.tell() - 300))
                reason = errors.read().decode("utf-8", errors="replace")
                raise RuntimeError("FFmpeg AST audio decode failed: " + reason)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


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
    if total <= 0:
        raise ValueError("Original source audio is empty")
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
    for offset, pcm in _windows(_ffmpeg_pcm_chunks(source_path)):
        audio = np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768
        inputs = feature(audio, sampling_rate=AST_RATE, return_tensors="pt")
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
