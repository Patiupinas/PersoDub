"""The voice a Qwen3-TTS dubbing is cloned from (2026-10-03). Cloned from its
sound alone ("timbre"), 20 of 28 test lines opened with a stray "어/아"; given
what the reference says as well ("icl"), its silence trimmed and the voice's
randomness lowered from 0.9 to 0.6, 2 of 28 did, and the voice came out the
closest to the speaker's (CAM++ 0.647 against 0.630)."""
import glob
import os

import httpx
import pytest

from app import config
from app import qwen_pipeline as qp
from app.audio import lead_burst as lb
from app.engines.base import SynthesisRequest, TTSEngine
from app.engines.qwen_tts import QwenTTSEngine
from tests.test_lead_burst import _seconds, _wav


def _cue(start, end, text, speaker):
    return {"start": start, "end": end, "text": text, "speaker_id": speaker}


def test_a_reference_keeps_its_speech_and_no_silence_either_side():
    # Silence put back on either side (0.25 s, 2026-10-03) made the anchor
    # briefing's lines come out as different people: the same span cloned
    # unpadded was 0.702 like the speaker (0 of 18 lines under 0.5), padded
    # 0.459 (9 of 18). Over four clips the padding did not lower the stray
    # words in front (6 against 6) (2026-10-06).
    raw = _wav([(0.7, 0), (2.0, 9000), (1.1, 0)])
    out = lb.tidy_reference(raw)
    assert abs(_seconds(out) - 2.0) < 0.03


def _as_piped(wav_bytes):
    """The wav as ffmpeg writes it to a pipe (app/text/cues.py
    cut_vocals_span_local): both sizes in the header say "unknown"."""
    b = bytearray(wav_bytes)
    b[4:8] = b"\xff\xff\xff\xff"
    i = bytes(b).index(b"data")
    b[i + 4:i + 8] = b"\xff\xff\xff\xff"
    return bytes(b)


def test_a_reference_cut_by_ffmpeg_with_unknown_length_is_tidied():
    # The real reference's header claims 89,478 seconds (2026-10-03): copying
    # that count into the trimmed wav failed every dubbing.
    out = lb.tidy_reference(_as_piped(_wav([(0.7, 0), (2.0, 9000), (1.1, 0)])))
    assert abs(_seconds(out) - 2.0) < 0.03


def test_a_real_reference_from_a_finished_dub_is_tidied():
    # The real thing when this Mac has one (skipped elsewhere): a reference
    # cut by ffmpeg from separated vocals.
    found = glob.glob(os.path.expanduser("~/PersoDub-prod-*/workspace/*/*/qwen_ref_*.wav"))
    if not found:
        pytest.skip("no real reference on this machine")
    # The longest one: a speaker with under a second of speech (an old dub's
    # extra speaker) stays under the bound once no silence is added back.
    raw = open(max(found, key=os.path.getsize), "rb").read()
    out = lb.tidy_reference(raw)
    assert 0.5 < _seconds(out) < 20


def test_a_reference_that_is_not_mono_wav_is_left_alone():
    assert lb.tidy_reference(b"not a wav") == b"not a wav"


def test_the_reference_is_cloned_with_what_it_says_by_default(monkeypatch):
    assert config.QWEN_VOICE_MODE == "icl"
    raw = _wav([(0.5, 0), (3.0, 9000), (0.5, 0)])
    monkeypatch.setattr(qp, "cut_vocals_span_local", lambda vocals_path, spans: raw)
    refs = qp.build_speaker_refs([_cue(0.0, 5.0, "hello this is speaker A talking now", "A")], ["A"], "/v.wav")
    assert "speaker A talking" in refs["A"]["ref_text"]
    assert abs(_seconds(refs["A"]["wav_bytes"]) - 3.0) < 0.03


def test_a_speaker_whose_reference_says_nothing_usable_keeps_a_voice(monkeypatch):
    # Without words to go with the sound the speaker used to be dropped, and
    # their lines had no voice to be made in.
    monkeypatch.setattr(qp, "cut_vocals_span_local", lambda vocals_path, spans: _wav([(3.0, 9000)]))
    monkeypatch.setattr(qp, "ref_text_from_spans", lambda cues, spans: "  ")
    refs = qp.build_speaker_refs([_cue(0.0, 5.0, "hm", "A")], ["A"], "/v.wav", mode="icl")
    assert refs["A"]["ref_text"] is None


class _Engine(TTSEngine):
    def __init__(self):
        self.cloned = []

    def clone(self, path, ref_text, mode=None):
        self.cloned.append((ref_text, mode))
        return "v"


def test_a_reference_without_words_is_cloned_from_its_sound(tmp_path):
    engine = _Engine()
    refs = {"A": {"wav_bytes": b"RIFF", "ref_text": "hi there", "span": {}},
            "B": {"wav_bytes": b"RIFF", "ref_text": None, "span": {}}}
    engine.assign_voices(refs, ["A", "B"], str(tmp_path), lambda m: None, mode="icl")
    assert engine.cloned == [("hi there", "icl"), (None, "timbre")]


def _capture_clone(monkeypatch):
    sent = {}

    class _R:
        def raise_for_status(self):
            return None

        def json(self):
            return {"voice_id": "v"}

    def fake_post(url, data=None, files=None, timeout=None):
        sent.update(data)
        return _R()

    monkeypatch.setattr(httpx, "post", fake_post)
    return sent


def test_the_engine_clones_with_the_words_when_it_has_them(monkeypatch, tmp_path):
    p = tmp_path / "ref.wav"
    p.write_bytes(b"RIFF")
    sent = _capture_clone(monkeypatch)
    QwenTTSEngine(base_url="http://x").clone(str(p), "hello there")
    assert sent == {"mode": "icl", "ref_text": "hello there"}


def test_the_engine_clones_from_the_sound_when_a_remade_line_has_no_words(monkeypatch, tmp_path):
    # A job made before 2026-10-03 kept no words with its reference
    # (speaker_refs.json ref_text null): remaking one of its lines still works.
    p = tmp_path / "ref.wav"
    p.write_bytes(b"RIFF")
    sent = _capture_clone(monkeypatch)
    QwenTTSEngine(base_url="http://x").clone(str(p), "")
    assert sent == {"mode": "timbre"}


def test_each_line_is_made_with_the_lower_randomness():
    form = QwenTTSEngine(base_url="http://x")._build_form(SynthesisRequest(text="안녕", voice_id="v"))
    assert form["temperature"] == "0.6" and form["top_p"] == "0.9"
