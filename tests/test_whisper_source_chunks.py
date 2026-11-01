"""Source-audio ownership and opt-in STT contracts; no weights are required."""
from types import SimpleNamespace

import pytest

from app import pipeline, stt_local
from app.scripts import whisper_source_chunks as chunks
from app.scripts import whisper_transcribe as worker


def word(name, start, end):
    return SimpleNamespace(word=name, start=start, end=end)


def segment(*words):
    return SimpleNamespace(
        text="".join(w.word for w in words),
        words=list(words),
    )


def test_real_clip_plan_matches_existing_source_audit():
    plan = chunks.plan_source_windows(234.684)
    assert len(plan) == 8
    assert [(w["start"], w["end"]) for w in plan[:3]] == [
        (0.0, 34.0), (29.0, 63.0), (58.0, 92.0),
    ]
    assert plan[0]["core_end"] == 31.5
    assert plan[1]["core_start"] == 31.5
    assert plan[-1]["end"] == 234.684
    assert all(a["core_end"] == b["core_start"] for a, b in zip(plan, plan[1:]))


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf"), 1900])
def test_rejects_bad_duration_and_uncheckpointed_long_form(duration):
    with pytest.raises(ValueError):
        chunks.plan_source_windows(duration)


def test_core_boundaries_remove_duplicate_words_without_retiming_original():
    windows = chunks.plan_source_windows(48.0)
    decoded = [
        [segment(word(" Hello", 30.8, 31.1),
                 word(" overlap", 31.2, 31.8))],
        [segment(word(" overlap", 2.2, 2.8),
                 word(" world.", 2.9, 3.3))],
    ]
    cues = chunks.merge_owned_cues(windows, decoded, 48.0)
    assert [c["text"] for c in cues] == ["Hello", "overlap world."]
    assert [w["word"] for c in cues for w in c["words"]] == [
        " Hello", " overlap", " world.",
    ]
    assert cues[0]["end"] == 31.1
    assert cues[1]["start"] == 31.2
    assert [c["start"] for c in cues] == sorted(c["start"] for c in cues)


def test_missing_words_are_not_silently_published_as_good_english():
    windows = chunks.plan_source_windows(20.0)
    with pytest.raises(ValueError, match="without word timestamps"):
        chunks.merge_owned_cues(
            windows, [[SimpleNamespace(text="English hallucination", words=[])]],
            20.0,
        )


def test_collapsed_words_and_nonmonotone_output_fail_before_translation():
    windows = chunks.plan_source_windows(20.0)
    with pytest.raises(ValueError, match="Invalid source ASR word timing"):
        chunks.merge_owned_cues(windows, [[segment(word(" bad", 1.1, 1.1))]], 20.0)
    with pytest.raises(ValueError, match="out of time order"):
        chunks.merge_owned_cues(
            windows, [[segment(word(" later", 5.0, 5.5)),
                       segment(word(" earlier", 1.0, 1.5))]], 20.0,
        )


def test_bounded_source_inference_passes_real_model_parameters_once_per_window():
    windows_seen = []
    class FakeModel:
        def transcribe(self, audio, **kwargs):
            windows_seen.append((audio, kwargs))
            if len(windows_seen) == 1:
                return iter([segment(word(" Hello.", 30.8, 31.1))]), SimpleNamespace(language="en")
            return iter([segment(word(" world.", 2.9, 3.3))]), SimpleNamespace(language="en")

    cues, language = chunks.transcribe_bounded_source(
        FakeModel(), "source.mp4", "en",
        duration_reader=lambda _: 48.0,
        decoder=lambda _, start, length: (start, length),
    )
    assert language == "en"
    assert len(cues) == 2
    assert cues[0]["text"] == "Hello."
    assert cues[1]["text"] == "world."
    assert windows_seen[0][0] == (0.0, 34.0)
    assert windows_seen[1][0] == (29.0, 19.0)
    assert all(params == {
        "language": "en", "beam_size": 5, "word_timestamps": True,
        "condition_on_previous_text": True, "vad_filter": False,
    } for _, params in windows_seen)


def test_worker_opt_in_and_default_stt_paths_remain_distinct(monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "_load_model", lambda: calls.append("load") or object())
    monkeypatch.setattr(worker, "_transcribe_with",
                        lambda *args: (["default"], "en"))
    monkeypatch.setattr(chunks, "transcribe_bounded_source",
                        lambda model, audio, language: (["bounded"], language))
    assert worker.transcribe("source.mp4", "en", True) == (["default"], "en")
    assert worker.transcribe("source.mp4", "en", True, bounded_source=True) == (["bounded"], "en")
    assert calls == ["load", "load"]
    with pytest.raises(ValueError, match="needs word timestamps"):
        worker.transcribe("source.mp4", "en", False, bounded_source=True)
    with pytest.raises(ValueError, match="source language"):
        worker.transcribe("source.mp4", None, True, bounded_source=True)


def test_bridge_only_adds_flag_when_explicitly_requested(monkeypatch, tmp_path):
    original = tmp_path / "source.mp4"
    original.write_bytes(b"video")
    monkeypatch.setattr(stt_local, "STT_PYTHON", "/usr/bin/true")
    monkeypatch.setattr(stt_local, "SCRIPT_PATH", "/usr/bin/true")
    commands = []
    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        path = cmd[cmd.index("--output") + 1]
        import json
        with open(path, "w") as stream:
            json.dump({"ok": True, "language": "en",
                       "segments": [{"start": 0.0, "end": 1.0,
                                     "text": "Hello."}]}, stream)
        return SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(stt_local, "_run", fake_run)
    stt_local.transcribe_local(str(original), language="en", word_timestamps=True)
    stt_local.transcribe_local(str(original), language="en", word_timestamps=True,
                               bounded_source=True)
    assert "--bounded-source" not in commands[0]
    assert "--bounded-source" in commands[1]
    with pytest.raises(ValueError, match="explicit source language"):
        stt_local.transcribe_local(str(original), language=None, word_timestamps=True,
                                   bounded_source=True)


def test_pipeline_config_applies_only_to_explicit_source_language(monkeypatch):
    captured = []
    logs = []
    monkeypatch.setattr(
        pipeline.settings_env, "current_value", lambda key: "bounded"
        if key == "PERSODUB_SOURCE_ASR_MODE" else "",
    )
    def fake_transcribe(path, **kwargs):
        captured.append(kwargs)
        return [{"start": 0.5, "end": 1.5, "text": "Hello."}]
    monkeypatch.setattr(pipeline, "transcribe_local", fake_transcribe)
    _ = pipeline._stage_transcribe_local(
        "source.mp4", "en", None, logs.append,
    )
    _ = pipeline._stage_transcribe_local(
        "source.mp4", None, None, logs.append,
    )
    assert captured[0]["bounded_source"] is True
    assert "bounded_source" not in captured[1]
    assert any("source language first" in line for line in logs)

    with pytest.raises(ValueError, match="en, de or es"):
        chunks.transcribe_bounded_source(
            object(), "source.mp4", "ko", duration_reader=lambda _: 48.0,
        )


def test_real_ffmpeg_reads_bounded_source_pcm_without_side_effects(tmp_path):
    import shutil
    import subprocess

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe required")
    source = tmp_path / "original.wav"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", "sine=frequency=440:sample_rate=48000:duration=2",
        "-ac", "2", str(source),
    ], check=True, capture_output=True, timeout=20)
    original = source.read_bytes()
    assert 1.99 <= chunks.source_duration(source) <= 2.01
    pcm = chunks.decode_window(source, 0.25, 1.0)
    assert len(pcm) == 16000
    assert max(abs(float(v)) for v in pcm[:1000]) > 0.001
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    ("existing_mode", "existing_language", "requested_mode", "requested_language", "should_reuse"),
    [
        (None, None, "bounded", "en", False),
        ("bounded", "en", "bounded", "en", True),
        ("bounded", "en", "bounded", "de", False),
        ("bounded", "en", "default", "en", False),
        (None, None, "default", "en", True),
    ],
)
def test_resume_reuses_only_matching_source_asr_clock(
    monkeypatch, tmp_path, existing_mode, existing_language,
    requested_mode, requested_language, should_reuse,
):
    prior = [{"start": 1.0, "end": 2.0, "text": "stale source"}]
    new = [{"start": 1.2, "end": 2.2, "text": "redecoded source"}]
    record = {"cues": prior, "perso": False, "detected": "en"}
    if existing_mode is not None:
        record.update(source_asr_mode=existing_mode,
                      source_asr_language=existing_language)
    pipeline._save_json(str(tmp_path), pipeline.TRANSCRIPT_NAME, record)
    calls = []
    monkeypatch.setattr(
        pipeline.settings_env, "current_value",
        lambda key: requested_mode if key == "PERSODUB_SOURCE_ASR_MODE" else "",
    )
    monkeypatch.setattr(pipeline, "_stage_transcribe_local",
                        lambda *a, **k: calls.append(True) or (new, None, None))
    monkeypatch.setattr(pipeline, "snap_starts", lambda *args: 0)
    monkeypatch.setattr(pipeline, "_stage_diarize", lambda *args, **kwargs: None)
    logs = []
    cues, perso_cues, detected, _client, reused = pipeline._transcribe_or_reuse(
        "untouched.mp4", str(tmp_path), True, "unused-vocals.wav",
        "whisper", requested_language, None, None, None, None, None,
        logs.append,
    )
    assert reused is should_reuse
    assert len(calls) == (0 if should_reuse else 1)
    assert cues == (prior if should_reuse else new)
    assert perso_cues is None
    if not should_reuse:
        saved = pipeline._saved_transcript(str(tmp_path))
        assert saved["source_asr_mode"] == requested_mode
        assert saved["source_asr_language"] == (
            requested_language if requested_mode == "bounded" else None
        )
        assert any("rebuilding transcript" in line for line in logs)
