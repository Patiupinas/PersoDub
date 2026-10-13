"""Digits written out the way they are said before Qwen3-TTS reads a line
(2026-10-03): handed "1990년대", "80년대" or "2020년" as digits, it read them
oddly in every dubbing the owner heard (Obama, Trump, Shuka)."""
import pytest

from app.text.numbers import spoken_numbers


@pytest.mark.parametrize("text, said", [
    ("1990년대 초반, 80년대 후반", "천구백구십년대 초반, 팔십년대 후반"),
    ("2020년 졸업생 여러분", "이천이십년 졸업생 여러분"),
    ("주택 200만 호를 지으면", "주택 이백만 호를 지으면"),
    ("6회 이상 탈락자", "육회 이상 탈락자"),
    ("1순위가 많으면", "일순위가 많으면"),
    ("0순위 있었습니다", "영순위 있었습니다"),
    ("서울 인구가 1,000만이 안 되던", "서울 인구가 천만이 안 되던"),
    ("50% 정도", "오십 퍼센트 정도"),
    ("3.5초", "삼 점 오초"),
    ("6월 10일", "유월 십일"),
    ("10월에", "시월에"),
    ("3개월 동안", "삼개월 동안"),
])
def test_korean_reads_sino_numbers(text, said):
    assert spoken_numbers(text, "Korean") == said


@pytest.mark.parametrize("text, said", [
    ("3번 가보셨어요?", "세번 가보셨어요?"),
    ("2명이 왔어요", "두명이 왔어요"),
    ("20살 때", "스무살 때"),
    ("21개", "스물한개"),
    ("5시에 만나요", "다섯시에 만나요"),
    ("1시간 뒤", "한시간 뒤"),
    ("2번째 줄", "두번째 줄"),
    ("1번째", "첫번째"),
    ("100명", "백명"),
])
def test_korean_reads_native_numbers_before_a_counting_word(text, said):
    assert spoken_numbers(text, "Korean") == said


@pytest.mark.parametrize("text, said", [
    ("This all unfolds in the 1990s.", "This all unfolds in the nineteen nineties."),
    ("The early 90s, late 80s, right?", "The early nineties, late eighties, right?"),
    ("the '80s", "the eighties"),
    ("graduating class of 2020", "graduating class of twenty twenty"),
    ("In 1905 it began", "In nineteen oh-five it began"),
    ("2 million homes", "two million homes"),
    ("about 1,500 people", "about one thousand five hundred people"),
    ("the 21st century", "the twenty-first century"),
    ("50% of them", "fifty percent of them"),
    ("it costs $5", "it costs five dollars"),
    ("$1", "one dollar"),
    ("3.5 seconds", "three point five seconds"),
    ("six or more times", "six or more times"),
])
def test_english_reads_years_decades_and_numbers(text, said):
    assert spoken_numbers(text, "English") == said


@pytest.mark.parametrize("language, text, said", [
    ("Spanish", "en 1990 hubo 3 casos", "en mil novecientos noventa hubo tres casos"),
    ("German", "im Jahr 1990", "im Jahr neunzehnhundertneunzig"),
    ("French", "il y a 3 ans", "il y a trois ans"),
])
def test_other_languages_read_whole_numbers(language, text, said):
    assert spoken_numbers(text, language) == said


@pytest.mark.parametrize("text", [
    "version 3.5.1", "call 0107654321", "agent 007", "between 3-5 people", "at 3:30", "A1 B2", "a 3D movie in 4K",
])
def test_what_could_be_misread_is_left_alone(text):
    assert spoken_numbers(text, "English") == text


@pytest.mark.parametrize("language, text", [
    ("Chinese", "1990年代"), ("Japanese", "1990年代"), ("", "1990"), ("Klingon", "1990"),
])
def test_languages_without_a_checked_reading_keep_their_digits(language, text):
    assert spoken_numbers(text, language) == text


def test_a_decimal_comma_language_keeps_its_decimals():
    # "3,5" is three and a half in German: only whole numbers are read there.
    assert spoken_numbers("3,5 Prozent", "German") == "3,5 Prozent"


def test_reading_twice_changes_nothing_more():
    once = spoken_numbers("1990년대 3번", "Korean")
    assert spoken_numbers(once, "Korean") == once


class _Res:
    audio_bytes = b"RIFF"
    duration = 1.0


class _Engine:
    def __init__(self, real):
        # What the voice stage asks of the real engine about digits.
        self.needs_spoken_numbers = real.needs_spoken_numbers
        self.asked = []

    def synthesize(self, req):
        self.asked.append(req.text)
        return _Res()


def test_qwen3_is_handed_the_spoken_numbers(tmp_path, monkeypatch):
    from app import qwen_pipeline as qp
    monkeypatch.setattr(qp, "cut_lead_burst", lambda wav, text: (wav, 0.0))
    from app.engines.qwen_tts import QwenTTSEngine
    engine = _Engine(QwenTTSEngine)
    qp._synth_one(engine, {"text": "1990년대에 3번"}, "v", "Korean", 1, str(tmp_path / "l.wav"), lambda m: None, "line 0")
    assert engine.asked == ["천구백구십년대에 세번"]


def test_another_engine_reads_its_own_digits(tmp_path):
    from app import qwen_pipeline as qp
    from app.engines.base import TTSEngine
    engine = _Engine(TTSEngine)
    qp._synth_one(engine, {"text": "1990년대"}, "v", "Korean", 1, str(tmp_path / "l.wav"), lambda m: None, "line 0")
    assert engine.asked == ["1990년대"]
