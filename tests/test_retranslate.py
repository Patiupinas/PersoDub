"""Translate again: chosen lines of a finished dub, through the translator
the project was dubbed with (ChatGPT in most of these). Words
only: no voice is made. The button and the assistant's tool share one route."""
import json

from fastapi.testclient import TestClient

import app.api.script as script_api
from app import engines_status, retranslate, state
from app.main import app
from app.text.srt import build_srt
from app.translate import TranslationEngine

client = TestClient(app, base_url="http://127.0.0.1")


def _job(tmp_path, source, texts, status="done", translator="chatgpt"):
    work = tmp_path / "dubbed"
    work.mkdir(exist_ok=True)
    (work / "input.mp4").write_bytes(b"vid")
    cues = [{"start": s, "end": e, "text": t} for s, e, t in texts]
    (work / "translated.srt").write_text(build_srt(cues), encoding="utf-8")
    (work / "original.srt").write_text(
        build_srt([{"start": s, "end": e, "text": t} for s, e, t in source]), encoding="utf-8")
    (work / "lines.json").write_text(json.dumps({
        "language": "Korean",
        "lines": [{"i": i, "speaker": "SPEAKER_00", "start": c["start"], "gain": 1.0}
                  for i, c in enumerate(cues)]}), encoding="utf-8")
    jid = state.job_store.create()
    state.job_store._update(jid, status=status, work_dir=str(work), project="dubbed",
                            language_code="ko", language="Korean",
                            result={"out_path": str(work / "dubbed.mp4")},
                            **({"translator": translator} if translator else {}))
    return jid, work


def _fakes(monkeypatch, answers):
    asked, said, built = [], [], []
    def fit(tr, texts, lang, src, slots, log=None):
        asked.append((list(texts), lang, slots))
        return [answers.get(t, "") for t in texts]
    monkeypatch.setattr(retranslate, "fit_translate", fit)
    monkeypatch.setattr(engines_status, "chatgpt_available", lambda: True)
    monkeypatch.setattr(script_api, "get_translator", lambda name: TranslationEngine())
    monkeypatch.setattr(script_api, "resynth_one_line", lambda *a: said.append(a) or "made.wav")
    monkeypatch.setattr(script_api, "rebuild_dub", lambda *a: built.append(a))
    return asked, said, built


SOURCE = [(0.0, 2.0, "Hello."), (3.0, 5.0, "Thanks for coming."), (6.0, 8.0, "Bye.")]
DUB = [(0.0, 2.0, "안녕."), (3.0, 5.0, "와 줘서 고마워."), (6.0, 8.0, "잘 가.")]


def test_chosen_lines_are_translated_again_and_no_voice_is_made(monkeypatch, tmp_path):
    asked, said, built = _fakes(monkeypatch, {"Thanks for coming.": "와 주셔서 감사해요."})
    jid, work = _job(tmp_path, SOURCE, DUB)
    r = client.post(f"/api/dub/jobs/{jid}/retranslate", json={"lines": [2]})
    assert r.status_code == 200
    assert r.json() == {"changed": [{"line": 2, "was": "와 줘서 고마워.", "text": "와 주셔서 감사해요."}]}
    assert asked == [(["Thanks for coming."], "Korean", [2.0])]
    assert said == [] and built == []
    # The first translation stays on record; the new words are an edit of it.
    assert "와 줘서 고마워." in (work / "translated.srt").read_text(encoding="utf-8")
    assert "와 주셔서 감사해요." in (work / "edited.srt").read_text(encoding="utf-8")


def test_no_lines_named_means_every_line(monkeypatch, tmp_path):
    asked, said, built = _fakes(monkeypatch, {})
    jid, _ = _job(tmp_path, SOURCE, DUB)
    r = client.post(f"/api/dub/jobs/{jid}/retranslate", json={})
    assert r.status_code == 200
    assert asked[0][0] == ["Hello.", "Thanks for coming.", "Bye."]
    # No usable answer: every line keeps its words, and nothing is respoken.
    assert r.json() == {"changed": []} and said == [] and built == []


def test_a_sentence_split_over_lines_is_translated_once_and_dealt_back(monkeypatch, tmp_path):
    source = [(0.0, 6.0, "Great. Go now. It's your chance.")]
    dub = [(0.0, 1.0, "잘됐네."), (1.0, 3.0, "얼른 가."), (3.0, 6.0, "기회잖아.")]
    asked, said, _ = _fakes(monkeypatch, {source[0][2]: "잘됐어요. 얼른 가 봐요. 기회가 왔잖아요."})
    jid, _ = _job(tmp_path, source, dub)
    r = client.post(f"/api/dub/jobs/{jid}/retranslate", json={"lines": [2]})
    assert asked == [([source[0][2]], "Korean", [6.0])]
    assert [c["text"] for c in r.json()["changed"]] == ["잘됐어요.", "얼른 가 봐요.", "기회가 왔잖아요."]


def test_the_same_words_said_again_are_their_own_lines(monkeypatch, tmp_path):
    # Three source lines with the same words are one sentence said three times,
    # not one sentence the dub split over three lines. Taken for the second,
    # they were translated once and the answer cut into pieces over the lines:
    # "With a" / "biased scale, doesn't" / ... (Windows test H14, 2026-10-10).
    said = "¿No asume que todo es culpa de los estudiantes?"
    source = [(i * 2.0, i * 2.0 + 1.8, said) for i in range(3)]
    dub = [(i * 2.0, i * 2.0 + 1.8, "Doesn't it assume it's the students' fault?") for i in range(3)]
    answer = "Isn't it all the students' fault, then?"
    asked, _, _ = _fakes(monkeypatch, {said: answer})
    jid, _ = _job(tmp_path, source, dub)
    r = client.post(f"/api/dub/jobs/{jid}/retranslate", json={})
    assert r.status_code == 200
    assert asked[0][0] == [said, said, said]
    assert [c["text"] for c in r.json()["changed"]] == [answer] * 3


def test_signed_out_running_and_unknown_lines_are_refused(monkeypatch, tmp_path):
    _fakes(monkeypatch, {})
    jid, _ = _job(tmp_path, SOURCE, DUB)
    assert client.post(f"/api/dub/jobs/{jid}/retranslate", json={"lines": [9]}).status_code == 422
    assert client.post(f"/api/dub/jobs/{jid}/retranslate", json={"lines": []}).status_code == 422
    monkeypatch.setattr(engines_status, "chatgpt_available", lambda: False)
    r = client.post(f"/api/dub/jobs/{jid}/retranslate", json={"lines": [1]})
    assert r.status_code == 422 and r.json()["detail"] == "Sign in to ChatGPT first."
    jid2, _ = _job(tmp_path, SOURCE, DUB, status="running")
    assert client.post(f"/api/dub/jobs/{jid2}/retranslate", json={"lines": [1]}).status_code == 409


def test_a_chatgpt_failure_is_a_sentence_not_a_crash(monkeypatch, tmp_path):
    _fakes(monkeypatch, {})
    def boom(*a, **k):
        raise script_api.ChatGptLimitError("limit")
    monkeypatch.setattr(retranslate, "fit_translate", boom)
    jid, _ = _job(tmp_path, SOURCE, DUB)
    r = client.post(f"/api/dub/jobs/{jid}/retranslate", json={"lines": [1]})
    assert r.status_code == 429 and "usage limit" in r.json()["detail"]


def test_one_sentence_over_two_lines_is_shared_by_time_not_left_beside_old_words():
    # Dealt by sentence, the first line got nothing and kept its old words and
    # voice: the dub said the first half twice (review, 2026-09-29).
    from app.retranslate import _deal
    group = [{"start": 0.0, "end": 2.0}, {"start": 2.0, "end": 4.0}]
    out = _deal("A brand new single sentence here", group)
    assert all(out)
    assert " ".join(out) == "A brand new single sentence here"
    assert out == ["A brand new", "single sentence here"]


def test_shared_by_time_follows_the_slots_and_feeds_every_line():
    from app.retranslate import _deal
    group = [{"start": 0.0, "end": 1.0}, {"start": 1.0, "end": 4.0}, {"start": 4.0, "end": 4.2}]
    out = _deal("one two three four five six seven eight", group)
    assert all(out) and " ".join(out) == "one two three four five six seven eight"
    assert len(out[1].split()) > len(out[0].split())
    # No spaces to cut at (Japanese, Chinese): cut between characters.
    out = _deal("これは新しい一つの文です", group[:2])
    assert all(out) and "".join(out) == "これは新しい一つの文です"


# --- The project's own translator (Windows H14, 2026-10-06) -----------------
# ChatGPT's free limit ran out for weeks, and Translate again asked ChatGPT on
# every project, even one Hunyuan translated: no line could be translated again.

from app.api import _launch as launch_api  # noqa: E402
from app.api import dub as dub_api  # noqa: E402
from tests.test_dub_api import _all_engines_available  # noqa: E402,F401


def _named(monkeypatch):
    """The translator names get_translator was handed."""
    names = []
    monkeypatch.setattr(script_api, "get_translator", lambda name: names.append(name) or TranslationEngine())
    return names


def test_translate_again_uses_the_translator_the_project_was_dubbed_with(monkeypatch, tmp_path):
    _fakes(monkeypatch, {"Hello.": "안녕하세요."})
    names = _named(monkeypatch)
    # ChatGPT signed out (or at its limit) is none of a Hunyuan project's business.
    monkeypatch.setattr(engines_status, "chatgpt_available", lambda: False)
    jid, _ = _job(tmp_path, SOURCE, DUB, translator="hunyuan")
    r = client.post(f"/api/dub/jobs/{jid}/retranslate", json={"lines": [1]})
    assert r.status_code == 200 and r.json()["changed"][0]["text"] == "안녕하세요."
    assert names == ["hunyuan"]


def test_a_project_resumed_with_another_translator_is_translated_again_by_that_one(monkeypatch, tmp_path):
    # ChatGPT stopped the dub and Resume carried on with Gemma: the job
    # record names Gemma (app/api/dub.py dub_job_resume), so Gemma it is.
    _fakes(monkeypatch, {})
    names = _named(monkeypatch)
    jid, _ = _job(tmp_path, SOURCE, DUB, translator="chatgpt")
    state.job_store._update(jid, translator="gemma")
    client.post(f"/api/dub/jobs/{jid}/retranslate", json={"lines": [1]})
    assert names == ["gemma"]


def test_a_project_saved_before_its_translator_was_kept_uses_the_one_in_settings(monkeypatch, tmp_path):
    _fakes(monkeypatch, {})
    names = _named(monkeypatch)
    monkeypatch.setattr(dub_api.dub_setup, "default_for", lambda stage: "hunyuan")
    jid, _ = _job(tmp_path, SOURCE, DUB, translator=None)
    client.post(f"/api/dub/jobs/{jid}/retranslate", json={"lines": [1]})
    assert names == ["hunyuan"]


def test_another_translator_can_be_picked_for_these_lines(monkeypatch, tmp_path):
    # The ChatGPT popup's "Continue with Hunyuan": these lines only, and the
    # project's record keeps the translator that made the dub.
    _fakes(monkeypatch, {})
    names = _named(monkeypatch)
    jid, _ = _job(tmp_path, SOURCE, DUB)
    assert client.post(f"/api/dub/jobs/{jid}/retranslate",
                       json={"lines": [1], "translator": "hunyuan"}).status_code == 200
    assert names == ["hunyuan"]
    assert state.job_store.get(jid)["translator"] == "chatgpt"
    r = client.post(f"/api/dub/jobs/{jid}/retranslate", json={"lines": [1], "translator": "deepl"})
    assert r.status_code == 422 and names == ["hunyuan"]


def test_a_local_translator_not_downloaded_asks_for_it_like_a_dub_start(monkeypatch, tmp_path):
    _fakes(monkeypatch, {})
    names = _named(monkeypatch)
    monkeypatch.setattr(engines_status, "hunyuan_status", lambda: "model_missing")
    asked = []

    def missing(need_whisper, translate_missing_id, need_tts=True, **kw):
        asked.append((need_whisper, translate_missing_id, need_tts))
        return [{"id": translate_missing_id, "kind": "model", "name": "Hunyuan", "bytes": 1100000000, "hint": ""}]
    monkeypatch.setattr(launch_api, "missing_models", missing)
    monkeypatch.setattr(dub_api.model_store, "free_bytes_at", lambda p: 5e9)
    jid, _ = _job(tmp_path, SOURCE, DUB, translator="hunyuan")
    r = client.post(f"/api/dub/jobs/{jid}/retranslate", json={"lines": [1]})
    assert r.status_code == 409 and r.json()["detail"]["missing"][0]["id"] == "hunyuan"
    assert asked == [(False, "hunyuan", False)] and names == []


def test_a_local_translator_that_cannot_run_now_is_refused_like_a_dub_start(monkeypatch, tmp_path):
    _fakes(monkeypatch, {})
    names = _named(monkeypatch)
    monkeypatch.setattr(engines_status, "gemma_status", lambda: "unreachable")
    jid, _ = _job(tmp_path, SOURCE, DUB, translator="gemma")
    r = client.post(f"/api/dub/jobs/{jid}/retranslate", json={"lines": [1]})
    assert r.status_code == 422 and "Gemma" in r.json()["detail"] and names == []


def test_the_chatgpt_limit_says_when_it_resets(monkeypatch, tmp_path):
    _fakes(monkeypatch, {})
    def boom(*a, **k):
        raise script_api.ChatGptLimitError("limit", "Oct 24, 1:07 PM")
    monkeypatch.setattr(retranslate, "fit_translate", boom)
    jid, _ = _job(tmp_path, SOURCE, DUB)
    r = client.post(f"/api/dub/jobs/{jid}/retranslate", json={"lines": [1]})
    assert r.status_code == 429 and "Resets Oct 24, 1:07 PM." in r.json()["detail"]


def test_a_failure_names_the_translator_that_failed(monkeypatch, tmp_path):
    _fakes(monkeypatch, {})
    def boom(*a, **k):
        raise RuntimeError("Ollama went away")
    monkeypatch.setattr(retranslate, "fit_translate", boom)
    jid, _ = _job(tmp_path, SOURCE, DUB, translator="hunyuan")
    r = client.post(f"/api/dub/jobs/{jid}/retranslate", json={"lines": [1]})
    assert r.status_code == 502 and r.json()["detail"].startswith("Hunyuan could not translate")
