"""Real CLI failure modes and source-bound Russian translation review gate."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from app import engines_status, translate
from app.translation_antigravity import AntigravityCLI
from app.translation_gate import review_ru_lines


def test_registered_and_opt_in_only():
    engine = translate.get_translator("antigravity")
    assert isinstance(engine, AntigravityCLI)
    assert engine.display_name == "Antigravity CLI (experimental)"
    assert engine.max_budget_retries == 0
    assert "antigravity" in engines_status.TRANSLATORS
    assert engines_status.TRANSLATORS["antigravity"].offered


def test_empty_success_is_a_real_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=json.dumps({"status":"SUCCESS","response":""}), stderr=""
    ))
    with pytest.raises(RuntimeError, match="no usable translation"):
        AntigravityCLI(binary="/fake/antigravity").ask("Translate")


def test_cli_timeout_prevents_hanging_job(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="timed out"):
        AntigravityCLI(binary="/fake/antigravity").ask("Translate")


def test_cli_uses_no_automatic_edits_and_caches_verified_response(tmp_path, monkeypatch):
    calls=[]
    def fake_run(args, **kwargs):
        calls.append((args,kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(
            {"status":"SUCCESS","response":'["Привет."]'}),stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    engine=AntigravityCLI(binary="/fake/antigravity")
    engine.answers_dir=str(tmp_path)
    assert engine.ask("One sentence") == '["Привет."]'
    assert engine.ask("One sentence") == '["Привет."]'
    assert len(calls)==1
    assert calls[0][0][1:3]==["--print","One sentence"]
    assert "--mode" in calls[0][0]
    assert calls[0][1]["timeout"] > 0
    assert len(list(tmp_path.glob("*.txt")))==1


def test_translation_four_cues_with_source_clock(monkeypatch):
    calls=[]
    def fake_ask(self, prompt):
        calls.append(prompt)
        return json.dumps(["Первое.","Второе.","Третье.","Четвёртое."])
    monkeypatch.setattr(AntigravityCLI,"ask",fake_ask)
    engine=AntigravityCLI(binary="/fake")
    actual=engine.translate(["a","b","c","d"],"Russian","English",[4,4,4,4])
    assert actual==["Первое.","Второе.","Третье.","Четвёртое."]
    assert len(calls)==1
    assert "max_ru_words" in calls[0]


def test_length_flag_blocks_output_before_russian_speech_synthesis(monkeypatch):
    monkeypatch.setattr(AntigravityCLI,"ask", lambda *a:
                        json.dumps(["Слишком длинная фраза для короткого времени.","Да."]))
    with pytest.raises(ValueError,match="needs review"):
        AntigravityCLI(binary="/fake").translate(["a","b"],"ru","en",[.5,2])


def test_review_gate_flags_informal_address_and_garbled_gender():
    flags=review_ru_lines(["I ran with my dog", "Choose one"],
                          ["Я хотела погулять с собакой.","Выберите упражнение."],
                          [5,4],informal=True,male_narrator=True)
    assert "narrator_gender_inconsistent" in flags[0]["issues"]
    assert "address_register_inconsistent" in flags[1]["issues"]


def test_review_gate_counts_russian_words_including_cyrillic_and_false_completion():
    flags=review_ru_lines(["a","b"],["Очень много русских слов в одной короткой реплике.",
                                     "Я только что"],[1,5])
    assert "too_long_for_source_clock" in flags[0]["issues"]
    assert "possible_sentence_fragment" in flags[1]["issues"]


def test_no_bilingual_gold_is_claimed_by_review_gate():
    assert review_ru_lines(["This is a negative"],["Это не так."],[5]) == []


def test_pipeline_uses_gate_not_generic_length_fit(tmp_path, monkeypatch):
    from app import pipeline

    called = []
    class FakeArgon:
        id = "antigravity"
        length_rules = True
        recheck_script = False
        def translate(self, texts, language, source=None, durations=None, fuller=False):
            called.append((texts, durations))
            raise ValueError("Antigravity output needs review: source cues [2]")

    monkeypatch.setattr(pipeline, "fit_translate", lambda *a, **k:
                        pytest.fail("Generic fit would bypass Argon review gate"))
    cues = [{"start":0.0,"end":3.0,"text":"one"},
            {"start":3.0,"end":6.0,"text":"two"}]
    with pytest.raises(ValueError, match="needs review"):
        pipeline._auto_translate_srt(cues, "Russian", FakeArgon(), str(tmp_path))
    assert len(called) == 1
    assert not (tmp_path/"translated.srt").exists()


def test_qa_uses_real_experiment_cues_without_declaring_semantic_pass():
    rows = [
        ("I ran with my dog", "Я хотела погонять пса на улице, а погонял он меня.", 6.0),
        ("Move the exercise into a song", "Вернёшь мышцы.", 3.0),
        ("Practice", "Не зажимай спину, держи лёгкий тонус у пупка.", 1.5),
    ]
    findings=review_ru_lines([r[0] for r in rows],[r[1] for r in rows],
                            [r[2] for r in rows],male_narrator=True)
    assert 1 in [f["cue"] for f in findings]
    assert 3 in [f["cue"] for f in findings]
    # Cue 2 is semantically wrong but passes surface checks. Semantic gold
    # must therefore be a separate review, never assumed from no flags.
    assert 2 not in [f["cue"] for f in findings]


def test_status_endpoint_exposes_optional_cli_without_assuming_success(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    monkeypatch.setattr(engines_status, "antigravity_available", lambda: False)
    response=TestClient(app, base_url="http://127.0.0.1").get("/api/engines")
    assert response.status_code==200
    assert response.json()["antigravity_available"] is False
    monkeypatch.setattr(engines_status, "antigravity_available", lambda: True)
    assert TestClient(app, base_url="http://127.0.0.1").get("/api/engines").json()["antigravity_available"] is True
