"""Source-speaker VoxCPM2 Russian TTS with the owner's selected expression.

Keeps source samples local, outside Git and outside the external TTS service.
Uses the existing TTSEngine voice assignment and source-clock pipeline.
"""
import hashlib
import json
import os
import wave
from pathlib import Path

import httpx

from app.engines.base import SynthesisRequest, SynthesisResult, SynthesisTimeout, TTSEngine
from app.voxcpm2_profile import (
    MODEL_ID,
    MODEL_REVISION,
    VOXCPM2_EXPRESSIVE_PROFILE,
    VOXCPM2_PROFILE,
)


class VoxCPM2ExpressiveRuEngine(TTSEngine):
    id = "voxcpm2_expressive_ru"
    display_name = "VoxCPM2 - source voice + expressive Russian"
    log_name = "VoxCPM2 expressive RU"
    supports_cloning = True
    needs_spoken_numbers = False
    adds_stray_sounds = False
    free_retakes = False

    def __init__(self, base_url=None):
        self._base_url = base_url
        self._source_refs = {}

    @property
    def base_url(self):
        return (self._base_url or os.environ.get("PERSODUB_VOXCPM2_URL") or "").rstrip("/")

    def _health(self):
        if not self.base_url:
            raise RuntimeError("Set PERSODUB_VOXCPM2_URL for expressive VoxCPM2 source cloning")
        result = httpx.get(self.base_url + "/health", timeout=5)
        result.raise_for_status()
        state = result.json()
        if (state.get("ready") is not True
                or state.get("profile") != VOXCPM2_PROFILE
                or state.get("model_id") != MODEL_ID
                or state.get("model_revision") != MODEL_REVISION
                or state.get("source_voice_clone_profile") != VOXCPM2_EXPRESSIVE_PROFILE
                or state.get("sample_rate") != 48000):
            raise RuntimeError("VoxCPM2 source-clone expression service/profile is unavailable")
        return state

    def fingerprint_identity(self):
        state = self._health()
        record = {
            "engine": self.id,
            "model_id": state["model_id"],
            "model_revision": state["model_revision"],
            "service_profile": state["profile"],
            "expression_profile": state["source_voice_clone_profile"],
            "sample_rate": state["sample_rate"],
        }
        return hashlib.sha256(json.dumps(record, sort_keys=True).encode("utf-8")).hexdigest()

    def is_available(self):
        try:
            self._health()
            return True
        except (RuntimeError, httpx.HTTPError, ValueError, KeyError, TypeError):
            return False

    def device_label(self):
        try:
            device = self._health().get("device")
        except (RuntimeError, httpx.HTTPError, ValueError, KeyError, TypeError):
            return None
        return "VoxCPM2 expressive (%s)" % device if device else None

    def clone(self, ref_audio_path, ref_text=None, mode=None):
        """Register one reviewed source-speaker WAV by content, not by label."""
        path = Path(ref_audio_path).resolve()
        try:
            with wave.open(str(path), "rb") as audio:
                duration = audio.getnframes() / audio.getframerate()
                if (not 3 <= duration <= 15 or audio.getnchannels() not in (1, 2)
                        or audio.getsampwidth() != 2
                        or audio.getframerate() not in (16000, 24000, 48000)):
                    raise ValueError("VoxCPM2 source voice requires 3-15 s PCM16 WAV (16, 24 or 48 kHz)")
        except (wave.Error, EOFError) as error:
            raise ValueError("VoxCPM2 source voice is not a valid WAV") from error
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        voice_id = "source-sha256:" + sha
        self._source_refs[voice_id] = str(path)
        return voice_id

    def assign_voices(self, refs, speakers, work_dir, log, mode=None,
                      source_registers=None):
        if set(refs) != set(speakers):
            missing = sorted(set(speakers) - set(refs))
            raise ValueError("VoxCPM2 source cloning requires a 4-7 s voice sample for each speaker: "
                             + ", ".join(missing))
        if not speakers:
            raise ValueError("VoxCPM2 source cloning requires at least one speaker")
        identity = self.fingerprint_identity()
        assignments = super().assign_voices(refs, speakers, work_dir, log, mode=mode)
        receipt = {
            "version": 1,
            "engine": self.id,
            "source_clone": True,
            "engine_identity": identity,
            "expression_profile": VOXCPM2_EXPRESSIVE_PROFILE,
            "speaker_to_voice": assignments,
        }
        path = Path(work_dir) / "source_voice_clone_assignments.json"
        part = path.with_name(path.name + ".part")
        try:
            part.write_text(json.dumps(receipt, sort_keys=True, indent=2), encoding="utf-8")
            os.replace(part, path)
        finally:
            if part.exists():
                part.unlink()
        log("   VoxCPM2 expressive source samples registered for %d speakers" % len(assignments))
        return assignments

    def synthesize(self, req: SynthesisRequest) -> SynthesisResult:
        if req.language not in (None, "Russian", "ru"):
            raise ValueError("VoxCPM2 expressive source cloning supports Russian only")
        if not req.text or not req.text.strip() or len(req.text) > 1600:
            raise ValueError("VoxCPM2 Russian line requires 1-1600 characters")
        if req.voice_id not in self._source_refs:
            raise ValueError("Unknown source voice reference; register speaker first")
        self._health()
        path = Path(self._source_refs[req.voice_id])
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        if req.voice_id != "source-sha256:" + sha:
            raise ValueError("Source voice WAV changed after speaker assignment")
        wait = req.wait or max(120.0, (req.duration or 0) * 15 + 60)
        data = {"text": req.text, "source_sha256": sha}
        if req.seed is not None:
            data["seed"] = str(req.seed)
        try:
            result = httpx.post(
                self.base_url + "/generate-clone",
                data=data,
                files={"reference_audio": (path.name, raw, "audio/wav")},
                timeout=wait,
            )
        except httpx.TimeoutException as error:
            raise SynthesisTimeout(wait) from error
        result.raise_for_status()
        if result.headers.get("x-source-voice-sha256") != sha:
            raise ValueError("VoxCPM2 clone response does not match the requested speaker")
        duration = result.headers.get("x-audio-duration")
        return SynthesisResult(
            audio_bytes=result.content,
            engine_id=self.id,
            duration=float(duration) if duration else None,
            seed=req.seed,
        )
