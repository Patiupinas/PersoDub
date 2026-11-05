"""Real FastAPI local-job Overdub export with explicit reviewed intervals."""

import json
import shutil
import struct
import subprocess
import wave

import pytest
from fastapi.testclient import TestClient

from app import state
from app.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def _line(path, frames=48000, amplitude=11000):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(48000)
        pulse = struct.pack("<hh", amplitude, amplitude)
        for first in range(0, frames, 4800):
            f.writeframesraw(pulse * min(4800, frames - first))


@pytest.fixture
def local_job(tmp_path, monkeypatch):
    source = tmp_path / "input.mp4"
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is required for real end-to-end media tests")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s=160x90:r=25:d=3",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "mpeg4",
        "-c:a", "aac", "-t", "3", str(source),
    ], check=True, capture_output=True)
    _line(tmp_path / "qwen_line_0.wav", 36000)
    (tmp_path / "lines.json").write_text(json.dumps({
        "language": "Russian",
        "lines": [{"i": 0, "start": 0.2, "gain": 1.0}],
    }))
    (tmp_path / "original.srt").write_text(
        "1\n00:00:00,200 --> 00:00:01,000\nOriginal speech\n",
        encoding="utf-8",
    )
    job = {"id": "bench", "kind": "dub", "status": "done",
           "dub_mode": "local", "work_dir": str(tmp_path),
           "result": {"out_path": str(tmp_path / "dubbed.mp4")}}
    original_get = state.job_store.get
    monkeypatch.setattr(
        state.job_store, "get",
        lambda jid: job if jid == "bench" else original_get(jid),
    )
    monkeypatch.delenv("PERSODUB_AST_PYTHON", raising=False)
    monkeypatch.delenv("PERSODUB_AST_MODEL_DIR", raising=False)
    return job


def test_unknown_and_unfinished_projects_not_exportable(monkeypatch):
    assert client.post("/api/dub/jobs/nope/overdub/prepare", json={}).status_code == 404
    monkeypatch.setattr(state.job_store, "get", lambda jid: {
        "id": jid, "kind": "dub", "status": "running",
    })
    assert client.post("/api/dub/jobs/unfinished/overdub/prepare", json={}).status_code == 409


def test_prepare_shows_only_unapproved_cues_and_original_clock(local_job):
    response = client.post("/api/dub/jobs/bench/overdub/prepare", json={"analyze": False})
    assert response.status_code == 200, response.text
    info = response.json()
    assert len(info["source_wav_sha256"]) == 64
    assert info["sample_rate"] == 48000
    assert info["total_frames"] == 3 * 48000
    assert info["ast_available"] is False
    assert info["analysis"] == "not_requested"
    assert info["requires_review"] is True
    assert info["suggestions"][0]["start_frame"] == 0
    assert info["suggestions"][-1]["end_frame"] == info["total_frames"]
    assert all(row["action"] == "REVIEW" for row in info["suggestions"])
    assert any(row["suggested_action"] == "TRANSLATE" for row in info["suggestions"])
    assert all(row["end_frame"] == later["start_frame"]
               for row, later in zip(info["suggestions"], info["suggestions"][1:]))


def test_unconfigured_ast_keeps_suggestions_unapproved(local_job):
    response = client.post("/api/dub/jobs/bench/overdub/prepare", json={"analyze": True})
    assert response.status_code == 200, response.text
    assert response.json()["analysis"] == "model_not_configured"
    assert all(row["action"] == "REVIEW" for row in response.json()["suggestions"])


def test_requires_explicit_review_and_exact_original_source(local_job):
    info = client.post("/api/dub/jobs/bench/overdub/prepare", json={}).json()
    reviewed = {
        "source_wav_sha256": info["source_wav_sha256"],
        "total_frames": info["total_frames"],
        "events": [
            {"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"},
            {"start_frame": 48000, "end_frame": info["total_frames"], "action": "PRESERVE"},
        ],
    }
    assert client.post("/api/dub/jobs/bench/overdub/export", json=reviewed).status_code == 422
    assert client.post("/api/dub/jobs/bench/overdub/export", json={
        **reviewed, "review_confirmed": True, "source_wav_sha256": "f" * 64,
    }).status_code == 422
    assert client.post("/api/dub/jobs/bench/overdub/export", json={
        **reviewed, "review_confirmed": True,
        "events": [{"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"}],
    }).status_code == 422
    output = client.post("/api/dub/jobs/bench/overdub/export", json={
        **reviewed, "review_confirmed": True,
    })
    assert output.status_code == 200, output.text
    data = output.json()
    assert data["receipt"]["audio_tracks"] == ["Overdub", "Original"]
    assert data["receipt"]["action_frames"]["TRANSLATE"] == 48000
    video = client.get(data["download_url"])
    assert video.status_code == 200
    assert len(video.content) > 2000
    assert client.get("/api/dub/jobs/bench/overdub/files/input.mp4").status_code == 404
    assert client.get("/api/dub/jobs/bench/overdub/files/finished-overdub-999.mp4").status_code == 404
    # A second export gets a new filename, without replacing the first.
    second = client.post("/api/dub/jobs/bench/overdub/export", json={
        **reviewed, "review_confirmed": True, "fade_ms": 200,
    })
    assert second.status_code == 200, second.text
    assert second.json()["file"] != data["file"]


def test_explicit_ast_invocation_is_only_a_source_bound_suggestion(local_job, tmp_path, monkeypatch):
    import hashlib
    from pathlib import Path

    import app.api.overdub as overdub_api

    model_dir = tmp_path / "cached-ast"
    model_dir.mkdir()
    isolated_python = tmp_path / "ml-python"
    isolated_python.write_text("synthetic executable for isolated observer test")
    monkeypatch.setattr(
        overdub_api.settings_env, "current_value",
        lambda key: str(isolated_python) if key == "PERSODUB_AST_PYTHON"
        else str(model_dir) if key == "PERSODUB_AST_MODEL_DIR" else "",
    )
    real_subprocess_run = subprocess.run
    observed_calls = []

    def fake_ast_call(cmd, **kwargs):
        if cmd[0] != str(isolated_python):
            return real_subprocess_run(cmd, **kwargs)
        observed_calls.append((cmd, kwargs))
        original = Path(cmd[cmd.index("--original") + 1])
        output = Path(cmd[cmd.index("--output") + 1])
        with wave.open(str(original), "rb") as f:
            total = f.getnframes()
        scores = {
            "speech": 0.94, "singing": 0.01, "laughing": 0.02,
            "crying_baby": 0.01, "coughing": 0.01,
            "sneezing": 0.01, "breathing": 0.02,
        }
        output.write_text(json.dumps({
            "schema_version": 1, "sample_rate": 48000, "total_frames": total,
            "source_wav_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
            "model": "MIT/ast-finetuned-audioset-12-12-0.447",
            "model_weights_sha256":
                "d87987744d05c134a9f4294568888832b94ad3a9a2d62a3e3a8de5d793eb1918",
            "windows": [{"start_frame": 0, "end_frame": total, "scores": scores}],
        }), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(overdub_api.subprocess, "run", fake_ast_call)
    response = client.post("/api/dub/jobs/bench/overdub/prepare", json={"analyze": True})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["ast_available"] is True
    assert result["analysis"] == "ast_observations"
    assert len(observed_calls) == 1
    assert all(row["action"] == "REVIEW" for row in result["suggestions"])
    assert all(row["hint"] == "speech" for row in result["suggestions"])
    assert all(row["suggested_action"] == "TRANSLATE" for row in result["suggestions"])


def test_wrong_ast_source_sha_falls_back_to_unapproved_cues(local_job, tmp_path, monkeypatch):
    import app.api.overdub as overdub_api

    model_dir = tmp_path / "cached-ast"
    model_dir.mkdir()
    isolated_python = tmp_path / "ml-python"
    isolated_python.write_text("synthetic")
    monkeypatch.setattr(
        overdub_api.settings_env, "current_value",
        lambda key: str(isolated_python) if key == "PERSODUB_AST_PYTHON"
        else str(model_dir) if key == "PERSODUB_AST_MODEL_DIR" else "",
    )
    real_subprocess_run = subprocess.run

    def fake_bad_observer(cmd, **kwargs):
        if cmd[0] != str(isolated_python):
            return real_subprocess_run(cmd, **kwargs)
        from pathlib import Path

        path = Path(cmd[cmd.index("--output") + 1])
        path.write_text(json.dumps({
            "schema_version": 1, "sample_rate": 48000,
            "source_wav_sha256": "f" * 64, "total_frames": 144000,
            "model": "MIT/ast-finetuned-audioset-12-12-0.447",
            "model_weights_sha256":
                "d87987744d05c134a9f4294568888832b94ad3a9a2d62a3e3a8de5d793eb1918",
            "windows": [{
                "start_frame": 0, "end_frame": 144000,
                "scores": {
                    "speech": 0.99, "singing": 0.0, "laughing": 0.0,
                    "crying_baby": 0.0, "coughing": 0.0,
                    "sneezing": 0.0, "breathing": 0.0,
                },
            }],
        }), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(overdub_api.subprocess, "run", fake_bad_observer)
    result = client.post(
        "/api/dub/jobs/bench/overdub/prepare", json={"analyze": True}
    )
    assert result.status_code == 200
    assert result.json()["analysis"] == "model_failed"
    assert all(r["action"] == "REVIEW" for r in result.json()["suggestions"])


def test_overdub_download_rejects_symlink_outside_job(local_job, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside.mp4")
    outside.write_bytes(b"OTHER PROJECT SOURCE")
    link = tmp_path / "finished-overdub-99.mp4"
    link.symlink_to(outside)
    response = client.get("/api/dub/jobs/bench/overdub/files/finished-overdub-99.mp4")
    assert response.status_code == 404
    outside.unlink()


def test_six_hour_source_budget_is_accepted_but_riff_overflow_is_rejected():
    from app.api.overdub import _ast_timeout, _audio_size
    from app.audio.overdub import OverdubError

    assert _audio_size(6 * 3600) == 6 * 3600 * 48000 * 4
    assert _ast_timeout(6 * 3600) > 900
    assert _ast_timeout(100) == 900
    with pytest.raises(OverdubError, match="single-WAV export"):
        _audio_size(7 * 3600)
    with pytest.raises(OverdubError, match="duration"):
        _audio_size(float("nan"))


def test_longform_preview_rejects_riff_overflow_before_audio_decode(local_job, monkeypatch):
    import app.api.overdub as overdub_api

    monkeypatch.setattr(overdub_api.media, "video_duration", lambda path: 7 * 3600)
    monkeypatch.setattr(
        overdub_api, "extract_original_pcm",
        lambda *args, **kwargs: pytest.fail("Overflow preflight must run before decoding"),
    )
    result = client.post("/api/dub/jobs/bench/overdub/prepare", json={})
    assert result.status_code == 422


def test_longform_export_requires_room_for_all_audio_and_video_intermediates(local_job, monkeypatch):
    from collections import namedtuple

    import app.api.overdub as overdub_api

    Usage = namedtuple("Usage", ["total", "used", "free"])
    monkeypatch.setattr(overdub_api.shutil, "disk_usage", lambda path: Usage(0, 0, 100))
    info = client.post("/api/dub/jobs/bench/overdub/prepare", json={}).json()
    response = client.post("/api/dub/jobs/bench/overdub/export", json={
        "source_wav_sha256": info["source_wav_sha256"],
        "total_frames": info["total_frames"], "review_confirmed": True,
        "events": [{
            "start_frame": 0, "end_frame": info["total_frames"], "action": "REVIEW",
        }],
    })
    assert response.status_code == 422
    assert "free disk" in response.json()["detail"]


def test_original_a4_source_stream_has_inline_byte_range(local_job):
    from pathlib import Path

    src = Path(local_job["work_dir"]) / "input.mp4"
    original = src.read_bytes()
    response = client.get("/api/dub/jobs/bench/overdub/source",
                          headers={"Range": "bytes=0-63"})
    assert response.status_code == 206
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["content-range"].startswith("bytes 0-63/")
    assert "attachment" not in response.headers.get("content-disposition", "")
    assert response.content == original[:64]
    assert src.read_bytes() == original


def test_a4_source_playback_respects_completed_local_job_scope(local_job, monkeypatch):
    assert client.get("/api/dub/jobs/unknown/overdub/source").status_code == 404
    monkeypatch.setattr(state.job_store, "get", lambda jid: {
        "id": jid, "kind": "dub", "status": "running",
    })
    assert client.get("/api/dub/jobs/bench/overdub/source").status_code == 409


def _ready_regeneration_source(local_job, tmp_path):
    # Reuse the original source and stage manifests, never fake a successful
    # expensive ASR/separation stage in the new job's own working directory.
    original = tmp_path / "original.srt"
    assert original.is_file()
    (tmp_path / "translated.srt").write_text(
        "1\n00:00:00,200 --> 00:00:01,000\nРусская реплика\n",
        encoding="utf-8",
    )
    _line(tmp_path / "vocals.wav", frames=3 * 48000, amplitude=2300)
    _line(tmp_path / "background.wav", frames=3 * 48000, amplitude=150)
    (tmp_path / "separated.json").write_text(json.dumps({
        "vocals": "vocals.wav", "background": "background.wav", "model": "cached"
    }))
    (tmp_path / "transcript.json").write_text(json.dumps({
        "cues": [{"start": 0.2, "end": 1, "text": "Original speech", "speaker_id": "SPK0"}],
        "detected": "en", "perso": False, "source_asr_mode": "default",
        "source_asr_language": None,
    }))
    local_job.update({
        "language": "Russian", "language_code": "ru", "source_lang": "en",
        "project": "Original Lesson", "quality": 2, "tts": "qwen3",
    })


def test_regenerate_start_uses_reviewed_a4_and_new_independent_project(
        local_job, tmp_path, monkeypatch):
    import app.api.overdub as api

    _ready_regeneration_source(local_job, tmp_path)
    reviewed_voice = {"version": 1, "speaker_to_register": {"SPK0": "male"}}
    (tmp_path / "russian_voice_register_overrides.json").write_text(json.dumps(reviewed_voice))
    new_work = tmp_path.parent / (tmp_path.name + "-selective-overdub")
    calls = []

    monkeypatch.setattr(api, "check_space", lambda path: None)
    monkeypatch.setattr(api, "job_dir", lambda title, code: (new_work.mkdir() or str(new_work)))
    monkeypatch.setattr(api, "_require_selected_voice_engine", lambda count, choice: calls.append(("voices", count, choice)))
    monkeypatch.setattr(api, "launch_job", lambda work, fields, intro, target:
                        (calls.append(("launch", work, fields, target)) or "fedcba12"))
    prep = client.post("/api/dub/jobs/bench/overdub/prepare", json={}).json()
    body = {
        "source_wav_sha256": prep["source_wav_sha256"],
        "total_frames": prep["total_frames"],
        "review_confirmed": True,
        "events": [
            {"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"},
            {"start_frame": 48000, "end_frame": 3 * 48000, "action": "PRESERVE"},
        ],
        "original_speech_db": -16, "dub_speech_db": -2, "fade_ms": 300,
    }
    response = client.post("/api/dub/jobs/bench/overdub/regenerate", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["job_id"] == "fedcba12"
    assert response.json()["approved_for_tts"] == 1
    assert response.json()["source_only"] == 0
    assert calls[0] == ("voices", 1, "qwen3")
    launch = calls[1]
    assert launch[0] == "launch"
    assert launch[2]["audio_mode"] == "overdub"
    assert launch[2]["overdub_source_job"] == "bench"
    assert launch[2]["language"] == "Russian"
    assert launch[2]["quality"] == 2
    assert launch[2]["work_dir"] == str(new_work)
    assert (new_work / "input.mp4").read_bytes() == (tmp_path / "input.mp4").read_bytes()
    assert (new_work / "sub.srt").read_text() == (tmp_path / "translated.srt").read_text()
    assert (new_work / "source.srt").read_text() == (tmp_path / "original.srt").read_text()
    assert (new_work / "separated.json").is_file()
    assert (new_work / "transcript.json").is_file()
    assert (new_work / "vocals.wav").read_bytes() == (tmp_path / "vocals.wav").read_bytes()
    assert (new_work / "background.wav").read_bytes() == (tmp_path / "background.wav").read_bytes()
    assert json.loads((new_work / "russian_voice_register_overrides.json").read_text()) == reviewed_voice
    assert not list(new_work.glob("qwen_line_*.wav"))
    assert json.loads((new_work / "overdub_events.json").read_text())["events"] == body["events"]
    assert json.loads((new_work / "overdub_levels.json").read_text()) == {
        "original_speech_db": -16, "dub_speech_db": -2, "fade_ms": 300,
    }
    assert not (tmp_path / "overdub_events.json").exists()
    assert (tmp_path / "input.mp4").is_file()
    # Running the registered target must delegate to the normal persisted job
    # pipeline, not hide a synchronous TTS run inside the HTTP route.
    assert callable(launch[3])


def test_regenerate_refuses_unreviewed_or_stale_source_before_creating_job(
        local_job, tmp_path, monkeypatch):
    import app.api.overdub as api

    _ready_regeneration_source(local_job, tmp_path)
    monkeypatch.setattr(api, "job_dir", lambda *_: pytest.fail("No new job folder on rejection"))
    prep = client.post("/api/dub/jobs/bench/overdub/prepare", json={}).json()
    event = [{"start_frame": 0, "end_frame": prep["total_frames"], "action": "TRANSLATE"}]
    body = {"source_wav_sha256": prep["source_wav_sha256"],
            "total_frames": prep["total_frames"], "events": event}
    assert client.post("/api/dub/jobs/bench/overdub/regenerate", json=body).status_code == 422
    assert client.post("/api/dub/jobs/bench/overdub/regenerate", json={
        **body, "review_confirmed": True, "source_wav_sha256": "f" * 64,
    }).status_code == 422
    assert client.post("/api/dub/jobs/bench/overdub/regenerate", json={
        **body, "review_confirmed": True,
        "events": [{"start_frame": 0, "end_frame": 48000, "action": "PRESERVE"}],
    }).status_code == 422


def test_regenerate_no_approved_speech_does_not_need_voice_engine(
        local_job, tmp_path, monkeypatch):
    import app.api.overdub as api

    _ready_regeneration_source(local_job, tmp_path)
    new_work = tmp_path.parent / (tmp_path.name + "-original-only")
    monkeypatch.setattr(api, "check_space", lambda *_: None)
    monkeypatch.setattr(api, "job_dir", lambda title, code: (new_work.mkdir() or str(new_work)))
    monkeypatch.setattr(api, "_require_selected_voice_engine", lambda count: (
        pytest.fail("No Qwen pack needed for zero eligible cues")))
    monkeypatch.setattr(api, "launch_job", lambda *_args: "1234abcd")
    prep = client.post("/api/dub/jobs/bench/overdub/prepare", json={}).json()
    resp = client.post("/api/dub/jobs/bench/overdub/regenerate", json={
        "source_wav_sha256": prep["source_wav_sha256"],
        "total_frames": prep["total_frames"],
        "events": [{"start_frame": 0, "end_frame": prep["total_frames"], "action": "REVIEW"}],
        "review_confirmed": True,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["approved_for_tts"] == 0
    assert resp.json()["job_id"] == "1234abcd"


def test_regenerate_requires_existing_source_caches_and_full_script(
        local_job, tmp_path, monkeypatch):
    import app.api.overdub as api

    _ready_regeneration_source(local_job, tmp_path)
    (tmp_path / "transcript.json").unlink()
    monkeypatch.setattr(api, "job_dir", lambda *_: pytest.fail("No job for missing cache"))
    prep = client.post("/api/dub/jobs/bench/overdub/prepare", json={}).json()
    res = client.post("/api/dub/jobs/bench/overdub/regenerate", json={
        "source_wav_sha256": prep["source_wav_sha256"],
        "total_frames": prep["total_frames"],
        "events": [{"start_frame": 0, "end_frame": prep["total_frames"], "action": "TRANSLATE"}],
        "review_confirmed": True,
    })
    assert res.status_code == 409
    assert "transcript" in res.text.lower()


@pytest.mark.parametrize("silent_separator_tail_frames", [0, 2452])
def test_selective_regeneration_real_mux_with_cached_source_no_models(
        local_job, tmp_path, monkeypatch, silent_separator_tail_frames):
    """Exercise the real FFmpeg source clock, pipeline stages, and two-track MP4."""
    import hashlib

    from app import pipeline
    from app.audio.overdub import (
        OverdubLevels,
        _open_pcm,
        _sha_file,
        extract_original_pcm,
    )
    from app.vocal_overdub_export import _verify_export_tracks
    from app.vocal_overdub_regenerate import seed_regeneration, source_inputs
    from app.vocal_overdub_review import approved_plan

    _ready_regeneration_source(local_job, tmp_path)
    inputs = source_inputs(tmp_path)
    source = tmp_path / "input.mp4"
    source_pcm = tmp_path / "source-48k.wav"
    extract_original_pcm(source, source_pcm, duration=3)
    with _open_pcm(source_pcm) as track:
        frames = track.getnframes()
    assert frames == 3 * 48000
    rows = [
        {"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"},
        {"start_frame": 48000, "end_frame": frames, "action": "PRESERVE"},
    ]
    plan = approved_plan(frames, _sha_file(source_pcm), rows)
    new_work = tmp_path / "regenerated"
    new_work.mkdir()
    seed_regeneration(inputs, new_work, plan, OverdubLevels(-16, -2, 300))
    expected_script = (tmp_path / "translated.srt").read_bytes()
    before_video = hashlib.sha256(source.read_bytes()).hexdigest()
    calls = []

    monkeypatch.setattr(
        pipeline, "_stage_separate",
        lambda *_a, **_k: pytest.fail("Cached separation must not rerun"),
    )
    monkeypatch.setattr(
        pipeline, "_stage_transcribe_local",
        lambda *_a, **_k: pytest.fail("Cached source ASR must not rerun"),
    )
    monkeypatch.setattr(
        pipeline, "_source_asr_mode",
        lambda _code: "bounded",  # mismatches old cache, must still reuse frozen source
    )
    monkeypatch.setattr(pipeline, "leakage_gate", lambda wav, *_a: wav)

    def fake_qwen(_engine, segments, _refs, work_dir, *_a, **_k):
        calls.append([dict(row) for row in segments])
        # Deliberately overlong TTS: the approved A4 final mix must never
        # replace the original PCM inside the protected exercise.
        out = tmp_path / "fake-voice.wav"
        _line(out, frames=3 * 48000 + silent_separator_tail_frames, amplitude=7000)
        if silent_separator_tail_frames:
            # This is the real AAC source/video clock difference, 2452 frames
            # observed on a 234.684-second source with a 234.633-second video.
            with out.open("r+b") as handle:
                handle.seek(-silent_separator_tail_frames * 4, 2)
                handle.write(b"\x00" * (silent_separator_tail_frames * 4))
        return str(out)

    monkeypatch.setattr(pipeline, "run_qwen_dub", fake_qwen)
    results = pipeline.run_dub(
        str(new_work / "input.mp4"), str(new_work / "dubbed.mp4"),
        srt_path=str(new_work / "sub.srt"),
        source_srt_path=str(new_work / "source.srt"),
        language="Russian", source_language_code="en",
        audio_mode="overdub", overdub_event_plan_path=str(new_work / "overdub_events.json"),
        overdub_levels=OverdubLevels(-16, -2, 300),
        qwen_engine=object(), resume=True, require_cached_source=True,
        log=lambda _: None,
    )
    assert results["a4_synthesis"]["selected"] == 1
    assert len(calls) == 1
    assert [x["text"] for x in calls[0]] == ["Русская реплика"]
    assert calls[0][0]["dub_limit_s"] == 1.0
    assert _verify_export_tracks(new_work / "dubbed.mp4")
    assert json.loads((new_work / "overdub_receipt.json").read_text())[
        "dub_tail_trimmed_frames"
    ] == silent_separator_tail_frames
    assert (new_work / "translated.srt").read_bytes() == expected_script
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before_video
    assert not list(new_work.glob("qwen_line_*.wav"))
    # Protected source is bit-identical outside the A4 crossfade.
    import wave
    with wave.open(str(new_work / "overdub_mixed_48k.wav")) as actual, wave.open(
        str(new_work / "overdub_original_48k.wav")
    ) as reference:
        pos = round(1.6 * 48000)
        actual.setpos(pos)
        reference.setpos(pos)
        assert actual.readframes(4800) == reference.readframes(4800)


def test_new_a4_mode_and_source_reference_survive_jobstore_restart(tmp_path):
    from app.jobs import JobStore

    work = tmp_path / "2026-11-03" / "source-overdub_ru"
    work.mkdir(parents=True)
    original = JobStore(log_dir=str(tmp_path / "log-original"))
    jid = original.create()
    original.update(
        jid, work_dir=str(work), audio_mode="overdub",
        overdub_source_job="abcd1234", language="Russian",
        language_code="ru", dub_mode="local",
    )
    original.persist(jid, str(work))
    restored = JobStore(log_dir=str(tmp_path / "log-restored"))
    restored.restore(str(tmp_path))
    record = restored.get(jid)
    assert record["audio_mode"] == "overdub"
    assert record["overdub_source_job"] == "abcd1234"


def test_dub_launch_passes_selective_source_contract_and_levels(tmp_path):
    from app.audio.overdub import OverdubLevels
    from app.dub_launch import work_for

    (tmp_path / "input.mp4").write_bytes(b"original")
    (tmp_path / "source.srt").write_text("source")
    (tmp_path / "sub.srt").write_text("target")
    (tmp_path / "overdub_levels.json").write_text(json.dumps({
        "original_speech_db": -13, "dub_speech_db": -4, "fade_ms": 250,
    }))
    called = []

    def fake_run_dub(**kwargs):
        called.append(kwargs)
        return {"audio_mode": "overdub"}

    worker = work_for({
        "id": "abcd1234", "work_dir": str(tmp_path),
        "language": "Russian", "language_code": "ru",
        "dub_mode": "local", "audio_mode": "overdub",
        "stt_engine": "whisper", "quality": 2,
    }, cancel_check=lambda: False, on_notice=lambda _: None,
        run_dub=fake_run_dub, resume=True)
    assert worker(lambda _: None)["audio_mode"] == "overdub"
    assert len(called) == 1
    kwargs = called[0]
    assert kwargs["resume"] is True
    assert kwargs["require_cached_source"] is True
    assert kwargs["audio_mode"] == "overdub"
    assert kwargs["overdub_event_plan_path"] == str(tmp_path / "overdub_events.json")
    assert kwargs["overdub_levels"] == OverdubLevels(-13, -4, 250)
    assert kwargs["srt_path"] == str(tmp_path / "sub.srt")
    assert kwargs["source_srt_path"] == str(tmp_path / "source.srt")


def test_regenerate_uses_latest_edited_translation_not_old_generated_voice(
        local_job, tmp_path):
    from app.audio.overdub import OverdubLevels
    from app.vocal_overdub_regenerate import seed_regeneration, source_inputs
    from app.vocal_overdub_review import approved_plan

    _ready_regeneration_source(local_job, tmp_path)
    (tmp_path / "edited.srt").write_text(
        "1\n00:00:00,200 --> 00:00:01,000\nИсправленный перевод\n",
        encoding="utf-8",
    )
    files = source_inputs(tmp_path)
    assert files["sub.srt"].name == "edited.srt"
    new_work = tmp_path / "fresh-edited"
    new_work.mkdir()
    seed_regeneration(files, new_work, approved_plan(
        48000, "a" * 64, [{"start_frame": 0, "end_frame": 48000, "action": "REVIEW"}],
    ), OverdubLevels())
    assert "Исправленный перевод" in (new_work / "sub.srt").read_text()
    assert "Русская реплика" in (tmp_path / "translated.srt").read_text()
    assert not list(new_work.glob("qwen_line*.wav"))


def test_regenerate_rejects_original_cache_stem_symlink_outside_source_project(
        local_job, tmp_path):
    from app.audio.overdub import OverdubError
    from app.vocal_overdub_regenerate import source_inputs

    _ready_regeneration_source(local_job, tmp_path)
    external = tmp_path.parent / (tmp_path.name + "-external.wav")
    _line(external)
    (tmp_path / "vocals.wav").unlink()
    (tmp_path / "vocals.wav").symlink_to(external)
    with pytest.raises(OverdubError, match="vocals"):
        source_inputs(tmp_path)


def test_a4_draft_roundtrip_resumes_edited_intervals_without_approval(local_job, tmp_path):
    preview = client.post("/api/dub/jobs/bench/overdub/prepare", json={}).json()
    assert preview["review_draft"] is None
    assert preview["draft_revision"] is None
    payload = {
        "source_wav_sha256": preview["source_wav_sha256"],
        "total_frames": preview["total_frames"],
        "expected_revision": None,
        "events": [
            {"start_frame": 0, "end_frame": 24000, "action": "TRANSLATE"},
            {"start_frame": 24000, "end_frame": 48000, "action": "PRESERVE"},
            {"start_frame": 48000, "end_frame": preview["total_frames"], "action": "REVIEW"},
        ],
        "original_speech_db": -12,
        "dub_speech_db": -3,
        "fade_ms": 150,
    }
    saved = client.post("/api/dub/jobs/bench/overdub/draft", json=payload)
    assert saved.status_code == 200, saved.text
    revision = saved.json()["revision"]
    assert len(revision) == 64
    saved_path = tmp_path / "overdub-review-draft.json"
    assert saved_path.is_file()
    assert json.loads(saved_path.read_text())["review_confirmed"] is False
    restored = client.post("/api/dub/jobs/bench/overdub/prepare", json={}).json()
    assert restored["draft_revision"] == revision
    assert restored["draft_stale"] is False
    assert restored["review_draft"]["events"] == payload["events"]
    assert restored["review_draft"]["original_speech_db"] == -12
    assert restored["review_draft"]["dub_speech_db"] == -3
    assert restored["review_draft"]["fade_ms"] == 150
    assert restored["review_draft"]["review_confirmed"] is False
    assert all(row["action"] == "REVIEW" for row in restored["suggestions"])


def test_a4_draft_rejects_stale_cas_and_wrong_media_without_overwriting(local_job, tmp_path):
    preview = client.post("/api/dub/jobs/bench/overdub/prepare", json={}).json()
    payload = {
        "source_wav_sha256": preview["source_wav_sha256"],
        "total_frames": preview["total_frames"],
        "expected_revision": None,
        "events": [
            {"start_frame": 0, "end_frame": preview["total_frames"], "action": "REVIEW"}
        ],
    }
    saved = client.post("/api/dub/jobs/bench/overdub/draft", json=payload)
    assert saved.status_code == 200
    old_sha = (tmp_path / "overdub-review-draft.json").read_bytes()
    assert client.post("/api/dub/jobs/bench/overdub/draft", json=payload).status_code == 409
    assert client.post("/api/dub/jobs/bench/overdub/draft", json={
        **payload, "expected_revision": saved.json()["revision"],
        "source_wav_sha256": "f"*64,
    }).status_code == 422
    assert client.post("/api/dub/jobs/bench/overdub/draft", json={
        **payload, "expected_revision": saved.json()["revision"],
        "events": [{"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"}],
    }).status_code == 422
    assert old_sha == (tmp_path / "overdub-review-draft.json").read_bytes()
    updated = client.post("/api/dub/jobs/bench/overdub/draft", json={
        **payload, "expected_revision": saved.json()["revision"],
        "events": [{"start_frame": 0, "end_frame": preview["total_frames"],
                    "action": "PRESERVE"}],
    })
    assert updated.status_code == 200
    assert updated.json()["revision"] != saved.json()["revision"]


def test_a4_draft_does_not_restore_on_changed_original_audio(local_job, tmp_path, monkeypatch):
    import app.api.overdub as api
    preview = client.post("/api/dub/jobs/bench/overdub/prepare", json={}).json()
    saved = client.post("/api/dub/jobs/bench/overdub/draft", json={
        "source_wav_sha256": preview["source_wav_sha256"],
        "total_frames": preview["total_frames"],
        "expected_revision": None,
        "events": [{"start_frame": 0, "end_frame": preview["total_frames"],
                    "action": "TRANSLATE"}],
    })
    assert saved.status_code == 200
    original = api.extract_original_pcm

    def modified_source(video, wav, duration):
        original(video, wav, duration)
        # Replacing a sample while keeping the same audio clock changes the
        # source identity. The old draft must remain available but inactive.
        with open(wav, "r+b") as f:
            f.seek(84)
            b = f.read(1)
            f.seek(84)
            f.write(bytes([b[0] ^ 1]))

    monkeypatch.setattr(api, "extract_original_pcm", modified_source)
    fresh = client.post("/api/dub/jobs/bench/overdub/prepare", json={}).json()
    assert fresh["source_wav_sha256"] != preview["source_wav_sha256"]
    assert fresh["review_draft"] is None
    assert fresh["draft_stale"] is True
    assert fresh["draft_revision"] == saved.json()["revision"]
    assert client.post("/api/dub/jobs/bench/overdub/draft", json={
        "source_wav_sha256": preview["source_wav_sha256"],
        "total_frames": preview["total_frames"],
        "expected_revision": saved.json()["revision"],
        "events": [{"start_frame": 0, "end_frame": preview["total_frames"],
                    "action": "TRANSLATE"}],
    }).status_code == 422
    # A new review can supersede the stale draft with its exact old revision.
    result = client.post("/api/dub/jobs/bench/overdub/draft", json={
        "source_wav_sha256": fresh["source_wav_sha256"],
        "total_frames": fresh["total_frames"],
        "expected_revision": fresh["draft_revision"],
        "events": [{"start_frame": 0, "end_frame": fresh["total_frames"],
                    "action": "REVIEW"}],
    })
    assert result.status_code == 200


def test_prepare_offers_automatic_source_and_current_russian_text_for_review(local_job, tmp_path):
    (tmp_path / "translated.srt").write_text(
        "1\n00:00:00,200 --> 00:00:01,000\nRussian draft\n", encoding="utf-8",
    )
    reply=client.post("/api/dub/jobs/bench/overdub/prepare",json={})
    assert reply.status_code==200
    data=reply.json()
    assert data["source_cues"] == [{"start": 0.2, "end": 1.0, "text": "Original speech"}]
    assert data["translated_cues"] == [{"start": 0.2, "end": 1.0, "text": "Russian draft"}]
    (tmp_path/"edited.srt").write_text(
        "1\n00:00:00,200 --> 00:00:01,000\nEdited translation\n",encoding="utf-8",
    )
    second=client.post("/api/dub/jobs/bench/overdub/prepare",json={}).json()
    assert second["translated_cues"][0]["text"]=="Edited translation"
    assert second["source_cues"]==data["source_cues"]
