"""Contract tests for the read-only WhisperNotes Session Pipeline V2 importer."""

import copy

import pytest

from app.vocal_whispernotes import import_session


SOURCE = "a" * 64


def fixture():
    phrases = {"phrases": [
        {"phraseID": "p1", "speaker": "session-speaker-01", "start": 1.0, "end": 3.0},
        {"phraseID": "p2", "speaker": "session-speaker-02", "start": 4.0, "end": 6.0},
    ]}
    final = {"segments": [
        {"phraseID": "p1", "speaker": "Display Name", "start": 1.0, "end": 3.0,
         "selectedLocale": "de-DE", "text": "Guten Morgen", "needsReview": False,
         "candidates": [{"candidateID": "c1", "decision": "selected"}]},
        {"phraseID": "p2", "speaker": "Other Name", "start": 4.0, "end": 6.0,
         "selectedLocale": "es-ES", "text": "Hola", "needsReview": True,
         "candidates": [{"candidateID": "c2", "decision": "selected"}]},
    ]}
    asr = {"candidates": [
        {"candidateID": "c1", "phraseID": "p1", "text": "Guten Morgen", "words": [
            {"start": 0.1, "end": 0.5, "text": "Guten", "isEstimated": False},
            {"start": 0.6, "end": 1.1, "text": "Morgen", "isEstimated": True}]},
        {"candidateID": "c2", "phraseID": "p2", "text": "Hola", "words": []},
    ]}
    return final, phrases, asr


def run(final=None, phrases=None, asr=None, **kwargs):
    f, p, a = fixture()
    return import_session(final if final is not None else f,
                          phrases if phrases is not None else p,
                          asr if asr is not None else a,
                          pcm_sha256=SOURCE, sample_rate=48000,
                          total_samples=48000 * 10, time_domain=kwargs.get("time_domain", "original"),
                          compact_map=kwargs.get("compact_map"))


def test_keeps_stable_speaker_and_relative_word_timing():
    result = run()
    first, second = result["segments"]
    assert first["speaker_id"] == "session-speaker-01"
    assert first["display_speaker"] == "Display Name"
    assert first["source_language"] == "de"
    assert (first["start_sample"], first["end_sample"]) == (48000, 144000)
    assert first["words"][0] == {"start_sample": 52800, "end_sample": 72000,
                                 "text": "Guten", "is_estimated": False}
    assert first["words"][1]["is_estimated"] is True
    assert second["source_language"] == "es" and second["needs_review"] is True
    assert result["pcm_sha256"] == SOURCE


def test_compacted_input_remaps_without_collapsing_gap():
    final, phrases, asr = fixture()
    for phrase, seg in zip(phrases["phrases"], final["segments"]):
        if phrase["phraseID"] == "p2":
            phrase["start"] -= 1
            phrase["end"] -= 1
            seg["start"] -= 1
            seg["end"] -= 1
    mapping = {"regions": [
        {"compactStart": 0, "compactEnd": 3, "originalStart": 0, "originalEnd": 3},
        {"compactStart": 3, "compactEnd": 6, "originalStart": 4, "originalEnd": 7},
    ]}
    out = run(final, phrases, asr, time_domain="compact", compact_map=mapping)
    assert out["segments"][1]["start_sample"] == 4 * 48000
    assert out["segments"][1]["words"] == []


def test_rejects_interval_spanning_compacted_gap():
    final, phrases, asr = fixture()
    mapping = {"regions": [
        {"compactStart": 0, "compactEnd": 2, "originalStart": 0, "originalEnd": 2},
        {"compactStart": 2, "compactEnd": 8, "originalStart": 3, "originalEnd": 9},
    ]}
    with pytest.raises(ValueError, match="removed compact-audio region"):
        run(final, phrases, asr, time_domain="compact", compact_map=mapping)


def test_missing_phrase_and_conflicting_bounds_rejected():
    final, phrases, asr = fixture()
    phrases["phrases"].pop(0)
    with pytest.raises(ValueError, match="unique phraseID"):
        run(final, phrases, asr)
    final, phrases, asr = fixture()
    final["segments"][0]["end"] = 3.1
    with pytest.raises(ValueError, match="disagree"):
        run(final, phrases, asr)


def test_conflicting_asr_candidate_rejected():
    final, phrases, asr = fixture()
    asr["candidates"][0]["text"] = "Other"
    with pytest.raises(ValueError, match="disagrees"):
        run(final, phrases, asr)
    final, phrases, asr = fixture()
    asr["candidates"][0]["words"][0]["end"] = 5.0
    with pytest.raises(ValueError, match="outside selected phrase"):
        run(final, phrases, asr)


def test_missing_optional_candidate_marks_review():
    final, phrases, asr = fixture()
    asr["candidates"] = []
    out = run(final, phrases, asr)
    assert out["segments"][0]["needs_review"] is True
    assert out["segments"][0]["review_reason"] == "missing_selected_candidate"
    assert out["segments"][0]["words"] == []


def test_source_binding_and_timeline_explicit():
    final, phrases, asr = fixture()
    with pytest.raises(ValueError, match="SHA-256"):
        import_session(final, phrases, asr, pcm_sha256="oops", sample_rate=48000,
                       total_samples=480000, time_domain="original")
    with pytest.raises(ValueError, match="explicitly"):
        import_session(final, phrases, asr, pcm_sha256=SOURCE, sample_rate=48000,
                       total_samples=480000, time_domain="unknown")
    with pytest.raises(ValueError, match="Do not remap"):
        run(compact_map={"regions": []})


def test_float_nan_and_overflow_rejected():
    final, phrases, asr = fixture()
    final["segments"][0]["start"] = float("nan")
    phrases["phrases"][0]["start"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        run(final, phrases, asr)
    final, phrases, asr = fixture()
    final["segments"][0]["end"] = 11
    phrases["phrases"][0]["end"] = 11
    with pytest.raises(ValueError, match="outside source PCM"):
        run(final, phrases, asr)


def test_does_not_mutate_whispernotes_payloads():
    final, phrases, asr = fixture()
    before = copy.deepcopy((final, phrases, asr))
    run(final, phrases, asr)
    assert before == (final, phrases, asr)


def test_cli_imports_without_altering_source(tmp_path):
    import json
    import subprocess
    import sys

    final, phrases, asr = fixture()
    input_dir = tmp_path / "session"
    input_dir.mkdir()
    for name, payload in (("session.final_transcript.json", final),
                          ("session.phrases.json", phrases),
                          ("session.asr_candidates.json", asr)):
        (input_dir / name).write_text(json.dumps(payload), encoding="utf-8")
    before = [(p.name, p.read_bytes()) for p in input_dir.iterdir()]
    out = tmp_path / "output" / "transcript.json"
    done = subprocess.run([
        sys.executable, "-m", "app.scripts.vocal_import_whispernotes",
        "--session", str(input_dir), "--pcm-sha256", SOURCE,
        "--sample-rate", "48000", "--total-samples", "480000",
        "--time-domain", "original", "--output", str(out),
    ], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert json.loads(out.read_text(encoding="utf-8"))["segments"][0]["speaker_id"] == "session-speaker-01"
    assert [(p.name, p.read_bytes()) for p in input_dir.iterdir()] == before
