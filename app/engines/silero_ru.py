"""Experimental fixed-Russian TTS backend using the existing local sidecar.

No original-sound samples or English-accent cloning. A source speaker group
gets a fixed Russian model voice for the whole job, including long lectures.
"""
import json
import os
import re
from typing import Optional

import httpx

from app import runtime
from app.engines.base import (
    SynthesisRequest,
    SynthesisResult,
    SynthesisTimeout,
    TTSEngine,
)
from app.speaker_voice_plan import SILERO_RU_V56

_VOICE_GROUP = re.compile(r"^VOICE_(\d+)$")


class SileroRuEngine(TTSEngine):
    id = "silero_ru"
    display_name = "Silero v5.6 - Russian voice presets (experimental)"
    log_name = "Silero RU"
    supports_cloning = False
    needs_spoken_numbers = False
    adds_stray_sounds = False
    free_retakes = False

    def __init__(self, base_url: Optional[str] = None):
        self._base_url = base_url

    @property
    def base_url(self):
        return (self._base_url or runtime.url("tts")).rstrip("/")

    def is_available(self):
        try:
            r = httpx.get(self.base_url + "/silero/health", timeout=5)
            return r.status_code == 200 and r.json().get("available") is True
        except (httpx.HTTPError, ValueError):
            return False

    def device_label(self):
        return "CPU (Russian fixed voices)"

    def clone(self, ref_audio_path, ref_text=None, mode=None):
        raise NotImplementedError("Silero fixed Russian voices do not clone source audio")

    def assign_voices(self, refs, speakers, work_dir, log, mode=None, source_registers=None):
        choices = {}
        if source_registers is not None:
            if set(source_registers) != set(speakers):
                raise ValueError("Missing source speaking register for a Silero voice group")
            bank = {
                "male": ("aidar", "eugene"),
                "female": ("kseniya", "xenia", "baya"),
            }
            counts = {"male": 0, "female": 0}
            for speaker in speakers:
                register = source_registers[speaker]
                if register not in bank or counts[register] >= len(bank[register]):
                    raise ValueError("Insufficient confirmed Russian voices for source speaking register")
                choices[speaker] = bank[register][counts[register]]
                counts[register] += 1
        else:
            # Keep the original direct-call contract; production passes
            # source-register evidence from the dubbing pipeline.
            for i, speaker in enumerate(speakers):
                match = _VOICE_GROUP.fullmatch(speaker)
                index = int(match.group(1)) - 1 if match else i
                if index < 0:
                    raise ValueError("invalid dubbing voice group")
                choices[speaker] = SILERO_RU_V56[index % len(SILERO_RU_V56)]
        report = {
            "version": 1,
            "engine": self.id,
            "speaker_to_voice": choices,
            "source_registers": source_registers,
            "source_clone": False,
        }
        os.makedirs(work_dir, exist_ok=True)
        final = os.path.join(work_dir, "russian_voice_assignments.json")
        pending = final + ".part"
        with open(pending, "w", encoding="utf-8") as fd:
            json.dump(report, fd, indent=2, ensure_ascii=False)
        os.replace(pending, final)
        log("   fixed Russian voices assigned to %d source voice group(s)" % len(choices))
        return choices

    def synthesize(self, req: SynthesisRequest) -> SynthesisResult:
        if req.language not in (None, "Russian", "ru"):
            raise ValueError("Silero RU supports Russian only")
        if req.voice_id not in SILERO_RU_V56:
            raise ValueError("unknown Russian voice preset")
        wait = req.wait or max(90.0, (req.duration or 0) * 10 + 45)
        try:
            response = httpx.post(
                self.base_url + "/silero/generate",
                data={"text": req.text, "speaker": req.voice_id},
                timeout=wait,
            )
        except httpx.TimeoutException as exc:
            raise SynthesisTimeout(wait) from exc
        response.raise_for_status()
        raw_duration = response.headers.get("x-audio-duration")
        return SynthesisResult(
            audio_bytes=response.content,
            engine_id=self.id,
            duration=float(raw_duration) if raw_duration else None,
            seed=req.seed,
        )
