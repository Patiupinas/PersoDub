"""A short sound Qwen3-TTS sometimes puts before a line's sentence.

Measured 2026-10-01: 9 of 139 Qwen lines in finished dubs (6.5%) opened with
a 0.10-0.50s sound in the cloned voice, then 0.3-1.5s of near-silence, then
the sentence. The lead trim keeps it (it is not silence), so the dub opened
with a stray syllable in the original speaker's voice and the sentence came
late. It is no word: Whisper found none in any of them.

Found on the line's own loudness, 20ms at a time: the first stretch of sound
lasts at most BURST_MAX_SEC, the quiet after it at least GAP_MIN_SEC, and more
sound follows. The line is then cut to start just before that sound.

A short first word followed by a pause in the text ("Oh, ...", "네, ...")
looks the same, so when the opening words carry a pause mark the line is
left whole. Same stdlib-only audio policy as app/qwen_assemble.py.

Measured 2026-10-02: more often the quiet after such a sound is short, 0.08
to 0.3s, and the sound sits at the line's very start or, once, its end. Placed
right after the line before, it is heard as an "아!" or "어!" after that line,
or as a stutter ("어-제가"). 74 of 189 Qwen lines in nine finished dubs had
one. A short first word before a stop ("that", "학") can look the same, so
cut_edge_sounds only proposes the cut; the Fast check keeps it when Whisper
hears the line at least as well without it (app/qwen_pipeline.py).
"""
import audioop
import io
import math
import re
import wave
from array import array
from typing import List, Optional, Tuple

from app.text.srt import _count_syllables

HOP_SEC = 0.02
BURST_MAX_SEC = 0.5
GAP_MIN_SEC = 0.3
FLOOR_DB = -48.0     # quieter than this is silence whatever the line's level
REL_DB = 32.0        # ...and so is anything this far below the line's peak
KEEP_BEFORE_SEC = 0.05   # cut this much before the sentence, so its onset stays whole

# A sound at either end of a line (cut_edge_sounds): at most EDGE_MAX_SEC
# long, then a dip at least DIP_DB below it for DIP_MIN_SEC that reaches
# DEEP_DB below it, then the sentence, whose first 0.2s is LOUDER_DB louder.
# DEEP_DB was 20 until 2026-10-03: a sound whose dip reached 18 dB below it
# was kept and heard as "will" before a Korean line. Over 474 lines made in two
# days, 15 proposes 23 more cuts; the Fast check keeps 15 of them, and in none
# does Whisper hear a word less ("of a who was president" became "who was
# president", "Wow, the incident" "The incident").
EDGE_MAX_SEC = 0.3
DIP_DB = 10.0
DIP_MIN_SEC = 0.08
DEEP_DB = 15.0
LOUDER_DB = 4.0

_MARKS = ",.!?;:…、，。！？"
_PAUSE_MARK = re.compile("[%s]" % re.escape(_MARKS))


def pause_after_opening(text: str) -> bool:
    """True when the text itself pauses within its first two words (or first
    four characters, for a language written without spaces). The mark that
    ends the whole line does not count."""
    t = text.strip().rstrip(_MARKS + " ")
    words = t.split()
    head = " ".join(words[:2]) if len(words) > 1 else t[:4]
    return bool(_PAUSE_MARK.search(head))


def short_word_set_off(text: str, language: str, at_end: bool) -> bool:
    """True when the text's first (or, at_end, last) word has at most two
    syllables and a pause mark sets it off from the rest ("네, ...", "Oh,
    ...", "..., Ana."): said with its pause, it looks like an edge sound."""
    words = text.strip().rstrip(_MARKS + " ").split()
    if len(words) < 2:
        return False
    word, marked = (words[-1], words[-2]) if at_end else (words[0], words[0])
    return marked[-1] in _MARKS and _count_syllables(word, language) <= 2


def _env_db(pcm: bytes, sampwidth: int, framerate: int) -> List[float]:
    """Loudness in dB below full scale, HOP_SEC at a time."""
    hop = max(1, int(framerate * HOP_SEC)) * sampwidth
    full = float((1 << (8 * sampwidth - 1)) - 1)
    return [20 * math.log10(max(audioop.rms(pcm[i:i + hop], sampwidth) / full, 1e-9))
            for i in range(0, len(pcm) - hop + 1, hop)]


def burst_end(pcm: bytes, sampwidth: int, framerate: int) -> float:
    """Seconds into mono PCM where the sentence starts after a leading burst,
    or 0.0 when the line has none. The sound after the quiet must be the
    line's loudest and last at least twice the burst: a short last word
    with a breath after it is not a burst before a sentence."""
    env = _env_db(pcm, sampwidth, framerate)
    if not env:
        return 0.0
    thr = max(FLOOR_DB, max(env) - REL_DB)
    loud = [i for i, e in enumerate(env) if e > thr]
    gap_hops = int(round(GAP_MIN_SEC / HOP_SEC))
    for a, b in zip(loud, loud[1:]):
        burst = (a + 1 - loud[0]) * HOP_SEC
        if burst > BURST_MAX_SEC:
            return 0.0
        if b - a > gap_hops:
            rest = sum(1 for h in loud if h >= b) * HOP_SEC
            if max(env[b:]) >= max(env[:a + 1]) and rest >= 2 * burst:
                return max(0.0, b * HOP_SEC - KEEP_BEFORE_SEC)
            return 0.0
    return 0.0


def _read_mono(wav_bytes: bytes):
    """(params, pcm) of a mono wav, or None for anything else."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            params = w.getparams()
            pcm = w.readframes(w.getnframes())
    except (wave.Error, EOFError):
        return None
    return (params, pcm) if params.nchannels == 1 else None


def _wav_bytes(params, pcm: bytes) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        # The frame count is the one written, never the one read: a wav ffmpeg
        # wrote to a pipe says "unknown" there, a count no header can hold.
        w.setparams(params._replace(nframes=0))
        w.writeframes(pcm)
    return out.getvalue()


# Every made line fades in and out over this much: a line the voice engine
# began at 79% of its loudest within 5 ms (Jobs, 2026-10-06) was heard as a
# "pop" like a bottle opening. 10 ms takes the edge off and leaves the word.
FADE_SEC = 0.01


def fade_edges(wav_bytes: bytes) -> bytes:
    """The line with FADE_SEC of linear fade at its start and end. A wav this
    module cannot read (not mono 16-bit) is returned as it is."""
    read = _read_mono(wav_bytes)
    if read is None or read[0].sampwidth != 2:
        return wav_bytes
    params, pcm = read
    samples = array("h", pcm)
    n = min(int(FADE_SEC * params.framerate), len(samples) // 2)
    for k in range(n):
        samples[k] = int(samples[k] * k / n)
        samples[-1 - k] = int(samples[-1 - k] * k / n)
    return _wav_bytes(params, samples.tobytes())


# A piece of sound at a line's start or end set apart from the rest by at
# least PIECE_GAP_SEC of quiet and no longer than PIECE_MAX_SEC: where a voice
# sample's own last words land when the clone says them (Sebasi line 8,
# 0.6 s of "(보)입니다" then 0.5 s quiet, 2026-10-06).
PIECE_GAP_SEC = 0.25
PIECE_MAX_SEC = 1.2


def edge_pieces(wav_bytes: bytes) -> List[Tuple[float, float]]:
    """(start, end) seconds of the pieces set apart at the start and at the
    end of a mono line, at most one each; [] when there are none or the wav
    cannot be read. Loud means the same floor as everywhere in this module."""
    read = _read_mono(wav_bytes)
    if read is None:
        return []
    params, pcm = read
    env = _env_db(pcm, params.sampwidth, params.framerate)
    if not env:
        return []
    thr = max(FLOOR_DB, max(env) - REL_DB)
    loud = [i for i, e in enumerate(env) if e > thr]
    gap = int(round(PIECE_GAP_SEC / HOP_SEC))
    runs = []
    for h in loud:
        if runs and h - runs[-1][1] <= gap:
            runs[-1][1] = h
        else:
            runs.append([h, h])
    if len(runs) < 2:
        return []
    # With one gap, the shorter side is the piece and the other the sentence.
    ends = [min(runs, key=lambda r: r[1] - r[0])] if len(runs) == 2 else [runs[0], runs[-1]]
    return [(a * HOP_SEC, (b + 1) * HOP_SEC) for a, b in ends if (b + 1 - a) * HOP_SEC <= PIECE_MAX_SEC]


def piece_wav(wav_bytes: bytes, start: float, end: float) -> bytes:
    """The part of a mono wav between start and end seconds."""
    params, pcm = _read_mono(wav_bytes)
    w = params.sampwidth
    return _wav_bytes(params, pcm[int(start * params.framerate) * w:int(end * params.framerate) * w])


def tidy_reference(wav_bytes: bytes) -> bytes:
    """A voice reference cut to its speech: the same loudness floor as the
    bursts above decides where speech starts and ends. No silence is put back
    on either side: with 0.25 s of it (2026-10-03) the anchor briefing's lines
    came out as different people, 9 of 18 under 0.5 like the speaker against
    0 of 18 for the same span unpadded (2026-10-06). A wav this module cannot
    read is returned as it is."""
    got = _read_mono(wav_bytes)
    if got is None:
        return wav_bytes
    params, pcm = got
    env = _env_db(pcm, params.sampwidth, params.framerate)
    if not env:
        return wav_bytes
    thr = max(FLOOR_DB, max(env) - REL_DB)
    loud = [i for i, e in enumerate(env) if e > thr]
    if not loud:
        return wav_bytes
    hop = max(1, int(params.framerate * HOP_SEC)) * params.sampwidth
    return _wav_bytes(params, pcm[loud[0] * hop:(loud[-1] + 1) * hop])


def cut_lead_burst(wav_bytes: bytes, text: str) -> Tuple[bytes, float]:
    """(wav bytes starting at the sentence, seconds cut). Unchanged, with 0.0,
    when there is no burst, the text may pause there, or the audio is not a
    mono wav this can read."""
    if pause_after_opening(text):
        return wav_bytes, 0.0
    read = _read_mono(wav_bytes)
    if read is None:
        return wav_bytes, 0.0
    params, pcm = read
    cut = burst_end(pcm, params.sampwidth, params.framerate)
    if cut <= 0:
        return wav_bytes, 0.0
    return _wav_bytes(params, pcm[int(cut * params.framerate) * params.sampwidth:]), cut


# A sound whose gap to the sentence is shorter than this is not cut: a word's
# weak first syllable looks just the same ("Com-paring": the p's closure is a
# 0.08-0.16 s dip, 2026-10-07), and the cut took "Com". Of 134 proposed cuts,
# 35 had a gap under 0.2 s: 8 were a syllable, 27 a sound, and no shape told
# them apart. Such a line is made again instead (edge_sound_too_close).
CUT_GAP_MIN_SEC = 0.2


def _sentence_after_sound(env: List[float]) -> Tuple[int, int]:
    """(hop where the sentence starts after a short, quieter sound and a deep
    dip at the start of env (see EDGE_MAX_SEC), hops of dip between them), or
    (0, 0) when there is none. A dip shorter than DIP_MIN_SEC is still part
    of the sound."""
    thr = max(FLOOR_DB, max(env, default=FLOOR_DB) - REL_DB)
    s = next((i for i, e in enumerate(env) if e > thr), None)
    if s is None:
        return 0, 0
    head = env[s]
    dip_hops = int(round(DIP_MIN_SEC / HOP_SEC))
    k = s + 1
    while k < len(env):
        if env[k] > head - DIP_DB:
            head = max(head, env[k])
            j = k + 1
        else:
            j = k
            while j < len(env) and env[j] <= head - DIP_DB:
                j += 1
            if j - k >= dip_hops:
                after = env[j:j + int(round(0.2 / HOP_SEC))]
                if after and min(env[k:j]) <= head - DEEP_DB and max(after) >= head + LOUDER_DB:
                    return j, j - k
                return 0, 0
        if (j - s) * HOP_SEC > EDGE_MAX_SEC:
            return 0, 0
        k = j
    return 0, 0


def _edge_sounds(wav_bytes: bytes, text: str, language: str):
    """The sounds at both ends: (params, pcm, env, (lead hop, gap hops),
    (tail hop, gap hops)), or None for audio this cannot read. An end where
    the text sets off a short word (short_word_set_off) is (0, 0)."""
    read = _read_mono(wav_bytes)
    if read is None:
        return None
    params, pcm = read
    env = _env_db(pcm, params.sampwidth, params.framerate)
    lead = (0, 0) if short_word_set_off(text, language, at_end=False) else _sentence_after_sound(env)
    tail = (0, 0) if short_word_set_off(text, language, at_end=True) else _sentence_after_sound(env[::-1])
    return params, pcm, env, lead, tail


def _too_close(end: Tuple[int, int]) -> bool:
    return bool(end[0]) and end[1] * HOP_SEC < CUT_GAP_MIN_SEC


def edge_sound_too_close(wav_bytes: bytes, text: str, language: str) -> bool:
    """True when a sound at either end sits closer to the sentence than
    CUT_GAP_MIN_SEC: it may be part of a word, so the line is not cut there
    but made again."""
    found = _edge_sounds(wav_bytes, text, language)
    return found is not None and (_too_close(found[3]) or _too_close(found[4]))


def cut_edge_sounds(wav_bytes: bytes, text: str, language: str) -> Optional[Tuple[bytes, float, float]]:
    """(wav bytes without the short sound before and after the sentence,
    seconds cut at the start, seconds cut at the end), or None when the line
    has neither or is not a mono wav. The sentence keeps KEEP_BEFORE_SEC of
    quiet on the cut side. An end where the text sets off a short word
    (short_word_set_off), or whose sound is too close to cut
    (edge_sound_too_close), is left alone."""
    found = _edge_sounds(wav_bytes, text, language)
    if found is None:
        return None
    params, pcm, env, lead_end, tail_end = found
    lead = 0 if _too_close(lead_end) else lead_end[0]
    tail = 0 if _too_close(tail_end) else tail_end[0]
    if not (lead or tail):
        return None
    total = len(pcm) / float(params.sampwidth * params.framerate)
    start = max(0.0, lead * HOP_SEC - KEEP_BEFORE_SEC) if lead else 0.0
    end = min(total, (len(env) - tail) * HOP_SEC + KEEP_BEFORE_SEC) if tail else total
    a = int(start * params.framerate) * params.sampwidth
    b = int(end * params.framerate) * params.sampwidth
    return _wav_bytes(params, pcm[a:b]), start, total - end
