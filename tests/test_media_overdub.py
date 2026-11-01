"""Two-track video exports with original audio and dynamic overdub."""

import hashlib
import json
import shutil
import struct
import subprocess
import wave

import pytest

from app import media
from app.audio.overdub import render_overdub


def _tone(path, frames, amplitude, sample_rate=48000):
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        word = struct.pack("<hh", amplitude, amplitude)
        for first in range(0, frames, 4800):
            output.writeframesraw(word * min(4800, frames - first))


def _probe(path):
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True, check=True, text=True,
    )
    return json.loads(proc.stdout)["streams"]


def _audio_packet_hashes(path, audio_index):
    process = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", f"a:{audio_index}",
        "-show_packets", "-show_data_hash", "sha256",
        "-show_entries", "packet=data_hash", "-of", "csv=p=0", str(path),
    ], capture_output=True, check=True, text=True)
    return [line.split(",", 1)[0] for line in process.stdout.splitlines()]


def test_mux_overdub_explicitly_maps_and_names_both_audio_streams(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(media.subprocess, "run", fake_run)
    monkeypatch.setattr(media, "stream_duration", lambda path, stream: 8.2)
    r = media.mux_overdub("input.mp4", "mixed.wav", "output.mp4", 8.246)
    assert r.returncode == 0
    args = calls[0]
    streams = [args[i + 1] for i, value in enumerate(args[:-1]) if value == "-map"]
    assert streams == ["0:v:0", "1:a:0", "0:a:0"]
    assert args[args.index("-c:v") + 1] == "copy"
    assert args[args.index("-c:a:1") + 1] == "copy"
    assert args[args.index("-disposition:a:0") + 1] == "default"
    assert args[args.index("-disposition:a:1") + 1] == "0"
    assert args[args.index("-filter:a:0") + 1] == "apad"
    assert "-filter:a:1" not in args
    assert "handler_name=Overdub" in args
    assert "handler_name=Original" in args
    assert float(args[args.index("-t") + 1]) == 8.246


def test_length_repair_keeps_two_audio_tracks(monkeypatch, tmp_path):
    args = []
    original = str(tmp_path / "original.mp4")
    mixed = str(tmp_path / "finished.mp4")
    with open(mixed, "wb") as handle:
        handle.write(b"synthetic output")

    def fake_run(command, **kwargs):
        args.append(command)
        (tmp_path / "finished.mp4.fix.mp4").write_bytes(b"fixed")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(media.subprocess, "run", fake_run)
    monkeypatch.setattr(media, "stream_duration", lambda path, stream: 2.8)
    monkeypatch.setattr(
        media, "video_duration",
        lambda path: 3.0 if path == original else 2.5,
    )
    media.ensure_video_length(original, mixed, lambda msg: None, preserve_overdub_tracks=True)
    refs = [args[0][i + 1] for i, item in enumerate(args[0][:-1]) if item == "-map"]
    assert refs == ["0:v:0", "1:a:0", "1:a:1"]
    assert args[0][args[0].index("-c:a:1") + 1] == "copy"
    assert "-filter:a:1" not in args[0]
    assert (tmp_path / "finished.mp4").read_bytes() == b"fixed"


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="ffmpeg/ffprobe unavailable")
def test_real_mp4_retains_original_and_selectable_overdub(tmp_path):
    source_video = tmp_path / "input.mp4"
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s=160x90:r=25:d=3",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac",
        "-t", "3", str(source_video),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    original_pcm = tmp_path / "original48.wav"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(source_video),
        "-map", "0:a:0", "-af", "aresample=async=1:first_pts=0",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
        str(original_pcm),
    ], check=True, capture_output=True)
    with wave.open(str(original_pcm), "rb") as handle:
        nframes = handle.getnframes()
        assert handle.getframerate() == 48000
    voice_only = tmp_path / "dub48.wav"
    _tone(voice_only, nframes, amplitude=12000)
    plan = {
        "schema_version": 1, "sample_rate": 48000, "total_frames": nframes,
        "source_wav_sha256": hashlib.sha256(original_pcm.read_bytes()).hexdigest(),
        "events": [
            {"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"},
            {"start_frame": 48000, "end_frame": 96000, "action": "PRESERVE"},
            {"start_frame": 96000, "end_frame": nframes, "action": "REVIEW"},
        ],
    }
    manifest = tmp_path / "plan.json"
    manifest.write_text(json.dumps(plan))
    mixed = tmp_path / "overdub.wav"
    render_overdub(original_pcm, voice_only, manifest, mixed)
    output = tmp_path / "multitrack.mp4"
    r = media.mux_overdub(str(source_video), str(mixed), str(output), 3.0)
    assert r.returncode == 0, r.stderr
    streams = _probe(output)
    assert len([s for s in streams if s["codec_type"] == "video"]) == 1
    audio = [s for s in streams if s["codec_type"] == "audio"]
    assert len(audio) == 2
    assert audio[0]["disposition"]["default"] == 1
    assert audio[1]["disposition"]["default"] == 0
    assert audio[0]["tags"]["handler_name"] == "Overdub"
    assert audio[1]["tags"]["handler_name"] == "Original"
    assert all(abs(float(s["duration"]) - 3.0) < 0.055 for s in audio)
    # The secondary audio comes from the untouched source stream, not from
    # the dynamically attenuated primary WAV.
    assert original_pcm.read_bytes() != mixed.read_bytes()
    # The Original track must retain the exact compressed audio packets.
    original_packets = _audio_packet_hashes(source_video, 0)
    assert original_packets
    assert _audio_packet_hashes(output, 1) == original_packets


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="ffmpeg unavailable")
def test_original_audio_tail_survives_video_track_ending_first(tmp_path):
    source_video = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s=160x90:r=25:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=2.4",
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "mpeg4", "-c:a", "aac",
        str(source_video),
    ], check=True, capture_output=True)
    original_duration = media.video_duration(str(source_video))
    assert original_duration < media.stream_duration(str(source_video), "a:0")
    overdub = tmp_path / "overdub.wav"
    _tone(overdub, int(original_duration * 48000), amplitude=5000)
    output = tmp_path / "output.mp4"
    result = media.mux_overdub(str(source_video), str(overdub), str(output), original_duration)
    assert result.returncode == 0, result.stderr
    original_packets = _audio_packet_hashes(source_video, 0)
    assert original_packets
    assert _audio_packet_hashes(output, 1) == original_packets


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="ffmpeg unavailable")
def test_extract_original_pcm_pads_short_original_audio_to_video_duration(tmp_path):
    from app.audio.overdub import extract_original_pcm
    source = tmp_path / "short_audio.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", "color=c=black:s=160x90:r=25:d=3",
        "-f", "lavfi", "-i", "sine=frequency=500:sample_rate=48000:duration=2.2",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "mpeg4", "-c:a", "aac", "-t", "3", str(source),
    ], check=True, capture_output=True)
    output = tmp_path / "original_padded.wav"
    extract_original_pcm(source, output, duration=3.0)
    with wave.open(str(output), "rb") as handle:
        assert handle.getnframes() == 144000
        handle.setpos(int(2.9 * 48000))
        assert handle.readframes(100) == b"\x00" * 400
