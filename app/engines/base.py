"""TTS socket specification.

Every TTS engine (Qwen3-TTS, and later MOSS, ChatterBox, etc.) follows this spec.
The rest of the app talks only through this spec, so swapping engines leaves the app unchanged.
"""
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from app.perso_client import _safe_name


def ref_wav_path(work_dir: str, spk: str) -> str:
    """Where a job keeps one speaker's reference clip: the voice is cloned
    from it, and the take scorer, the voice check and a remade line read it
    back from there."""
    return os.path.join(work_dir, "qwen_ref_%s.wav" % _safe_name(spk))


@dataclass
class SynthesisRequest:
    """A single-line speech generation request (what you plug into the socket)."""
    text: str
    ref_audio: Optional[str] = None   # Sample voice path (a location the engine server can read)
    ref_text: Optional[str] = None    # Transcript of the sample voice (audio and text must match)
    voice_id: Optional[str] = None    # Pre-registered voice (skip re-cloning; Qwen /clone-once flow)
    mode: Optional[str] = None        # Qwen voice-clone mode: "timbre" | "icl" (None = engine default)
    language: Optional[str] = None
    duration: Optional[float] = None  # Length (seconds) of the slot this line goes into — a hint
    num_step: int = 32
    guidance_scale: float = 2.0
    speed: float = 1.0
    seed: Optional[int] = None
    wait: Optional[float] = None      # seconds to wait for the answer; None = from the slot


@dataclass
class SynthesisResult:
    """Generation result (what comes out of the socket)."""
    audio_bytes: bytes                # wav binary
    engine_id: str = ""
    duration: Optional[float] = None  # Length (seconds) of the generated audio
    seed: Optional[int] = None


class SynthesisCut(RuntimeError):
    """The engine hit the line's speech-length cap: the model ran away instead
    of finishing the sentence. The audio is not usable (it stops mid-word)."""

    def __init__(self, cut_at: float, slot: Optional[float] = None):
        super().__init__("ran away, cut at %.1fs" % cut_at)
        self.cut_at = cut_at
        self.slot = slot


class SynthesisTimeout(RuntimeError):
    """No answer inside the line's waiting time."""

    def __init__(self, waited: float):
        super().__init__("no answer in %.0fs" % waited)
        self.waited = waited


class VoiceEngineDown(RuntimeError):
    """The voice engine stopped answering altogether (its health probe fails
    after a line timed out). Nothing more can be made this run."""

    def __init__(self, after: str = ""):
        super().__init__("The voice engine stopped responding" + (" after %s" % after if after else ""))
        self.after = after


class TTSEngine:
    """The standard socket a TTS engine must provide. The voice stage
    (app/qwen_pipeline.py) reaches an engine only through these members; an
    engine with no use for one keeps the default here."""
    id: str = ""
    display_name: str = ""
    # The engine's name in the job log ("Qwen synth failed").
    log_name: str = ""
    supports_cloning: bool = False
    # Whether the engine reads digits oddly, so its lines are handed numbers
    # written out the way they are said (app/text/numbers.py).
    needs_spoken_numbers: bool = False
    # Whether a line can come back with a short stray sound before its
    # sentence (app/audio/lead_burst.py), cut off before the line is kept.
    adds_stray_sounds: bool = False
    # Whether making a line again costs nothing but time on this computer.
    # Fast mode then hears every line back and makes the wrong ones again,
    # makes a short line several times, and rewrites lines to fit their slot
    # (app/qwen_pipeline.py: _check_fast_lines, FAST_SHORT_TAKES, fit_to_pace).
    free_retakes: bool = False

    def is_available(self) -> bool:
        """Whether this engine is currently usable."""
        raise NotImplementedError

    def synthesize(self, req: SynthesisRequest) -> SynthesisResult:
        """One line of text -> speech."""
        raise NotImplementedError

    def clone(self, ref_audio_path: str, ref_text: Optional[str] = None, mode: Optional[str] = None) -> str:
        """Register a voice from one reference clip, with the words said in
        it when the clone mode uses them (see SynthesisRequest.mode), and
        return its voice_id. The default assign_voices clones with it."""
        raise NotImplementedError

    def assign_voices(self, refs: Dict[str, dict], speakers: List[str], work_dir: str,
                      log: Callable[[str], None], mode: Optional[str] = None) -> Dict[str, str]:
        """A voice for the speakers of one job, {speaker: voice_id}, from
        their reference clips (refs, app/qwen_pipeline.build_speaker_refs).
        Each clip is written to ref_wav_path first: the take scorer, the voice
        check and a remade line read it there. By default every speaker with
        a clip is cloned from it once (clone), with its words, or from the
        sound alone when it has none; a speaker without a clip gets no
        voice_id."""
        voice_ids = {}
        for spk, ref in refs.items():
            path = ref_wav_path(work_dir, spk)
            with open(path, "wb") as f:
                f.write(ref["wav_bytes"])
            # Words to clone with, or the sound alone when the reference had none.
            voice_ids[spk] = self.clone(path, ref["ref_text"], mode=mode if ref["ref_text"] else "timbre")
        return voice_ids

    def memory_mb(self) -> Optional[int]:
        """The memory the engine holds, in MB; None when it cannot say."""
        return None

    def restart(self) -> None:
        """Start the engine afresh, keeping its voices. Asked only of an
        engine whose memory_mb is over the voice stage's limit, so there is
        nothing to do by default."""

    def device_label(self) -> Optional[str]:
        """The device the engine computes on, in words; None when it cannot say."""
        return None


# --- Engine registry (the list of plugged-in engines) ---
_REGISTRY: Dict[str, TTSEngine] = {}


def register_engine(engine: TTSEngine) -> None:
    _REGISTRY[engine.id] = engine


def get_engine(engine_id: str) -> Optional[TTSEngine]:
    return _REGISTRY.get(engine_id)


def list_engines() -> List[TTSEngine]:
    return list(_REGISTRY.values())
