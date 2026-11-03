"""Qwen and finished-video integration for opt-in, event-driven overdub."""

import hashlib
import json
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from app import pipeline, qwen_pipeline
from app.audio.overdub import OverdubError, create_review_plan, write_silent_bed_like


def tone(path, seconds=2, rate=48000, volume=5000):
    with wave.open(str(path), "wb") as result:
        result.setnchannels(2)
        result.setsampwidth(2)
        result.setframerate(rate)
        remaining = int(seconds * rate)
        pulse = struct.pack("<hh", volume, volume)
        while remaining:
            frames = min(4800, remaining)
            result.writeframesraw(pulse * frames)
            remaining -= frames
    return path


def at(path, at_seconds):
    with wave.open(str(path), "rb") as audio:
        audio.setpos(int(round(at_seconds * audio.getframerate())))
        return struct.unpack("<hh", audio.readframes(1))[0]


def test_qwen_overdub_assembles_tts_only_not_demucs_background(tmp_path, monkeypatch):
    bed = tone(tmp_path / "background.wav", volume=6500)
    vocals = tone(tmp_path / "vocals.wav", volume=3500)
    line = tone(tmp_path / "qwen_line_0.wav", seconds=0.4, volume=9000)
    monkeypatch.setattr(
        qwen_pipeline, "apply_nonverbal_whitelist",
        lambda *a, **kw: pytest.fail("Whitelist must not double original voice in overdub"),
    )
    monkeypatch.setattr(
        qwen_pipeline, "apply_company_ambience",
        lambda *a, **kw: pytest.fail("Company gate must not double original voice in overdub"),
    )
    out = qwen_pipeline._assemble(
        [{"start": 0.5, "end": 1.0}], [str(line)], [0.5], [1.0],
        [{"start": 0.5, "end": 1.0}], str(vocals), str(bed),
        str(tmp_path), lambda msg: None, 2.0, output_mode="overdub",
    )
    assert at(out, 0.2) == 0
    assert at(out, 0.7) > 1000
    assert at(out, 1.5) == 0
    with wave.open(str(out), "rb") as f:
        assert f.getframerate() == 48000
        assert f.getnframes() == 96000


def test_silent_bed_clock_matches_original_background_at_44100(tmp_path):
    background = tone(tmp_path / "background.wav", seconds=1.25, rate=44100)
    silent = write_silent_bed_like(background, tmp_path / "blank.wav")
    with wave.open(silent, "rb") as out:
        assert out.getframerate() == 48000
        assert out.getnframes() == 60000
        assert set(out.readframes(4800)) == {0}


def test_pipeline_finisher_uses_two_stream_mux_and_preserving_length_gate(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(pipeline, "_video_duration", lambda video: 2.0)
    monkeypatch.setattr(
        pipeline.media, "mux_overdub",
        lambda *args: (calls.append(("mux", args)) or
                       subprocess.CompletedProcess([], 0, "", "")),
    )
    monkeypatch.setattr(
        pipeline.media, "ensure_video_length",
        lambda *args, **kwargs: calls.append(("length", args, kwargs)),
    )
    monkeypatch.setattr(
        pipeline, "cleanup_takes", lambda *args: calls.append(("cleanup", args)),
    )
    pipeline._stage_finish(
        "video.mp4", "overdub.wav", str(tmp_path / "final.mp4"),
        str(tmp_path), lambda msg: None, output_mode="overdub",
    )
    assert calls[0] == ("mux", ("video.mp4", "overdub.wav", str(tmp_path / "final.mp4"), 2.0))
    assert calls[1][2] == {"preserve_overdub_tracks": True}
    assert calls[2][0] == "cleanup"


def test_pipeline_rejects_missing_review_plan_without_spending_tts_work(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"synthetic video placeholder")
    monkeypatch.setattr(pipeline, "_duration_or_none", lambda path: 2.0)
    monkeypatch.setattr(pipeline, "_check_room", lambda *args: None)
    monkeypatch.setattr(pipeline, "_check_cancel", lambda *args: None)
    monkeypatch.setattr(
        pipeline, "_separate_or_reuse",
        lambda *args, **kwargs: pytest.fail("No separation before event validation"),
    )
    with pytest.raises(ValueError, match="requires a source-bound"):
        pipeline.run_dub(
            str(source), str(tmp_path / "final.mp4"),
            audio_mode="overdub", log=lambda msg: None,
        )
    with pytest.raises(ValueError, match="Unknown audio mode"):
        pipeline.run_dub(
            str(source), str(tmp_path / "final.mp4"),
            audio_mode="not-a-real-mode", log=lambda msg: None,
        )


def test_pipeline_rejects_wrong_source_event_clock_before_separation(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"synthetic video placeholder")
    captured = tone(tmp_path / "captured.wav")
    events = tmp_path / "events.json"
    create_review_plan(captured, events)
    obj = json.loads(events.read_text())
    obj["source_wav_sha256"] = "f" * 64
    events.write_text(json.dumps(obj))
    monkeypatch.setattr(pipeline, "_duration_or_none", lambda path: 2.0)
    monkeypatch.setattr(pipeline, "_check_room", lambda *args: None)
    monkeypatch.setattr(pipeline, "_check_cancel", lambda *args: None)
    monkeypatch.setattr(
        pipeline, "extract_original_pcm",
        lambda video, dest, duration: (tone(dest) and str(dest)),
    )
    monkeypatch.setattr(
        pipeline, "_separate_or_reuse",
        lambda *args, **kwargs: pytest.fail("No model work before plan validation"),
    )
    with pytest.raises(OverdubError, match="does not match"):
        pipeline.run_dub(
            str(source), str(tmp_path / "final.mp4"),
            audio_mode="overdub", overdub_event_plan_path=str(events),
            log=lambda msg: None,
        )


def test_unchanged_default_mode_does_not_create_new_source_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "_duration_or_none", lambda path: 3.0)
    monkeypatch.setattr(pipeline, "_check_room", lambda *args: None)
    monkeypatch.setattr(pipeline, "_check_cancel", lambda *args: None)
    def stop(*args, **kwargs):
        raise RuntimeError("Expected first separation stage")
    monkeypatch.setattr(pipeline, "_separate_or_reuse", stop)
    monkeypatch.setattr(
        pipeline, "extract_original_pcm",
        lambda *args, **kwargs: pytest.fail("Default path must not extract extra audio"),
    )
    with pytest.raises(RuntimeError, match="Expected first separation"):
        pipeline.run_dub(
            "synthetic.mp4", str(tmp_path / "final.mp4"),
            audio_mode="replace", log=lambda msg: None,
        )


def _review_spans(seconds):
    from app.audio.overdub import _Span
    return [_Span(round(a * 48000), round(b * 48000), status)
            for a, b, status in seconds]


def test_pretts_selects_only_entirely_approved_cues_and_leaves_source_intact():
    from app.audio.overdub import select_translatable_cues
    source = [
        {"start": 0.2, "end": 0.8, "text": "A"},
        {"start": 0.9, "end": 1.9, "text": "Crosses exercise"},
        {"start": 2.2, "end": 3.5, "text": "Exercise"},
        {"start": 3.6, "end": 4.5, "text": "B"},
        {"start": 4.9, "end": 5.8, "text": "Needs review"},
        {"start": 6.5, "end": 7.8, "text": "C"},
    ]
    approved = _review_spans([
        (0, 2, "TRANSLATE"), (2, 3.5, "PRESERVE"),
        (3.5, 4.8, "TRANSLATE"), (4.8, 6, "REVIEW"),
        (6, 8, "TRANSLATE"),
    ])
    selected, skipped = select_translatable_cues(source, approved)
    assert [s["text"] for s in selected] == ["A", "Crosses exercise", "B", "C"]
    assert skipped == 2
    assert [s["dub_limit_s"] for s in selected] == [2, 2, 4.8, 8]
    assert "dub_limit_s" not in source[0]
    assert len(source) == 6


def test_pretts_skips_partially_approved_and_merges_adjacent_translate():
    from app.audio.overdub import select_translatable_cues
    cues = [
        {"start": 0.5, "end": 2.5, "text": "Across approved split"},
        {"start": 2.8, "end": 4.2, "text": "Crosses preserve"},
        {"start": 5.0, "end": 5.8, "text": "Unreviewed"},
    ]
    events = _review_spans([
        (0, 1.2, "TRANSLATE"), (1.2, 3.0, "TRANSLATE"),
        (3.0, 4.0, "PRESERVE"), (4.0, 4.6, "TRANSLATE"),
        (4.6, 6, "REVIEW"),
    ])
    approved, skipped = select_translatable_cues(cues, events)
    assert [v["text"] for v in approved] == ["Across approved split"]
    assert approved[0]["dub_limit_s"] == 3
    assert skipped == 2


def test_pretts_never_approves_when_all_intervals_are_review():
    from app.audio.overdub import select_translatable_cues
    approved, skipped = select_translatable_cues(
        [{"start": 0.0, "end": 1.0, "text": "Do not synthesize"}],
        _review_spans([(0, 2, "REVIEW")]),
    )
    assert approved == []
    assert skipped == 1


def _run_fake_a4_pipeline(tmp_path, monkeypatch, actions, *, mutate_plan_during_tts=False):
    from app.audio.overdub import validate_overdub_plan
    from app.vocal_overdub_review import approved_plan

    source_video = tmp_path / "in.mp4"
    source_video.write_bytes(b"fake source video for deterministic tests")
    src_audio = tone(tmp_path / "original.wav", seconds=5)
    background = tone(tmp_path / "background.wav", seconds=5, volume=0)
    vocals = tone(tmp_path / "vocals.wav", seconds=5, volume=1000)
    plan = tmp_path / "approved-a4.json"

    source_hash = hashlib.sha256(src_audio.read_bytes()).hexdigest()
    spans = [{"start_frame": int(a * 48000), "end_frame": int(b * 48000),
              "action": action} for a, b, action in actions]
    plan.write_text(json.dumps(approved_plan(5 * 48000, source_hash, spans)))
    assert validate_overdub_plan(src_audio, plan)
    source_cues = [{"start": 0.0, "end": 5.0, "text": "source reference speech"}]
    translated = [
        {"start": 0.1, "end": 0.9, "text": "one"},
        {"start": 1.0, "end": 1.6, "text": "crosses the exercise"},
        {"start": 2.5, "end": 3.5, "text": "unknown"},
        {"start": 4.1, "end": 4.8, "text": "last"},
    ]
    calls = []

    monkeypatch.setattr(pipeline, "_duration_or_none", lambda _: 5.0)
    monkeypatch.setattr(pipeline, "_video_duration", lambda _: 5.0)
    monkeypatch.setattr(pipeline, "_check_room", lambda *_args: None)
    monkeypatch.setattr(pipeline, "_check_cancel", lambda *_args: None)
    monkeypatch.setattr(pipeline, "extract_original_pcm",
                        lambda _video, dest, duration=None:
                        (shutil.copyfile(src_audio, dest) or dest))
    monkeypatch.setattr(pipeline, "_separate_or_reuse",
                        lambda *_args, **_kwargs:
                        (str(vocals), str(background), None, "fake", False))
    monkeypatch.setattr(pipeline, "_transcribe_or_reuse",
                        lambda *_args, **_kwargs:
                        (source_cues, None, "en", None, False))
    monkeypatch.setattr(pipeline, "_pick_source_cues",
                        lambda *_args: source_cues)
    monkeypatch.setattr(pipeline, "_translate_or_reuse",
                        lambda *_args, **_kwargs: (translated, False, False))
    monkeypatch.setattr(pipeline, "leakage_gate",
                        lambda audio, *_args: audio)
    monkeypatch.setattr(pipeline, "_result_of",
                        lambda *_args: {"out_path": "fake", "num_segments": len(translated)})

    def qwen_stub(_engine, cues, _refs, work_dir, *_args, **kwargs):
        calls.append({"cues": list(cues), "kwargs": kwargs})
        if mutate_plan_during_tts:
            changed = json.loads(plan.read_text())
            changed["events"][0]["action"] = "PRESERVE"
            plan.write_text(json.dumps(changed))
        path = tone(Path(work_dir) / "qwen_dub_48k.wav",
                    seconds=5, volume=7000)
        return str(path)

    monkeypatch.setattr(pipeline, "run_qwen_dub", qwen_stub)
    monkeypatch.setattr(pipeline.media, "mux_overdub",
                        lambda *_args: subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(pipeline.media, "ensure_video_length",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "cleanup_takes", lambda *_args: None)
    output = tmp_path / "finished.mp4"
    log = []
    result = pipeline.run_dub(str(source_video), str(output), audio_mode="overdub",
                              overdub_event_plan_path=str(plan), qwen_engine=object(),
                              language="Russian", source_language_code="en",
                              log=log.append)
    expected_selected = len(calls[0]["cues"]) if calls else 0
    assert result["a4_synthesis"]["selected"] == expected_selected
    assert result["a4_synthesis"]["source_only"] == 4 - expected_selected
    persisted = json.loads((tmp_path / "speech_coverage.json").read_text())
    assert persisted == result["a4_synthesis"]["coverage"]
    assert persisted["translated_cues"] == expected_selected
    assert persisted["source_only_cues"] == 4 - expected_selected
    assert any("Source speech coverage:" in item for item in log)
    return calls, log, tmp_path


def test_real_pipeline_a4_gates_tts_before_synthesis_and_preserves_full_script(
        tmp_path, monkeypatch):
    actions = [
        (0, 1.2, "TRANSLATE"), (1.2, 2.3, "PRESERVE"),
        (2.3, 4.0, "REVIEW"), (4.0, 5.0, "TRANSLATE"),
    ]
    calls, logs, folder = _run_fake_a4_pipeline(tmp_path, monkeypatch, actions)
    assert len(calls) == 1
    selected = calls[0]["cues"]
    assert [row["text"] for row in selected] == ["one", "last"]
    assert [row["dub_limit_s"] for row in selected] == [1.2, 5.0]
    assert calls[0]["kwargs"]["output_mode"] == "overdub"
    assert any("2/4 translated cues allowed" in row for row in logs)
    assert (folder / "overdub_receipt.json").is_file()
    assert (folder / "a4_tts_selection.json").is_file()
    # The fake Qwen emitted five seconds of continuous sound. The actual
    # approved renderer must still pass protected source samples unchanged.
    for timepoint in (1.6, 3.0):
        assert at(folder / "overdub_mixed_48k.wav", timepoint) == at(
            folder / "original.wav", timepoint
        )
    assert at(folder / "overdub_mixed_48k.wav", 0.6) != at(
        folder / "original.wav", 0.6
    )


def test_real_pipeline_a4_all_review_never_calls_qwen(tmp_path, monkeypatch):
    actions = [(0, 5, "REVIEW")]
    calls, logs, folder = _run_fake_a4_pipeline(tmp_path, monkeypatch, actions)
    assert calls == []
    assert any("source-only Overdub" in row for row in logs)
    assert json.loads((folder / "lines.json").read_text())["lines"] == []
    with wave.open(str(folder / "qwen_dub_48k.wav")) as generated:
        assert generated.getnframes() == 5 * 48000
        assert set(generated.readframes(4800)) == {0}



def test_a4_resume_fingerprint_rejects_modified_source_cues_and_approval(tmp_path):
    from app.pipeline import (
        _a4_tts_fingerprint,
        _a4_tts_mark_success,
        _a4_tts_resume_matches,
    )

    selected = [{"start": 0.0, "end": 1.2, "text": "Russian speech",
                 "dub_limit_s": 1.2}]
    ref = [{"start": 0.0, "end": 2.0, "text": "original English"}]
    fingerprint = _a4_tts_fingerprint("a" * 64, "b" * 64, selected,
                                      ref, "Russian")
    assert not _a4_tts_resume_matches(str(tmp_path), fingerprint)
    _a4_tts_mark_success(str(tmp_path), fingerprint)
    assert _a4_tts_resume_matches(str(tmp_path), fingerprint)
    assert not _a4_tts_resume_matches(str(tmp_path), _a4_tts_fingerprint(
        "a" * 64, "c" * 64, selected, ref, "Russian"))
    shifted = [dict(selected[0], dub_limit_s=1.1)]
    assert not _a4_tts_resume_matches(str(tmp_path), _a4_tts_fingerprint(
        "a" * 64, "b" * 64, shifted, ref, "Russian"))
    assert not _a4_tts_resume_matches(str(tmp_path), _a4_tts_fingerprint(
        "a" * 64, "b" * 64, selected, ref, "Spanish"))
    assert not _a4_tts_resume_matches(str(tmp_path), _a4_tts_fingerprint(
        "a" * 64, "b" * 64, selected, ref, "Russian", n_takes=7))


def test_a4_plan_changed_during_synthesis_stops_before_mixing(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="A4 event plan changed during synthesis"):
        _run_fake_a4_pipeline(
            tmp_path, monkeypatch,
            [(0, 1.2, "TRANSLATE"), (1.2, 2.3, "PRESERVE"),
             (2.3, 4.0, "REVIEW"), (4.0, 5.0, "TRANSLATE")],
            mutate_plan_during_tts=True,
        )
    assert not (tmp_path / "overdub_mixed_48k.wav").exists()


def test_qwen_overdub_a4_assembly_never_places_voice_into_protected_interval(
        tmp_path, monkeypatch):
    from app import qwen_assemble

    monkeypatch.setattr(qwen_assemble, "QWEN_MAX_SPEEDUP", 1.0)
    bg = tone(tmp_path / "background.wav", seconds=3, volume=0)
    vocals = tone(tmp_path / "vocals.wav", seconds=3, volume=1000)
    voice = tone(tmp_path / "line.wav", seconds=1.1, volume=7500)
    output = qwen_pipeline._assemble(
        [{"start": 0.2, "end": 0.6, "text": "short",
          "dub_limit_s": 0.6}],
        [str(voice)], [0.2], [1.0],
        [{"start": 0.2, "end": 0.6}],
        str(vocals), str(bg), str(tmp_path),
        lambda _msg: None, 3.0, output_mode="overdub",
    )
    assert at(output, 0.35) > 0
    assert at(output, 0.8) == 0
    ledger = json.loads((tmp_path / "clipped_lines.json").read_text())
    assert ledger["clipped_count"] == 1
    assert ledger["clipped"][0]["cut_s"] >= 0.69


def test_a4_clipped_qa_uses_original_source_cue_numbers_not_filtered_tts_indices(tmp_path):
    """The real 17-cue run's clipped line 11 is source cue 26, not 27."""
    approved = _review_spans([
        (0, 2, "TRANSLATE"), (2, 3, "REVIEW"),
        (3, 5, "TRANSLATE"), (5, 6, "REVIEW"),
        (6, 8, "TRANSLATE"),
    ])
    source = [
        {"start": 0.1, "end": 1.1, "text": "A"},
        {"start": 2.1, "end": 2.6, "text": "Protected 2"},
        {"start": 3.2, "end": 4.7, "text": "B"},
        {"start": 5.2, "end": 5.8, "text": "Protected 4"},
        {"start": 6.1, "end": 7.1, "text": "C"},
    ]
    from app.audio.overdub import select_translatable_cues
    picked, skipped = select_translatable_cues(source, approved)
    assert skipped == 2
    assert [c["source_cue_number"] for c in picked] == [1, 3, 5]
    assert all("source_cue_number" not in row for row in source)

    ledger = {"clipped_count": 2, "clipped": [
        {"line": 2, "cut_s": 1.974},
        {"line": 3, "cut_s": 0.192},
    ]}
    path = tmp_path / "clipped_lines.json"
    path.write_text(json.dumps(ledger))
    pipeline._a4_remap_clipped_source_cues(tmp_path, picked)
    after = json.loads(path.read_text())
    assert after["clipped_count"] == 2
    assert after["clipped"] == [
        {"line": 3, "selected_line": 2, "cut_s": 1.974},
        {"line": 5, "selected_line": 3, "cut_s": 0.192},
    ]
    # Re-exporting a finished job cannot remap the source indexes twice.
    pipeline._a4_remap_clipped_source_cues(tmp_path, picked)
    assert json.loads(path.read_text()) == after


def test_a4_tts_fingerprint_never_reuses_qwen_voice_for_a_russian_preset_engine():
    from app.pipeline import _a4_tts_fingerprint

    content = [{"start": 0, "end": 2, "text": "Привет"}]
    reference = [{"start": 0, "end": 2, "text": "Hello", "speaker_id": "SPK0"}]
    original = _a4_tts_fingerprint("a" * 64, "b" * 64, content, reference, "Russian",
                                   engine_id="qwen3_tts")
    russian = _a4_tts_fingerprint("a" * 64, "b" * 64, content, reference, "Russian",
                                  engine_id="silero_ru")
    assert original != russian
    assert original == _a4_tts_fingerprint("a" * 64, "b" * 64, content, reference,
                                            "Russian", engine_id="qwen3_tts")
