"""Acceptance audit tests: a successful MP4 mux is not an audible-quality PASS."""

import json
import shutil
import struct
import subprocess
import wave

import pytest

from app import dub_quality_audit as quality


def _wav(path, seconds, rate=24000):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        data = struct.pack("<h", 7200) * 4096
        remaining = round(seconds * rate)
        while remaining:
            take = min(remaining, 4096)
            f.writeframesraw(data[:take * 2])
            remaining -= take


@pytest.fixture
def job(tmp_path, monkeypatch):
    root = tmp_path
    (root / "dubbed.mp4").write_bytes(b"fake mp4")
    (root / "job.json").write_text(json.dumps({
        "id": "real-job-id", "status": "done", "result": {
            "out_path": str(root / "dubbed.mp4"), "clipped_count": 1,
        },
    }))
    (root / "lines.json").write_text(json.dumps({"lines": [{
        "i": 0, "start": 0.0, "speaker": "S0", "text": "example",
    }]}))
    (root / "speakers.json").write_text(json.dumps([{
        "start": 0.0, "end": 1.0, "speaker": "S0",
    }]))
    (root / "speaker_refs.json").write_text(json.dumps({"S0": {
        "ref_wav": "qwen_ref_S0.wav",
        "ref_text": "hello I am speaking for a long time in this reference",
    }}))
    (root / "clipped_lines.json").write_text(json.dumps({
        "clipped": [{"line": 1, "cut_s": 0.4}],
    }))
    (root / "qwen_scorer_output.json").write_text(json.dumps({
        "ok": True, "lines": {
            "0": [{"sim": 0.31}, {"sim": 0.45}, {"sim": 0.38}, {"sim": 0.41}],
        },
    }))
    _wav(root / "qwen_ref_S0.wav", 0.9)
    _wav(root / "qwen_line_0.wav", 2.0)
    monkeypatch.setattr(quality, "_media_streams", lambda path: [
        {"codec_type": "video"}, {"codec_type": "audio"},
    ])
    return root


def test_detects_missing_original_and_weak_reference_and_bad_timing(job):
    report = quality.audit_completed(job, expected_mode="overdub")
    codes = {item["code"] for item in report["issues"]}
    assert codes == {
        "source_track_missing", "output_mode_mismatch",
        "speaker_reference_too_short", "speaker_reference_text_mismatch",
        "timing_slot_overruns", "speech_audio_clipped",
    }
    assert report["status"] == "review_required"
    assert report["actual_audio_streams"] == 1
    assert report["timing_overruns"][0]["line"] == 1
    assert report["timing_overruns"][0]["excess_seconds"] >= 0.9
    assert report["speaker_similarity_model_scores"]["0"] == 0.45
    assert "speaker likeness and naturalness" in report["human_review_remaining"]
    assert "example" not in json.dumps(report)


def test_two_streams_still_not_claimed_to_be_perceptually_verified(job, monkeypatch):
    metadata = json.loads((job / "job.json").read_text())
    metadata["result"]["audio_mode"] = "overdub"
    (job / "job.json").write_text(json.dumps(metadata))
    (job / "speaker_refs.json").write_text(json.dumps({"S0": {
        "ref_wav": "qwen_ref_S0.wav",
        "ref_text": "a good sample in context",
    }}))
    _wav(job / "qwen_ref_S0.wav", 5.0)
    _wav(job / "qwen_line_0.wav", 0.8)
    (job / "clipped_lines.json").write_text('{"clipped":[]}')
    monkeypatch.setattr(quality, "_media_streams", lambda path: [
        {"codec_type": "video"}, {"codec_type": "audio"}, {"codec_type": "audio"},
    ])
    result = quality.audit_completed(job, expected_mode="overdub")
    assert result["issues"] == []
    assert result["status"] == "not_perceptually_verified"
    assert len(result["human_review_remaining"]) == 4


def test_explicit_replace_mode_is_not_a_two_track_error(job):
    report = quality.audit_completed(job, expected_mode="replace")
    assert "source_track_missing" not in {
        item["code"] for item in report["issues"]
    }


def test_missing_finished_video_fails(job):
    (job / "dubbed.mp4").unlink()
    with pytest.raises(FileNotFoundError):
        quality.audit_completed(job, expected_mode="overdub")


def test_reference_cannot_leave_job_directory(job, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-ref.wav")
    _wav(outside, 5.0)
    (job / "speaker_refs.json").write_text(json.dumps({"S0": {
        "ref_wav": "../" + outside.name,
        "ref_text": "sample",
    }}))
    report = quality.audit_completed(job)
    assert any(r["code"] == "speaker_reference_missing" for r in report["issues"])
    outside.unlink()



def test_unfinished_job_cannot_be_treated_as_completed(job):
    manifest = json.loads((job / "job.json").read_text())
    manifest["status"] = "running"
    (job / "job.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="completed"):
        quality.audit_completed(job)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="Real media tools are required")
def test_real_ffprobe_exposes_overdub_original_names_and_default_stream(tmp_path):
    output = tmp_path / "two-track.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s=160x90:r=25:d=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-f", "lavfi", "-i", "sine=frequency=660:duration=1",
        "-map", "0:v:0", "-map", "1:a:0", "-map", "2:a:0",
        "-c:v", "mpeg4", "-c:a", "aac",
        "-metadata:s:a:0", "handler_name=Overdub",
        "-metadata:s:a:1", "handler_name=Original",
        "-disposition:a:0", "default", "-disposition:a:1", "0",
        str(output),
    ], check=True, capture_output=True)
    audio = [s for s in quality._media_streams(output)
             if s.get("codec_type") == "audio"]
    assert [s["tags"]["handler_name"] for s in audio] == ["Overdub", "Original"]
    assert [s["disposition"]["default"] for s in audio] == [1, 0]


def test_mismatched_source_cues_are_not_silently_used(job):
    (job / "speakers.json").write_text(json.dumps([{
        "start": 45.0, "end": 46.0, "speaker": "S0",
    }]))
    report = quality.audit_completed(job)
    assert report["timing_overruns"] == []
    assert any(item["code"] == "source_line_timing_unmatched" for item in report["issues"])


def test_finished_quality_reports_collapsed_source_whisper_timestamps(job):
    original = {
        "cues": [{
            "start": 145.64, "end": 146.72,
            "text": " ".join(f"word{i}" for i in range(18)),
            "words": [
                {"start": 146.72, "end": 146.72, "word": f"word{i}"}
                for i in range(16)
            ] + [
                {"start": 145.64, "end": 145.98, "word": "if"},
                {"start": 145.98, "end": 146.72, "word": "you"},
            ],
        }]
    }
    (job / "transcript.json").write_text(json.dumps(original))
    report = quality.audit_completed(job)
    timing = next(x for x in report["issues"]
                  if x["code"] == "source_transcript_timing_review")
    assert timing["count"] == 1
    assert timing["zero_duration_words"] == 16
    assert report["source_transcript_timing"]["word_timestamps_total"] == 18
    assert report["status"] == "review_required"
    assert "word15" not in json.dumps(report)


def test_finished_quality_does_not_invent_source_timing_pass(job):
    report = quality.audit_completed(job)
    assert report["source_transcript_timing"]["status"] == "not_measured"
    assert all(x["code"] != "source_transcript_timing_review"
               for x in report["issues"])
