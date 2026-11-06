"""Standalone opt-in VoxCPM2 Russian inference service; no desktop dependency."""

import hashlib
import io
import os
import tempfile
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.voxcpm2_profile import (
    MODEL_ID,
    MODEL_REVISION,
    STYLE_PREFIX,
    VOXCPM2_EXPRESSIVE_PREFIX,
    VOXCPM2_EXPRESSIVE_PROFILE,
    VOXCPM2_PROFILE,
    VOXCPM2_RU_VOICES,
)

MODEL_REPO = MODEL_ID
_generate_lock = threading.Lock()


def _reference_paths():
    directory = os.environ.get("PERSODUB_VOXCPM2_REFS")
    if not directory:
        raise RuntimeError("Set PERSODUB_VOXCPM2_REFS to the Russian WAV directory")
    refs = {name: Path(directory) / (name + ".wav") for name in VOXCPM2_RU_VOICES}
    for name, path in refs.items():
        if not path.is_file():
            raise FileNotFoundError("Missing Russian voice reference: " + str(path))
        with sf.SoundFile(str(path)) as wave:
            if wave.channels != 1 or not 4 <= wave.frames / wave.samplerate <= 30:
                raise ValueError("Invalid Russian reference audio for " + name)
    return refs


def _sha256(path):
    hash_value = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hash_value.update(chunk)
    return hash_value.hexdigest()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from huggingface_hub import snapshot_download
    from voxcpm import VoxCPM

    references = _reference_paths()
    snapshot = snapshot_download(repo_id=MODEL_REPO, revision=MODEL_REVISION)
    device = os.environ.get("PERSODUB_VOXCPM2_DEVICE") or "cpu"
    if device not in ("cpu", "mps", "cuda"):
        raise ValueError("Unsupported VoxCPM2 inference device")
    app.state.model = VoxCPM.from_pretrained(
        snapshot, load_denoiser=False, device=device, optimize=False
    )
    app.state.device = device
    app.state.references = references
    app.state.reference_sha256 = {name: _sha256(path) for name, path in references.items()}
    try:
        yield
    finally:
        app.state.model = None


app = FastAPI(lifespan=lifespan, title="PersoDub VoxCPM2 RU pilot")


@app.get("/health")
def health():
    model = getattr(app.state, "model", None)
    return {
        "ready": model is not None,
        "profile": VOXCPM2_PROFILE,
        "model_id": MODEL_REPO,
        "model_revision": MODEL_REVISION,
        "device": getattr(app.state, "device", None),
        "references": getattr(app.state, "reference_sha256", {}),
        "sample_rate": model.tts_model.sample_rate if model is not None else None,
        "source_voice_clone_profile": VOXCPM2_EXPRESSIVE_PROFILE,
    }


@app.post("/generate")
async def generate(text: str = Form(...), speaker: str = Form(...)):
    if speaker not in VOXCPM2_RU_VOICES:
        raise HTTPException(422, "Unknown Russian preset")
    if not text.strip() or len(text) > 1600:
        raise HTTPException(422, "Russian speech text length must be 1-1600 characters")
    if getattr(app.state, "model", None) is None:
        raise HTTPException(503, "VoxCPM2 model is not ready")

    def speak():
        # Match the exact style and inference settings of the rated experiment.
        with _generate_lock:
            samples = app.state.model.generate(
                text=STYLE_PREFIX + text,
                reference_wav_path=str(app.state.references[speaker]),
                cfg_value=2.0,
                inference_timesteps=10,
            )
        samples = np.asarray(samples).reshape(-1)
        if not samples.size or not np.isfinite(samples).all():
            raise RuntimeError("VoxCPM2 returned invalid audio")
        sample_rate = int(app.state.model.tts_model.sample_rate)
        with io.BytesIO() as data:
            sf.write(data, samples, sample_rate, format="WAV", subtype="PCM_16")
            return data.getvalue(), samples.size / sample_rate

    wav, seconds = await run_in_threadpool(speak)
    return Response(
        content=wav, media_type="audio/wav",
        headers={"x-audio-duration": f"{seconds:.3f}"},
    )


@app.post("/generate-clone")
async def generate_clone(
    text: str = Form(...),
    source_sha256: str = Form(...),
    reference_audio: UploadFile = File(...),
    seed: int = Form(None),
):
    """Speak Russian in the actual source voice with owner-selected expression.

    The reference is uploaded as bounded WAV bytes rather than a path into
    arbitrary service-local files. No source sample is persisted by the server.
    """
    if not text.strip() or len(text) > 1600:
        raise HTTPException(422, "Russian speech text length must be 1-1600 characters")
    if getattr(app.state, "model", None) is None:
        raise HTTPException(503, "VoxCPM2 model is not ready")
    raw = await reference_audio.read(8 * 1024 * 1024 + 1)
    if not raw or len(raw) > 8 * 1024 * 1024 or raw[:4] != b"RIFF":
        raise HTTPException(422, "Source reference must be a bounded WAV file")
    digest = hashlib.sha256(raw).hexdigest()
    if source_sha256 != digest:
        raise HTTPException(422, "Uploaded source voice has a different SHA256")
    try:
        with sf.SoundFile(io.BytesIO(raw)) as clip:
            duration = clip.frames / clip.samplerate
            if (clip.format != "WAV" or clip.channels not in (1, 2)
                    or clip.samplerate not in (16000, 24000, 48000)
                    or clip.subtype != "PCM_16" or not 3 <= duration <= 15):
                raise ValueError("Voice source requires 3-15 seconds PCM16, mono/stereo")
    except (RuntimeError, ValueError) as error:
        raise HTTPException(422, str(error)) from error

    def speak():
        # Match the exact listener-selected prompt and model inference steps.
        # A closed, isolated directory supports reopening the WAV on both
        # Windows and macOS. NamedTemporaryFile may deny reopen on Windows.
        with tempfile.TemporaryDirectory(prefix="persodub-clone-") as directory:
            reference = Path(directory) / "source.wav"
            reference.write_bytes(raw)
            with _generate_lock:
                if seed is not None:
                    import torch

                    torch.manual_seed(seed)
                    np.random.seed(seed % (2 ** 32))
                samples = app.state.model.generate(
                    text=VOXCPM2_EXPRESSIVE_PREFIX + text,
                    reference_wav_path=str(reference),
                    cfg_value=2.0,
                    inference_timesteps=10,
                )
        signal = np.asarray(samples).reshape(-1)
        if not signal.size or not np.isfinite(signal).all():
            raise RuntimeError("VoxCPM2 clone returned invalid audio")
        sample_rate = int(app.state.model.tts_model.sample_rate)
        with io.BytesIO() as output:
            sf.write(output, signal, sample_rate, format="WAV", subtype="PCM_16")
            return output.getvalue(), signal.size / sample_rate

    wav, seconds = await run_in_threadpool(speak)
    return Response(
        content=wav, media_type="audio/wav",
        headers={
            "x-audio-duration": f"{seconds:.3f}",
            "x-source-voice-sha256": digest,
            "x-expression-profile": VOXCPM2_EXPRESSIVE_PROFILE,
        },
    )
