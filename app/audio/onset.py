"""Where each line's speech really begins on the separated vocals track.

Measured 2026-10-03: Whisper put 15 of 49 line starts 0.15 s or more before
the speech (6 by 0.3 s or more, the first Trump line by 0.94 s), so the dub
spoke before the mouth moved; Perso's transcript, 2 of 42. Each machine
transcript's starts are moved forward to the speech, never back (a line
must not reach into the one before), the way VoiceStudio's onset_align does:

  - speech begins at the first FRAME_SEC frame louder than REL of the
    line's loudest frame that SUSTAIN_MIN_SEC of the next SUSTAIN_WIN_SEC
    stays above too -- a click or a footstep dies sooner;
  - a shift under MIN_SHIFT_SEC is timing noise and left alone, and a line
    is never left shorter than MIN_LINE_SEC;
  - a shift past MAX_QUIET_JUMP_SEC is taken only over near-silence: quiet
    speech under the threshold is still speech.

Read a window at a time from the wav, so a long video's vocals are never
held whole. Same stdlib-only audio policy as app/qwen_assemble.py.
"""
import audioop
import os
import wave
from typing import List

FRAME_SEC = 0.02
REL = 0.10
SUSTAIN_WIN_SEC = 0.30
SUSTAIN_MIN_SEC = 0.16
PRE_ROLL_SEC = 0.05
MIN_SHIFT_SEC = 0.15
MIN_LINE_SEC = 0.30
MAX_QUIET_JUMP_SEC = 1.0
QUIET_REL = 0.03     # "near-silence" for a long jump: under 3% of the line's loudest frame


def _frames_rms(w, start: float, end: float) -> List[int]:
    """RMS of each FRAME_SEC frame of the mono mix of [start, end) seconds."""
    rate, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
    first = max(0, int(start * rate))
    count = max(0, min(w.getnframes(), int(end * rate)) - first)
    if count <= 0:
        return []
    w.setpos(first)
    pcm = w.readframes(count)
    if ch == 2:
        pcm = audioop.tomono(pcm, sw, 0.5, 0.5)
    elif ch != 1:
        return []
    hop = max(1, int(FRAME_SEC * rate)) * sw
    return [audioop.rms(pcm[i:i + hop], sw) for i in range(0, len(pcm) - hop + 1, hop)]


def speech_start(w, start: float, end: float) -> float:
    """Seconds from `start` to where the speech of [start, end) begins
    (PRE_ROLL_SEC before it), or 0.0 when it should stay where it is."""
    rms = _frames_rms(w, start, end)
    if len(rms) < 3 or max(rms) <= 0:
        return 0.0
    peak = max(rms)
    on = [r > REL * peak for r in rms]
    win, need = int(round(SUSTAIN_WIN_SEC / FRAME_SEC)), int(round(SUSTAIN_MIN_SEC / FRAME_SEC))
    first = next((i for i in range(len(rms)) if on[i] and sum(on[i:i + win]) >= need), None)
    if first is None:
        return 0.0
    shift = max(0.0, first * FRAME_SEC - PRE_ROLL_SEC)
    if shift < MIN_SHIFT_SEC or (end - start) - shift < MIN_LINE_SEC:
        return 0.0
    if shift > MAX_QUIET_JUMP_SEC and max(rms[:first]) > QUIET_REL * peak:
        return 0.0
    return shift


def snap_starts(cues: List[dict], vocals_path: str) -> int:
    """Move each cue's start, in place, to where its speech begins on the
    vocals track. Returns how many moved; 0 when the track cannot be read."""
    if not vocals_path or not os.path.exists(vocals_path):
        return 0
    moved = 0
    try:
        with wave.open(vocals_path, "rb") as w:
            for c in cues:
                shift = speech_start(w, float(c["start"]), float(c["end"]))
                if shift:
                    c["start"] = round(float(c["start"]) + shift, 3)
                    moved += 1
    except (wave.Error, EOFError, audioop.error):
        return moved
    return moved
