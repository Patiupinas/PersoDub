"""Fit each dubbed line to its slot by the speaker's real pace (Fast mode).

The translation is sized before any voice exists, from a fixed speaking rate
per language (app/text/length_fit.py). Once the lines are voiced, each
speaker's real pace is known: letters (or syllables) per second of speech.
A line that ends well before its slot ends leaves dead air on moving lips;
one that runs well past it is sped up or cut. Those lines are written again
to the length the slot holds at that speaker's pace, voiced again, and the
new take is kept only when it lands closer to the slot.

Meaning comes first: the translator is told to keep the meaning and change
only the wording; a rewrite that grows or shrinks the line by more than
MAX_CHANGE is not used, and neither is one that does not land closer.
"""
from typing import Dict, List, Optional, Sequence

from app.text.dub_prompt import ask_with_retry, register_rule, script_ok
from app.text.length_fit import _BANS, NO_BUDGET_SLOT_S, _unit
from app.text.srt import _SYL_PER_SEC, _count_syllables

# A line is fine when it ends no more than EARLY_S before its slot ends and
# no more than LATE_S after (the assembly's lead borrow and small speed-up
# absorb that much).
EARLY_S = 0.25
LATE_S = 0.5
ROUNDS = 2
MAX_CHANGE = 0.4          # a rewrite may change the line's length by at most this
ASK_CHANGE = 0.35         # ...and is asked for at most this, to leave room
MIN_PACE_SPEECH_S = 4.0   # less speech than this says little about a pace
REWRITE_CHUNK = 40        # lines per ask: one ask for a short video, bounded for a long one
MIN_GAIN_S = 0.1          # new words for less than this much closer are not worth the risk


def miss(dur: float, slot: float) -> float:
    """Seconds outside the window around the slot; 0 inside it."""
    if dur < slot - EARLY_S:
        return slot - EARLY_S - dur
    if dur > slot + LATE_S:
        return dur - slot - LATE_S
    return 0.0


def worse_voice(old: float, new: float, slot: float) -> Optional[str]:
    """Why the new voicing is not kept over the old one, or None when it is.
    A line that was short is never traded for one that runs long: a long
    line is sped up or cut, a short one only leaves a pause."""
    if miss(new, slot) > miss(old, slot) - MIN_GAIN_S:
        return "not closer"
    if old < slot and new > slot + LATE_S:
        return "now runs long"
    return None


def measure_pace(texts: Sequence[str], durs: Sequence[float], speakers: Sequence[Optional[str]],
                 lang: str) -> Dict[Optional[str], float]:
    """Letters (syllables) per second of speech for each speaker, over the
    voiced lines. A speaker with too little speech takes everyone's pace;
    with too little speech in all, the language's table pace."""
    count: Dict[Optional[str], int] = {}
    secs: Dict[Optional[str], float] = {}
    total_n, total_s = 0, 0.0
    for t, d, s in zip(texts, durs, speakers):
        n = _count_syllables(t, lang) if t and t.strip() else 0
        if n <= 0 or not d or d <= 0:
            continue
        count[s] = count.get(s, 0) + n
        secs[s] = secs.get(s, 0.0) + d
        total_n, total_s = total_n + n, total_s + d
    overall = (total_n / total_s if total_s >= MIN_PACE_SPEECH_S
               else _SYL_PER_SEC.get(lang.lower(), 5.0))
    return {s: count[s] / secs[s] if secs.get(s, 0.0) >= MIN_PACE_SPEECH_S else overall
            for s in set(speakers)}


def pick_lines(texts: Sequence[str], durs: Sequence[Optional[float]],
               slots: Sequence[float]) -> List[int]:
    """The lines worth writing again: voiced, with words, a slot long enough
    to hold a phrase, and outside the window."""
    return [i for i, (t, d, s) in enumerate(zip(texts, durs, slots))
            if t and t.strip() and d and s >= NO_BUDGET_SLOT_S and miss(d, s) > 0]


def target_count(slot: float, pace: float, current: int) -> int:
    """How many letters (syllables) the slot holds at this pace, kept within
    ASK_CHANGE of the line as it is."""
    want = int(round(slot * pace))
    lo = max(1, int(round(current * (1 - ASK_CHANGE))))
    hi = int(round(current * (1 + ASK_CHANGE)))
    return max(lo, min(hi, want))


def usable_rewrite(old: str, new: Optional[str], lang: str) -> Optional[str]:
    """Why a rewrite cannot be used, or None when it can. Letters of another
    script are refused only when the line had none: a name the translator
    kept in English stays, a stray English word it slips in does not
    (ChatGPT offered "usual한" for a Korean line, 2026-10-02)."""
    if not new or not new.strip():
        return "no answer"
    if new.strip() == old.strip():
        return "unchanged"
    a, b = _count_syllables(old, lang), _count_syllables(new, lang)
    if a and abs(b - a) / float(a) > MAX_CHANGE:
        return "length changed %d%%" % round(100 * (b - a) / float(a))
    if not script_ok(new, lang) and script_ok(old, lang):
        return "wrong script"
    return None


def build_rewrite_prompt(sources: Sequence[str], currents: Sequence[str], targets: Sequence[int],
                         lang: str) -> str:
    u = _unit(lang)
    lines = []
    for k, (src, cur, n) in enumerate(zip(sources, currents, targets)):
        have = _count_syllables(cur, lang)
        how = "make it shorter" if n < have else "make it fuller"
        lines.append("%d. Source: %s\n   Current: %s\n   (%d %s now; %s, about %d %s)"
                     % (k + 1, src or "(not available)", cur, have, u, how, n, u))
    return (
        "You are adjusting a %s dubbing script so each line fills the time the speaker talks. "
        "Each line below has its source line, the current translation, and a target length.\n"
        "Rewrite the current translation to about the target length. Keep EXACTLY the meaning of "
        "the source: do not add facts, names, numbers, examples or ideas that are not in it, and "
        "do not drop any. Change only the wording: a fuller or a tighter way of saying the same "
        "thing. If the target cannot be reached without changing the meaning, get as close as you "
        "can and keep the meaning.\n"
        "Keep each line natural spoken dubbing, in the same tone. Do not merge or split lines.\n"
        % lang
        + register_rule(lang)
        + _BANS
        + "Output only a JSON array containing exactly %d strings in order. No other text.\n\n%s"
        % (len(currents), "\n".join(lines))
    )


def ask_rewrites(translator, sources: Sequence[str], currents: Sequence[str],
                 targets: Sequence[int], lang: str) -> List[Optional[str]]:
    """One ask per REWRITE_CHUNK lines. A chunk whose answer cannot be read
    gets None for each of its lines: they keep what they have."""
    tries = translator.format_tries
    out: List[Optional[str]] = []
    for a in range(0, len(currents), REWRITE_CHUNK):
        b = a + REWRITE_CHUNK
        prompt = build_rewrite_prompt(sources[a:b], currents[a:b], targets[a:b], lang)
        try:
            out.extend(ask_with_retry(translator.ask, prompt, len(currents[a:b]), tries))
        except ValueError:
            out.extend([None] * len(currents[a:b]))
    return out


def source_for(seg: dict, source_cues: Sequence[dict]) -> str:
    """The source words a dubbed line says: the source lines whose middle
    falls inside it, else the one it overlaps most (a long line split in
    pieces)."""
    s, e = seg["start"], seg["end"]
    inside = [c["text"] for c in source_cues if s <= (c["start"] + c["end"]) / 2.0 < e]
    if inside:
        return " ".join(inside)
    best, most = "", 0.0
    for c in source_cues:
        ov = min(e, c["end"]) - max(s, c["start"])
        if ov > most:
            best, most = c["text"], ov
    return best
