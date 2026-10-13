"""Hunyuan MT is a translation-only model. Handed a scene as a JSON array under
the dubbing rules it left lines empty, moved lines into their neighbours'
places and wrote the speech-level rule's "-요" onto finished sentences
(2026-10-02). It is asked one line at a time, in the prompt it was trained on."""
import pytest

from app import translate
from app.config import OLLAMA_GEMMA_MODEL, OLLAMA_HUNYUAN_MODEL
from app.text.dub_prompt import UNTRANSLATED
from app.text.length_fit import fit_translate
from app.translate import OllamaTranslator


def _hunyuan(monkeypatch, answers):
    """A Hunyuan translator whose Ollama answers from `answers` in order;
    returns it and the request bodies it sent."""
    bodies = []
    replies = iter(answers)

    class Resp:
        status_code = 200

        def __init__(self, text):
            self.text = text

        def json(self):
            return {"message": {"content": self.text}}

    def fake_post(url, json=None, timeout=None):
        bodies.append(json)
        return Resp(next(replies))

    monkeypatch.setattr(translate.requests, "post", fake_post)
    return OllamaTranslator(url="http://x", model=OLLAMA_HUNYUAN_MODEL), bodies


def test_each_line_is_asked_alone_in_the_models_own_prompt(monkeypatch):
    tr, bodies = _hunyuan(monkeypatch, ["안녕하세요.", "잘 가요."])
    assert tr.translate(["Hello.", "Goodbye."], "Korean", "English") == ["안녕하세요.", "잘 가요."]
    prompts = [b["messages"][0]["content"] for b in bodies]
    assert prompts == [
        "Translate the following segment into Korean, without additional explanation.\n\nHello.",
        "Translate the following segment into Korean, without additional explanation.\n\nGoodbye.",
    ]
    # No dubbing rules, no speech-level rule, no array to answer in.
    assert "JSON" not in prompts[0] and "해요체" not in prompts[0]


def test_the_model_keeps_the_sampling_its_model_file_carries(monkeypatch):
    tr, bodies = _hunyuan(monkeypatch, ["안녕"])
    tr.translate(["Hi"], "Korean")
    assert bodies[0]["options"] == {"num_predict": 512}


def test_an_answer_over_several_rows_is_one_line(monkeypatch):
    tr, _ = _hunyuan(monkeypatch, ["  첫 문장이에요.\n둘째 문장이에요. \n"])
    assert tr.translate(["One. Two."], "Korean") == ["첫 문장이에요. 둘째 문장이에요."]


def test_an_empty_answer_is_asked_again_and_then_left_untranslated(monkeypatch):
    tr, bodies = _hunyuan(monkeypatch, ["", "안녕", "", " ", "\n"])
    assert tr.translate(["Hi", "Bye"], "Korean") == ["안녕", UNTRANSLATED]
    assert len(bodies) == 5


def test_a_line_with_nothing_in_it_is_not_sent(monkeypatch):
    tr, bodies = _hunyuan(monkeypatch, [])
    assert tr.translate(["  "], "Korean") == [UNTRANSLATED]
    assert bodies == []


def test_the_first_translation_of_a_script_goes_one_line_at_a_time(monkeypatch):
    # app/pipeline.py hands a translator without length rules no durations.
    tr, bodies = _hunyuan(monkeypatch, ["하나", "둘", "셋"])
    assert fit_translate(tr, ["one", "two", "three"], "Korean", "English", None) == ["하나", "둘", "셋"]
    assert len(bodies) == 3


def test_gemma_is_still_handed_the_scene(monkeypatch):
    tr = OllamaTranslator(url="http://x", model=OLLAMA_GEMMA_MODEL)
    assert tr.plain_lines is False and tr.length_rules is True


def test_a_cancel_stops_the_lines_between_two_requests(monkeypatch):
    # The pipeline's cancel check runs before every request (before_ask). A
    # line asked alone goes through ask like any other request, so a cancel
    # stops Hunyuan between two lines rather than after the last one.
    tr, bodies = _hunyuan(monkeypatch, ["하나", "둘", "셋"])

    def cancelled_once_one_is_sent():
        if bodies:
            raise RuntimeError("cancelled")
    tr.before_ask = cancelled_once_one_is_sent
    with pytest.raises(RuntimeError, match="cancelled"):
        tr.translate(["one", "two", "three"], "Korean")
    assert len(bodies) == 1
