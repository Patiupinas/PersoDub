"""Opt-in external VoxCPM2 Russian TTS through the existing engine contract.

The CUDA/Metal dependencies live outside the default PersoDub engine pack.
This adapter uses only HTTP and an immutable server-side Russian voice bank.
"""
import hashlib
import json
import os
from typing import Optional

import httpx

from app.engines.base import SynthesisRequest, SynthesisResult, SynthesisTimeout, TTSEngine
from app.voxcpm2_profile import MODEL_ID, VOXCPM2_PROFILE, VOXCPM2_RU_VOICES


class VoxCPM2RuEngine(TTSEngine):
    id = "voxcpm2_ru"
    display_name = "VoxCPM2 - Russian voices (external experimental)"
    log_name = "VoxCPM2 RU"
    supports_cloning = False
    needs_spoken_numbers = False
    adds_stray_sounds = False
    free_retakes = False

    def __init__(self, base_url: Optional[str] = None):
        self._base_url = base_url

    @property
    def base_url(self):
        return (self._base_url or os.environ.get("PERSODUB_VOXCPM2_URL") or "").rstrip("/")

    def _health(self):
        if not self.base_url:
            raise RuntimeError("Set PERSODUB_VOXCPM2_URL to the opt-in VoxCPM2 server URL")
        response = httpx.get(self.base_url + "/health", timeout=5)
        response.raise_for_status()
        health = response.json()
        if (health.get("ready") is not True
                or health.get("profile") != VOXCPM2_PROFILE
                or health.get("model_id") != MODEL_ID
                or not all(health.get("references", {}).get(voice) for voice in VOXCPM2_RU_VOICES)):
            raise RuntimeError("VoxCPM2 server model/profile/Russian reference bank is not ready")
        return health

    @staticmethod
    def _identity(health):
        data = {
            "profile": health["profile"],
            "model_id": health["model_id"],
            "revision": health.get("model_revision"),
            "references": {name: health["references"][name] for name in VOXCPM2_RU_VOICES},
            "sample_rate": health.get("sample_rate"),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()

    def fingerprint_identity(self):
        return self._identity(self._health())

    def is_available(self):
        try:
            self._health()
            return True
        except (RuntimeError, httpx.HTTPError, ValueError, KeyError, TypeError):
            return False

    def device_label(self):
        try:
            device = self._health().get("device") or "external device"
        except (RuntimeError, httpx.HTTPError, ValueError, KeyError, TypeError):
            return None
        return "VoxCPM2 (" + str(device) + ")"

    def clone(self, ref_audio_path, ref_text=None, mode=None):
        raise NotImplementedError("VoxCPM2 uses the reviewed Russian preset bank, not source timbre")

    def assign_voices(self, refs, speakers, work_dir, log, mode=None, source_registers=None):
        if refs:
            raise ValueError("VoxCPM2 source-voice cloning must remain disabled")
        if source_registers is None or set(source_registers) != set(speakers):
            raise ValueError("VoxCPM2 requires verified source speaking registers for every group")
        bank = {"male": "aidar", "female": "kseniya"}
        if any(register not in bank for register in source_registers.values()):
            raise ValueError("Unverified source speaking register; review before choosing a voice")
        health = self._health()
        choices = {speaker: bank[source_registers[speaker]] for speaker in speakers}
        if len(set(choices.values())) != len(choices):
            raise ValueError("VoxCPM2 pilot has one tested voice per speaking register; multiple same-register speakers need a larger Russian voice bank")
        receipt = {
            "version": 1,
            "engine": self.id,
            "profile": VOXCPM2_PROFILE,
            "engine_identity": self._identity(health),
            "speaker_to_voice": choices,
            "source_registers": source_registers,
            "source_clone": False,
        }
        os.makedirs(work_dir, exist_ok=True)
        destination = os.path.join(work_dir, "russian_voice_assignments.json")
        partial = destination + ".part"
        with open(partial, "w", encoding="utf-8") as stream:
            json.dump(receipt, stream, sort_keys=True, ensure_ascii=False, indent=2)
        os.replace(partial, destination)
        log("   VoxCPM2 source-register-matched Russian voices selected for %d groups" % len(choices))
        return choices

    def synthesize(self, req: SynthesisRequest) -> SynthesisResult:
        if req.language not in (None, "Russian", "ru"):
            raise ValueError("VoxCPM2 pilot supports Russian only")
        if req.voice_id not in VOXCPM2_RU_VOICES:
            raise ValueError("Unknown VoxCPM2 Russian voice preset")
        if not req.text or not req.text.strip():
            raise ValueError("Empty Russian speech script")
        if len(req.text) > 1600:
            raise ValueError("VoxCPM2 Russian speech exceeds 1600 characters")
        self._health()
        wait = req.wait or max(120.0, (req.duration or 0) * 15 + 60)
        try:
            response = httpx.post(
                self.base_url + "/generate",
                data={"text": req.text, "speaker": req.voice_id},
                timeout=wait,
            )
        except httpx.TimeoutException as exc:
            raise SynthesisTimeout(wait) from exc
        response.raise_for_status()
        seconds = response.headers.get("x-audio-duration")
        return SynthesisResult(
            audio_bytes=response.content,
            engine_id=self.id,
            duration=float(seconds) if seconds else None,
            seed=req.seed,
        )
