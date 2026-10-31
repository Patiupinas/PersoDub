"""Existing job overdub re-export never re-runs TTS or doubles source music."""

import hashlib
import json
import shutil
import struct
import subprocess
import wave

import pytest

from app import vocal_overdub_export as exporter
from app.audio.overdub import OverdubError


def tone(path, duration=1, volume=15000, sr=48000):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        row = struct.pack("<hh", volume, volume)
        frames = int(duration * sr)
        for start in range(0, frames, 4800):
            wav.writeframesraw(row * min(4800, frames-start))
    return path


def test_existing_job_manifest_must_be_ordered_and_local(tmp_path):
    (tmp_path / "lines.json").write_text(json.dumps({
        "language": "Russian",
        "lines": [
            {"i": 0, "start": 0.5, "gain": 1.0},
            {"i": 1, "start": 1.5, "gain": 0.8},
        ],
    }))
    tone(tmp_path / "qwen_line_0.wav")
    paths, starts, gains = exporter._line_manifest(tmp_path)
    assert paths[0].endswith("qwen_line_0.wav")
    assert paths[1] is None
    assert starts == [0.5, 1.5]
    assert gains == [1.0, 0.8]
    bad = json.loads((tmp_path / "lines.json").read_text())
    bad["lines"][0]["start"] = float("nan")
    (tmp_path / "lines.json").write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="start"):
        exporter._line_manifest(tmp_path)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="ffmpeg unavailable")
def test_real_existing_job_exports_original_plus_dynamic_overdub(tmp_path):
    source = tmp_path / "input.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", "color=c=black:s=160x90:r=25:d=3",
        "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=48000:duration=3",
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "mpeg4",
        "-c:a", "aac", "-t", "3", str(source),
    ], check=True, capture_output=True)
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    voice = tone(tmp_path / "qwen_line_0.wav", duration=1.0, volume=18000)
    (tmp_path / "lines.json").write_text(json.dumps({
        "language": "Russian",
        "lines": [{"i": 0, "start": 0.25, "gain": 1.0}],
    }))
    plan_path = tmp_path / "overdub_events.json"
    plan = exporter.prepare_existing(source, tmp_path, plan_path)
    assert plan["events"][0]["action"] == "REVIEW"
    frames = plan["total_frames"]
    assert frames > 96000
    plan["events"] = [
        {"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"},
        {"start_frame": 48000, "end_frame": 96000, "action": "PRESERVE"},
        {"start_frame": 96000, "end_frame": frames, "action": "REVIEW"},
    ]
    plan_path.write_text(json.dumps(plan))
    movie = tmp_path / "overdub.mp4"
    result = exporter.export_existing(source, tmp_path, plan_path, movie)
    assert result["audio_tracks"] == ["Overdub", "Original"]
    assert result["action_frames"]["PRESERVE"] == 48000
    assert result["source_wav_sha256"] == plan["source_wav_sha256"]
    assert result["output_mp4"] == movie.name
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    assert voice.is_file()
    assert movie.exists() and movie.stat().st_size > 2000
    receipt = json.loads((tmp_path / "overdub.mp4.overdub.json").read_text())
    assert receipt == result
    probed = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type:stream_tags=handler_name", "-of", "json", str(movie),
    ], check=True, capture_output=True, text=True)
    streams = json.loads(probed.stdout)["streams"]
    assert [stream["codec_type"] for stream in streams] == ["video", "audio", "audio"]
    assert [stream["tags"]["handler_name"] for stream in streams[1:]] == [
        "Overdub", "Original"
    ]
    with pytest.raises(ValueError, match="must be new"):
        exporter.export_existing(source, tmp_path, plan_path, movie)


def test_invalid_output_parent_refused_before_media_processing(tmp_path):
    (tmp_path / "lines.json").write_text(json.dumps({
        "language": "Russian",
        "lines": [{"i": 0, "start": 0.2, "gain": 1.0}],
    }))
    tone(tmp_path / "qwen_line_0.wav")
    with pytest.raises(ValueError, match="inside"):
        exporter.export_existing(
            tmp_path / "input.mp4", tmp_path, tmp_path / "events.json",
            tmp_path.parent / "not-in-job.mp4",
        )


def test_line_paths_do_not_accept_user_provided_absolute_paths(tmp_path):
    (tmp_path / "lines.json").write_text(json.dumps({
        "language": "Russian",
        "lines": [
            {"i": 0, "start": 0.2, "gain": 1.0, "path": "/private/secret.wav"}
        ],
    }))
    with pytest.raises(ValueError, match="No synthesized"):
        exporter._line_manifest(tmp_path)


def test_review_plan_template_never_approves_model_hints(tmp_path):
    source = tone(tmp_path / "source.wav", duration=2.0)
    from app.audio.overdub import create_review_plan
    plan = create_review_plan(source, tmp_path / "events.json")
    assert plan["events"] == [{
        "start_frame": 0, "end_frame": 96000, "action": "REVIEW"
    }]
    with pytest.raises(OverdubError, match="new"):
        create_review_plan(source, tmp_path / "events.json")
