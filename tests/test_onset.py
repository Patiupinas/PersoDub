"""Where each line's speech really begins on the separated vocals (2026-10-03).
Whisper put 15 of 49 line starts 0.15 s or more before the speech (0.94 s on
the first Trump line), and the dub spoke before the mouth moved."""
import math
import struct
import wave

from app.audio import onset

RATE = 48000


def _vocals(tmp_path, parts, channels=2):
    """A 16-bit vocals wav from (seconds, amplitude) parts: a 220 Hz tone, or silence at 0."""
    frames = bytearray()
    for sec, amp in parts:
        for i in range(int(RATE * sec)):
            s = struct.pack("<h", int(amp * math.sin(2 * math.pi * 220 * i / RATE)))
            frames += s * channels
    p = tmp_path / "vocals.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    return str(p)


def test_a_start_is_moved_to_where_the_speech_begins(tmp_path):
    path = _vocals(tmp_path, [(0.8, 0), (2.0, 9000)])
    cues = [{"start": 0.0, "end": 2.8, "text": "hi"}]
    assert onset.snap_starts(cues, path) == 1
    assert abs(cues[0]["start"] - (0.8 - onset.PRE_ROLL_SEC)) < 0.03
    assert cues[0]["end"] == 2.8


def test_a_click_before_the_speech_is_not_the_start(tmp_path):
    path = _vocals(tmp_path, [(0.3, 0), (0.04, 9000), (0.5, 0), (2.0, 9000)])
    cues = [{"start": 0.0, "end": 2.84, "text": "hi"}]
    onset.snap_starts(cues, path)
    assert abs(cues[0]["start"] - (0.84 - onset.PRE_ROLL_SEC)) < 0.03


def test_a_start_already_close_is_left_alone(tmp_path):
    path = _vocals(tmp_path, [(0.1, 0), (2.0, 9000)])
    cues = [{"start": 0.0, "end": 2.1, "text": "hi"}]
    assert onset.snap_starts(cues, path) == 0
    assert cues[0]["start"] == 0.0


def test_a_line_is_never_left_shorter_than_its_minimum(tmp_path):
    path = _vocals(tmp_path, [(0.9, 0), (0.25, 9000)])
    cues = [{"start": 0.0, "end": 1.15, "text": "hi"}]
    onset.snap_starts(cues, path)
    assert cues[0]["start"] == 0.0


def test_a_long_jump_over_quiet_speech_is_refused(tmp_path):
    # Quiet speech (here 6% of the loud part) under the threshold is still
    # speech: jumping 1.5 s over it would play the dub late.
    path = _vocals(tmp_path, [(1.5, 600), (2.0, 9000)])
    cues = [{"start": 0.0, "end": 3.5, "text": "hi"}]
    assert onset.snap_starts(cues, path) == 0


def test_a_long_jump_over_silence_is_taken(tmp_path):
    path = _vocals(tmp_path, [(1.5, 0), (2.0, 9000)])
    cues = [{"start": 0.0, "end": 3.5, "text": "hi"}]
    assert onset.snap_starts(cues, path) == 1
    assert cues[0]["start"] > 1.4


def test_mono_vocals_and_a_cue_past_the_end_are_handled(tmp_path):
    path = _vocals(tmp_path, [(0.6, 0), (1.0, 9000)], channels=1)
    cues = [{"start": 0.0, "end": 1.6, "text": "a"}, {"start": 5.0, "end": 6.0, "text": "b"}]
    assert onset.snap_starts(cues, path) == 1
    assert cues[1]["start"] == 5.0


def test_no_vocals_file_moves_nothing(tmp_path):
    cues = [{"start": 0.0, "end": 2.0, "text": "hi"}]
    assert onset.snap_starts(cues, str(tmp_path / "missing.wav")) == 0
