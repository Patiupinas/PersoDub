"""Fitting lines to the speaker's measured pace after the first voicing
(app/text/pace_fit.py, app/qwen_pipeline.fit_to_pace)."""
import json
import os

from app import qwen_pipeline as qp
from app.text import pace_fit as pf
from app.translate import TranslationEngine
from tests.test_lead_burst import _wav

# --- the window -------------------------------------------------------------

def test_a_line_inside_the_window_misses_nothing():
    assert pf.miss(3.0, 3.0) == 0.0
    assert pf.miss(2.8, 3.0) == 0.0      # 0.2s early is fine
    assert pf.miss(3.4, 3.0) == 0.0      # 0.4s late is fine


def test_a_line_outside_the_window_misses_by_the_seconds_past_its_edge():
    assert abs(pf.miss(2.0, 3.0) - 0.75) < 1e-9   # ends 1.0s early: 0.75 past the 0.25 edge
    assert abs(pf.miss(4.0, 3.0) - 0.5) < 1e-9    # runs 1.0s long: 0.5 past the 0.5 edge


def test_pick_lines_takes_short_and_long_lines_only():
    texts = ["a", "b", "c", "", "e", "f"]
    durs = [2.0, 3.0, 4.0, 1.0, 0.3, None]
    slots = [3.0, 3.0, 3.0, 3.0, 0.8, 3.0]
    # 3: no words; 4: a slot too short to hold a phrase; 5: never voiced
    assert pf.pick_lines(texts, durs, slots) == [0, 2]


def test_a_new_voice_is_kept_only_when_clearly_closer():
    assert pf.worse_voice(3.0, 4.0, 5.0) is None            # 1.75 short -> 0.75 short
    assert pf.worse_voice(3.0, 3.05, 5.0) == "not closer"   # 0.05s closer is not worth new words
    assert pf.worse_voice(3.0, 2.5, 5.0) == "not closer"


def test_a_short_line_is_never_traded_for_one_that_runs_long():
    assert pf.worse_voice(3.0, 5.8, 5.0) == "now runs long"  # 1.75 short -> 0.3 long: closer, but sped up or cut
    assert pf.worse_voice(6.5, 5.7, 5.0) is None             # long and less long is fine


# --- the pace ---------------------------------------------------------------

def test_pace_is_measured_per_speaker():
    texts = ["가나다라마바사아자차", "가나다라마", "가나다라마바사아자차카타파하"]
    durs = [2.5, 1.5, 4.0]
    pace = pf.measure_pace(texts, durs, ["A", "A", "B"], "Korean")
    assert abs(pace["A"] - 15 / 4.0) < 1e-9
    assert abs(pace["B"] - 14 / 4.0) < 1e-9


def test_a_speaker_with_little_speech_takes_everyones_pace():
    texts = ["가나다라마바사아자차", "가나다라마바사아자차", "가나"]
    pace = pf.measure_pace(texts, [2.5, 2.5, 0.5], ["A", "A", "B"], "Korean")
    assert abs(pace["B"] - 22 / 5.5) < 1e-9


def test_with_little_speech_in_all_the_table_pace_is_used():
    pace = pf.measure_pace(["가나다"], [1.0], ["A"], "Korean")
    assert pace["A"] == pf._SYL_PER_SEC["ko"]


# --- the target ---------------------------------------------------------------

def test_target_is_what_the_slot_holds_at_the_pace():
    assert pf.target_count(4.0, 5.0, 18) == 20


def test_target_stays_within_reach_of_the_line_as_it_is():
    assert pf.target_count(10.0, 5.0, 20) == 27   # 50 wanted, at most +35%
    assert pf.target_count(1.0, 5.0, 20) == 13    # 5 wanted, at most -35%


# --- accept or reject ---------------------------------------------------------

def test_a_rewrite_that_changes_the_length_too_much_is_not_used():
    old = "가나다라마바사아자차"
    assert pf.usable_rewrite(old, "가나다라마바사아자차카타파하파", "Korean") == "length changed 50%"
    assert pf.usable_rewrite(old, "가나다라마", "Korean") == "length changed -50%"
    assert pf.usable_rewrite(old, "가나다라마바", "Korean") is None     # -40% is the edge, still fine
    assert pf.usable_rewrite(old, "가나다라마바사아자차카타파", "Korean") is None


def test_a_rewrite_with_nothing_new_is_not_used():
    assert pf.usable_rewrite("안녕하세요", None, "Korean") == "no answer"
    assert pf.usable_rewrite("안녕하세요", "  ", "Korean") == "no answer"
    assert pf.usable_rewrite("안녕하세요", "안녕하세요 ", "Korean") == "unchanged"


def test_a_rewrite_that_slips_in_another_script_is_not_used():
    assert pf.usable_rewrite("안녕하세요 여러분", "안녕 hi 여러분", "Korean") == "wrong script"


def test_a_name_the_line_already_kept_in_english_may_stay():
    assert pf.usable_rewrite("Apple 제품이 좋아요", "Apple 제품이 정말 좋아요", "Korean") is None


def test_source_is_the_source_lines_inside_the_dubbed_line():
    src = [{"start": 0.0, "end": 2.0, "text": "one"}, {"start": 2.1, "end": 4.0, "text": "two"},
           {"start": 5.0, "end": 20.0, "text": "a long one"}]
    assert pf.source_for({"start": 0.0, "end": 4.0}, src) == "one two"
    # a piece of a long line that was split: the line it overlaps most
    assert pf.source_for({"start": 15.0, "end": 20.0}, src) == "a long one"


class _Translator(TranslationEngine):
    display_name = "Fake"

    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def _ask(self, prompt):
        self.prompts.append(prompt)
        return self.answer(prompt)


def test_rewrites_are_asked_for_in_one_batch_with_source_and_target():
    tr = _Translator(lambda p: json.dumps(["하나 둘", "셋 넷"]))
    out = pf.ask_rewrites(tr, ["one two", "three four"], ["하나", "셋"], [4, 4], "Korean")
    assert out == ["하나 둘", "셋 넷"]
    assert len(tr.prompts) == 1
    assert "Source: one two" in tr.prompts[0] and "about 4 characters" in tr.prompts[0]
    assert "Keep EXACTLY the meaning" in tr.prompts[0]


def test_an_answer_that_cannot_be_read_leaves_every_line_as_it_is():
    tr = _Translator(lambda p: "no json here")
    assert pf.ask_rewrites(tr, ["a"], ["가"], [3], "Korean") == [None]


# --- fit_to_pace, end to end with a fake voice --------------------------------

class _PacedEngine:
    """Speaks 5 Hangul letters a second."""
    needs_spoken_numbers = adds_stray_sounds = free_retakes = True   # as Qwen3-TTS

    def __init__(self):
        self.said = []

    def synthesize(self, req):
        self.said.append(req.text)
        n = sum(1 for ch in req.text if ch.isalnum())

        class _Res:
            audio_bytes = _wav([(n / 5.0, 9000)])
            duration = n / 5.0
        return _Res()


def _first_voicing(engine, segments, tmp_path):
    paths = []
    for i, s in enumerate(segments):
        p = str(tmp_path / ("qwen_line_%d.wav" % i))
        with open(p, "wb") as f:
            f.write(engine.synthesize(type("R", (), {"text": s["text"]})).audio_bytes)
        paths.append(p)
    engine.said.clear()
    return paths


def test_a_short_line_is_written_fuller_voiced_again_and_kept(tmp_path):
    segments = [{"start": 0.0, "end": 4.0, "text": "가나다라마바사아자차카타파하가나다라마바"},   # 20: 4.0s, fits
                {"start": 5.0, "end": 9.0, "text": "가나다라마바사아자차카타파하"}]               # 14: 2.8s in 4.0, short
    ref = [{"start": 0.0, "end": 4.0, "text": "first"}, {"start": 5.0, "end": 9.0, "text": "second"}]
    engine = _PacedEngine()
    paths = _first_voicing(engine, segments, tmp_path)
    tr = _Translator(lambda p: json.dumps(["가나다라마바사아자차카타파하가나다라마"]))   # 19 letters
    logs = []
    qp.fit_to_pace(engine, tr, segments, ["A", "A"], {"A": "v"}, ref, "Korean", str(tmp_path),
                   paths, [4.0, 4.0], logs.append)
    assert engine.said == ["가나다라마바사아자차카타파하가나다라마"]
    assert segments[1]["text"] == "가나다라마바사아자차카타파하가나다라마"
    assert "Source: second" in tr.prompts[0]
    with open(tmp_path / "translated.srt", encoding="utf-8") as f:
        assert "가나다라마바사아자차카타파하가나다라마\n" in f.read()
    rec = json.load(open(tmp_path / "pace_fit.json", encoding="utf-8"))
    assert rec["rounds"][0][0]["kept"] is True and rec["translator"] == "Fake"
    assert not os.path.exists(tmp_path / "qwen_line_1_pace.wav")
    assert any("pace line 1: 2.80s in a 4.00s slot -> 3.80s, kept" in m for m in logs)
    # no words of the script in the log
    assert not any("가나" in m for m in logs)


def test_a_rewrite_that_lands_no_closer_is_dropped_and_its_voice_removed(tmp_path):
    segments = [{"start": 0.0, "end": 4.0, "text": "가나다라마바사아자차카타파하가나다라마바"},
                {"start": 5.0, "end": 9.0, "text": "가나다라마바사아자차카타파하"}]
    engine = _PacedEngine()
    paths = _first_voicing(engine, segments, tmp_path)
    before = open(paths[1], "rb").read()
    tr = _Translator(lambda p: json.dumps(["가나다라마바사아자차카타"]))   # shorter still
    qp.fit_to_pace(engine, tr, segments, ["A", "A"], {"A": "v"}, [], "Korean", str(tmp_path),
                   paths, [4.0, 4.0], lambda m: None)
    assert segments[1]["text"] == "가나다라마바사아자차카타파하"
    assert open(paths[1], "rb").read() == before
    assert not os.path.exists(tmp_path / "qwen_line_1_pace.wav")
    assert not os.path.exists(tmp_path / "translated.srt")
    rec = json.load(open(tmp_path / "pace_fit.json", encoding="utf-8"))
    assert [r["why"] for rnd in rec["rounds"] for r in rnd] == ["not closer", "not closer"]


def test_a_rewrite_that_changes_the_length_too_much_is_never_voiced(tmp_path):
    segments = [{"start": 0.0, "end": 4.0, "text": "가나다라마바사아자차카타파하가나다라마바"},
                {"start": 5.0, "end": 9.0, "text": "가나다라마바사아자차카타파하"}]
    engine = _PacedEngine()
    paths = _first_voicing(engine, segments, tmp_path)
    tr = _Translator(lambda p: json.dumps(["가" * 30]))
    qp.fit_to_pace(engine, tr, segments, ["A", "A"], {"A": "v"}, [], "Korean", str(tmp_path),
                   paths, [4.0, 4.0], lambda m: None)
    assert engine.said == []
    assert len(tr.prompts) == 2       # asked again in round 2, still refused


def test_a_translator_that_fails_leaves_the_lines_as_they_are(tmp_path):
    segments = [{"start": 0.0, "end": 4.0, "text": "가나다라마바사아자차카타파하"}]
    engine = _PacedEngine()
    paths = _first_voicing(engine, segments, tmp_path)

    def boom(p):
        raise RuntimeError("usage limit")
    logs = []
    qp.fit_to_pace(engine, _Translator(boom), segments, ["A"], {"A": "v"}, [], "Korean", str(tmp_path),
                   paths, [4.0], logs.append)
    assert engine.said == [] and any("pace fit stopped" in m for m in logs)


# --- only for a script the app translated -----------------------------------

def test_run_dub_hands_no_translator_to_a_user_script(monkeypatch, tmp_path):
    from app import pipeline
    from tests.test_qwen_dub_pipeline import _fake_mux, _FakeQwenEngine, _stub_qwen_io, _write_inputs
    _stub_qwen_io(monkeypatch)
    seen = {}
    real = pipeline._stage_synthesize

    def spy(*a, **k):
        seen["translator"] = k.get("translator")
        return real(*a, **k)
    monkeypatch.setattr(pipeline, "_stage_synthesize", spy)
    monkeypatch.setattr(pipeline, "_video_duration", lambda path: 2.0)
    monkeypatch.setattr(pipeline, "_mux", _fake_mux)
    monkeypatch.setattr(pipeline, "ensure_video_length", lambda *a, **k: None)
    video, out, srt = _write_inputs(tmp_path)
    pipeline.run_dub(video_path=video, out_path=out, srt_path=srt, language="Korean", language_code="ko",
                     qwen_engine=_FakeQwenEngine(), translator=_Translator(lambda p: "[]"), log=lambda m: None)
    assert seen["translator"] is None


def _auto_run(monkeypatch, tmp_path, translator):
    from app import pipeline
    from tests.test_qwen_dub_pipeline import _fake_mux, _FakeQwenEngine, _stub_qwen_io, _write_inputs
    _stub_qwen_io(monkeypatch)
    seen = {}
    real = pipeline._stage_synthesize

    def spy(*a, **k):
        seen["translator"] = k.get("translator")
        return real(*a, **k)

    def fake_auto_translate(source_cues, target_lang, translator, work_dir, **k):
        p = os.path.join(work_dir, "translated.srt")
        with open(p, "w") as f:
            f.write("1\n00:00:00,000 --> 00:00:02,000\nhi\n")
        return p
    monkeypatch.setattr(pipeline, "_auto_translate_srt", fake_auto_translate)
    monkeypatch.setattr(pipeline, "_stage_synthesize", spy)
    monkeypatch.setattr(pipeline, "_video_duration", lambda path: 2.0)
    monkeypatch.setattr(pipeline, "_mux", _fake_mux)
    monkeypatch.setattr(pipeline, "ensure_video_length", lambda *a, **k: None)
    video, out, _ = _write_inputs(tmp_path)
    logs = []
    pipeline.run_dub(video_path=video, out_path=out, srt_path=None, language="Korean", language_code="ko",
                     qwen_engine=_FakeQwenEngine(), translator=translator, log=logs.append)
    return seen["translator"], logs


def test_run_dub_hands_its_own_translator_to_the_voice_stage(monkeypatch, tmp_path):
    tr = _Translator(lambda p: "[]")
    got, _ = _auto_run(monkeypatch, tmp_path, tr)
    assert got is tr


def test_pace_fit_can_be_switched_off(monkeypatch, tmp_path):
    from app import config
    monkeypatch.setattr(config, "PACE_FIT", 0)
    got, _ = _auto_run(monkeypatch, tmp_path, _Translator(lambda p: "[]"))
    assert got is None


def test_a_translator_without_length_rules_is_not_asked(monkeypatch, tmp_path):
    tr = _Translator(lambda p: "[]")
    tr.length_rules = False
    got, logs = _auto_run(monkeypatch, tmp_path, tr)
    assert got is None and any("pace fit off: Fake" in m for m in logs)
