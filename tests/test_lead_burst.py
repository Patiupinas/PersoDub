"""app/audio/lead_burst.py: the short sound Qwen3-TTS sometimes puts before a
line's sentence (9 of 139 lines in finished dubs, 2026-10-01). Synthetic wavs."""
import io
import math
import struct
import wave

from app.audio import lead_burst as lb

RATE = 24000


def _wav(parts, rate=RATE):
    """Mono 16-bit wav from (seconds, amplitude) parts: a 220Hz tone, or silence at 0."""
    frames = b""
    for sec, amp in parts:
        frames += b"".join(struct.pack("<h", int(amp * math.sin(2 * math.pi * 220 * i / rate)))
                           for i in range(int(rate * sec)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return buf.getvalue()


def _seconds(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getnframes() / w.getframerate()


def test_burst_then_quiet_then_sentence_is_cut_to_the_sentence():
    # The measured shape: 0.2s of sound, 0.6s quiet, then the sentence.
    raw = _wav([(0.2, 4000), (0.6, 0), (1.5, 9000)])
    out, cut = lb.cut_lead_burst(raw, "Me siento inmensamente orgulloso.")
    assert 0.7 <= cut <= 0.8
    assert abs(_seconds(out) - (2.3 - cut)) < 0.01


def test_a_line_that_starts_with_its_sentence_is_left_whole():
    raw = _wav([(1.5, 9000), (0.5, 0), (0.8, 9000)])
    assert lb.cut_lead_burst(raw, "Hello there. How are you?") == (raw, 0.0)


def test_a_long_first_sound_is_not_a_burst():
    raw = _wav([(0.7, 9000), (0.5, 0), (1.5, 9000)])
    assert lb.cut_lead_burst(raw, "Everything changed after that day")[1] == 0.0


def test_a_short_pause_is_not_enough():
    raw = _wav([(0.2, 9000), (0.2, 0), (1.5, 9000)])
    assert lb.cut_lead_burst(raw, "So that was the plan")[1] == 0.0


def test_a_short_word_with_a_quieter_breath_after_it_is_kept():
    # "Go." then a breath: what follows the quiet is neither louder nor longer.
    raw = _wav([(0.3, 9000), (0.5, 0), (0.4, 2000)])
    assert lb.cut_lead_burst(raw, "Go")[1] == 0.0


def test_a_pause_the_text_asks_for_is_left_alone():
    raw = _wav([(0.2, 4000), (0.6, 0), (1.5, 9000)])
    for text in ("Oh, I see what you mean.", "네, 알겠어요.", "Wait... what?", "はい、そうです。"):
        assert lb.cut_lead_burst(raw, text)[1] == 0.0, text


def test_the_mark_that_ends_the_line_does_not_count():
    assert lb.pause_after_opening("Yes.") is False
    assert lb.pause_after_opening("Hey you, come here") is True
    assert lb.pause_after_opening("그게 뭐야?") is False


def test_audio_that_is_not_a_mono_wav_comes_back_unchanged():
    assert lb.cut_lead_burst(b"WAVnot really", "hello there") == (b"WAVnot really", 0.0)


# --- cut_edge_sounds: a sound right before or after the sentence (2026-10-02) --

def test_a_quiet_sound_and_a_dip_before_the_sentence_is_cut():
    # Measured shape: 0.1s of sound 10-20 dB under the line, 0.2-0.3s of dip.
    raw = _wav([(0.12, 2000), (0.24, 0), (1.5, 9000)])
    out, lead, tail = lb.cut_edge_sounds(raw, "come here now", "English")
    assert abs(lead - (0.36 - lb.KEEP_BEFORE_SEC)) < 0.03 and tail == 0.0
    assert abs(_seconds(out) - (1.5 + lb.KEEP_BEFORE_SEC)) < 0.03
    assert lb.edge_sound_too_close(raw, "come here now", "English") is False


def test_a_sound_closer_than_the_gap_is_not_cut_but_flagged():
    # "Com-paring" (2026-10-07): the first syllable, a 0.1s closure, the loud
    # rest. The shape of a stray sound, so the line is made again, not cut.
    raw = _wav([(0.12, 2000), (0.12, 0), (1.5, 9000)])
    assert lb.cut_edge_sounds(raw, "come here now", "English") is None
    assert lb.edge_sound_too_close(raw, "come here now", "English") is True
    # ...at the end as well, and a line with no edge sound is not flagged.
    assert lb.edge_sound_too_close(_wav([(1.5, 9000), (0.12, 0), (0.28, 1500)]), "come here now", "English") is True
    assert lb.edge_sound_too_close(_wav([(1.5, 9000)]), "come here now", "English") is False
    assert lb.edge_sound_too_close(b"WAVnot really", "come here now", "English") is False


def test_a_quiet_sound_after_the_sentence_is_cut():
    raw = _wav([(1.5, 9000), (0.26, 0), (0.28, 1500)])
    out, lead, tail = lb.cut_edge_sounds(raw, "come here now", "English")
    assert lead == 0.0 and abs(tail - (0.54 - lb.KEEP_BEFORE_SEC)) < 0.03
    assert abs(_seconds(out) - (1.5 + lb.KEEP_BEFORE_SEC)) < 0.03


def test_a_first_word_as_loud_as_the_sentence_is_not_an_edge_sound():
    assert lb.cut_edge_sounds(_wav([(0.15, 9000), (0.12, 0), (1.5, 9000)]), "come here now", "English") is None


def test_a_long_first_word_is_not_an_edge_sound():
    assert lb.cut_edge_sounds(_wav([(0.4, 2000), (0.12, 0), (1.5, 9000)]), "come here now", "English") is None


def test_a_dip_too_short_or_too_shallow_is_part_of_the_sentence():
    assert lb.cut_edge_sounds(_wav([(0.12, 2000), (0.04, 0), (1.5, 9000)]), "come here now", "English") is None
    assert lb.cut_edge_sounds(_wav([(0.12, 2000), (0.12, 600), (1.5, 9000)]), "come here now", "English") is None


def test_a_sound_whose_dip_reaches_15_db_below_it_is_cut():
    # The measured line (2026-10-03): the dip went 18 dB under the sound, short
    # of the 20 dB asked before, and the sound was heard as "will".
    raw = _wav([(0.1, 2000), (0.24, 250), (1.5, 9000)])
    assert lb.cut_edge_sounds(raw, "come here now", "English")[1] > 0


def test_a_line_without_edge_sounds_or_not_mono_comes_back_as_none():
    assert lb.cut_edge_sounds(_wav([(1.5, 9000)]), "come here now", "English") is None
    assert lb.cut_edge_sounds(b"WAVnot really", "come here now", "English") is None


def test_a_short_word_the_text_sets_off_is_left_alone():
    before = _wav([(0.12, 2000), (0.24, 0), (1.5, 9000)])
    after = _wav([(1.5, 9000), (0.26, 0), (0.28, 1500)])
    assert lb.cut_edge_sounds(before, "네, 알겠어요", "Korean") is None
    assert lb.cut_edge_sounds(after, "Thank you so much, Ana.", "English") is None
    assert lb.cut_edge_sounds(after, "네, 지금 바로 갈게요", "Korean")[2] > 0     # the other end is still looked at
    # A longer word before the pause cannot be a sound this short.
    assert lb.cut_edge_sounds(before, "아나야, 멋진 소개 고마워요.", "Korean")[1] > 0


# --- No line starts or stops with a click (2026-10-06) -----------------------

def _first_ms_peak(wav_bytes, ms, from_end=False):
    with wave.open(io.BytesIO(wav_bytes)) as w:
        n = int(w.getframerate() * ms / 1000)
        frames = w.readframes(w.getnframes())
    samples = struct.unpack("<%dh" % (len(frames) // 2), frames)
    part = samples[-n:] if from_end else samples[:n]
    return max(abs(x) for x in part)


def test_a_line_that_starts_at_full_loudness_fades_in_and_out():
    # A Jobs line began at 79% of its loudest within 5 ms (2026-10-06): heard
    # as a "pop" like a bottle opening. 10 ms of fade takes the edge off and
    # leaves the word.
    raw = _wav([(1.0, 9000)])
    raw = raw[:44] + b"".join(struct.pack("<h", 9000) for _ in range(len(raw[44:]) // 2))
    out = lb.fade_edges(raw)
    assert _first_ms_peak(out, 1) < 1000
    assert _first_ms_peak(out, 1, from_end=True) < 1000
    assert abs(_seconds(out) - 1.0) < 0.001
    assert _first_ms_peak(out[:44] + out[44 + 2 * 480:], 1) == 9000   # past 10 ms it is untouched


def test_audio_that_is_not_a_mono_wav_is_not_faded():
    assert lb.fade_edges(b"not a wav") == b"not a wav"


# --- Pieces set apart at a line's edges (2026-10-06) -------------------------

def test_a_piece_set_apart_before_the_sentence_is_found():
    # Sebasi line 8: 0.6 s of "(보)입니다", 0.5 s quiet, then the English line.
    raw = _wav([(0.6, 6000), (0.5, 0), (2.0, 9000)])
    pieces = lb.edge_pieces(raw)
    assert len(pieces) == 1
    a, b = pieces[0]
    assert a < 0.05 and abs(b - 0.6) < 0.05


def test_a_line_said_in_one_go_has_no_edge_pieces():
    assert lb.edge_pieces(_wav([(0.1, 0), (2.0, 9000), (0.1, 0)])) == []


def test_a_long_first_part_is_not_an_edge_piece():
    assert lb.edge_pieces(_wav([(1.5, 9000), (0.5, 0), (1.5, 9000)])) == []
