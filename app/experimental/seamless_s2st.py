"""Isolated SeamlessM4T v2 speech-to-Russian-audio experimental provider.

No translated text or transcript is used as an intermediate artifact.
The source is one short utterance, never an entire unsegmented lecture.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
import wave
from pathlib import Path

MODEL_ID = "facebook/seamless-m4t-v2-large"
MODEL_REVISION = "5f8cc790b19fc3f67a61c105133b20b34e3dcb76"
MAX_INPUT_SECONDS = 30.0
INPUT_SAMPLE_RATE = 16000
WEIGHT_FILES = (
    "model-00001-of-00002.safetensors",
    "model-00002-of-00002.safetensors",
)
REQUIRED_FILES = (
    "config.json", "generation_config.json", "preprocessor_config.json",
    "tokenizer.model", "model.safetensors.index.json",
) + WEIGHT_FILES


def sha256_file(path):
    sha = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def verify_model(model_dir):
    """Use the pinned architecture and complete local shards, never network."""
    root = Path(model_dir).expanduser().resolve()
    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        raise ValueError("Incomplete SeamlessM4T model: " + ", ".join(missing))
    with (root / "config.json").open(encoding="utf-8") as source:
        config = json.load(source)
    if config.get("model_type") != "seamless_m4t_v2":
        raise ValueError("Incorrect SeamlessM4T model architecture")
    if any((root / name).stat().st_size <= 0 for name in REQUIRED_FILES):
        raise ValueError("Empty model file")
    return {"model_id": MODEL_ID, "revision": MODEL_REVISION,
            "weights_bytes": sum((root / name).stat().st_size for name in WEIGHT_FILES)}


def decode_utterance(source):
    """Bound decoding to <=30 seconds and return 16-kHz mono float32 PCM."""
    import numpy as np

    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError("Source clip is missing")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    duration = float(probe.stdout.strip())
    if not math.isfinite(duration) or not (0 < duration <= MAX_INPUT_SECONDS):
        raise ValueError("Single utterance must be at most 30 seconds")
    command = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
               "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(INPUT_SAMPLE_RATE),
               "-f", "f32le", "-c:a", "pcm_f32le", "pipe:1"]
    proc = subprocess.run(command, capture_output=True, timeout=75, check=True)
    if not (160 <= len(proc.stdout) <= MAX_INPUT_SECONDS * INPUT_SAMPLE_RATE * 4 + 4):
        raise ValueError("Decoded speech length is invalid")
    if len(proc.stdout) % 4:
        raise ValueError("FFmpeg produced unaligned PCM")
    waveform = np.frombuffer(proc.stdout, dtype="<f4").copy()
    if not np.isfinite(waveform).all():
        raise ValueError("Source contains non-finite samples")
    return waveform, len(waveform) / INPUT_SAMPLE_RATE


class SeamlessSession:
    """Reuse one MPS model across many bounded speech utterances."""

    def __init__(self, model_dir, device):
        import torch
        from transformers import AutoProcessor, SeamlessM4Tv2Model

        if device not in ("mps", "cpu"):
            raise ValueError("Expected mps or cpu")
        if device == "mps" and not torch.backends.mps.is_available():
            raise RuntimeError("Apple MPS unavailable")
        self.device = device
        self.model_dir = Path(model_dir).expanduser().resolve()
        verify_model(self.model_dir)
        self.torch = torch
        self.processor = AutoProcessor.from_pretrained(
            str(self.model_dir), local_files_only=True,
        )
        self.model = SeamlessM4Tv2Model.from_pretrained(
            str(self.model_dir), dtype=torch.float32,
            low_cpu_mem_usage=True, local_files_only=True,
        ).eval().to(device)
        self.sample_rate = int(self.model.config.sampling_rate)

    def __call__(self, audio, model_dir, device):
        """Translate one speech sample without retaining any text output."""
        import numpy as np

        if device != self.device or Path(model_dir).resolve() != self.model_dir:
            raise ValueError("Reused model has different device or checkpoint")
        inputs = self.processor(audio=audio, sampling_rate=INPUT_SAMPLE_RATE,
                                return_tensors="pt")
        inputs = {key: value.to(device) for key, value in inputs.items()}
        with self.torch.inference_mode():
            generated = self.model.generate(**inputs, tgt_lang="rus")
        signal = generated[0].detach().to("cpu").float().numpy().reshape(-1)
        if not signal.size or not np.isfinite(signal).all():
            raise RuntimeError("Model generated empty or non-finite audio")
        return signal, self.sample_rate

    def close(self):
        """Release the model explicitly before starting other GPU experiments."""
        model = self.model
        self.model = None
        del model
        if self.device == "mps":
            self.torch.mps.empty_cache()


def infer_speech(audio, model_dir, device):
    """Single-utterance convenience entrypoint; batches reuse SeamlessSession."""
    session = SeamlessSession(model_dir, device)
    try:
        return session(audio, model_dir, device)
    finally:
        session.close()


def run(source, destination, model_dir, device="mps", report=None, infer=None):
    """Generate exactly one new WAV and immutable input/output fingerprints."""
    import numpy as np

    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    model_dir = Path(model_dir).expanduser().resolve()
    if destination == source or destination.exists():
        raise FileExistsError("Result WAV must not overwrite existing data")
    if report:
        report = Path(report).expanduser().resolve()
        if report in (source, destination) or report.exists():
            raise FileExistsError("Report must be a new separate path")
    model = verify_model(model_dir)
    audio, source_duration = decode_utterance(source)
    start = time.monotonic()
    signal, rate = (infer or infer_speech)(audio, model_dir, device)
    signal = np.asarray(signal, dtype=np.float32).reshape(-1)
    if not signal.size or not np.isfinite(signal).all():
        raise ValueError("Output contains no finite samples")
    if rate not in (16000, 22050, 24000, 44100, 48000):
        raise ValueError("Unsupported output sampling rate")
    if np.max(np.abs(signal)) > 1.001:
        raise ValueError("Output PCM is outside the normalized range")
    inference_seconds = time.monotonic() - start
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Keep the stage dependency-free: PCM16 audio is enough for the mixer
    # and independent language/voice benchmark.
    encoded = np.rint(np.clip(signal, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(destination), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(encoded.tobytes())
    result = {
        "provider": "seamless-m4t-v2",
        "model_id": model["model_id"], "model_revision": model["revision"],
        "model_weights_bytes": model["weights_bytes"],
        "source_sha256": sha256_file(source),
        "output_sha256": sha256_file(destination),
        "source_seconds": round(source_duration, 5),
        "output_seconds": round(len(signal) / rate, 5),
        "sample_rate": rate, "device": device,
        "inference_seconds": round(inference_seconds, 3),
        "realtime_factor": round(inference_seconds / source_duration, 3),
        "external_intermediate_text_used": False,
        "architecture_uses_internal_text_tokens": True,
        "voice_cloning_performed": False,
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open("x", encoding="utf-8") as out:
            json.dump(result, out, indent=2, ensure_ascii=False)
            out.write("\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--device", choices=("mps", "cpu"), default="mps")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check-model", action="store_true")
    args = parser.parse_args(argv)
    if args.check_model:
        print(json.dumps(verify_model(args.model_dir), indent=2))
        return 0
    result = run(args.source, args.out, args.model_dir,
                 device=args.device, report=args.report)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
