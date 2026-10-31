"""Qwen and finished-video integration for opt-in, event-driven overdub."""

import json
import struct
import subprocess
import wave

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
