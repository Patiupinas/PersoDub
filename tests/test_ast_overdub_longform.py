"""Long-form AST time-grid invariants without loading ML weights."""

import itertools
import math
import wave

import pytest

from app.scripts.ast_overdub_observer import (
    AST_RATE,
    SAMPLE_BYTES,
    STRIDE_SAMPLES,
    WINDOW_SAMPLES,
    _ffmpeg_pcm_chunks,
    _windows,
)


def _pcm(chunks, *, window_samples=WINDOW_SAMPLES, stride_samples=STRIDE_SAMPLES):
    return list(_windows(chunks, window_samples=window_samples, stride_samples=stride_samples))


@pytest.mark.parametrize("samples,expected", [
    (10, [0]),
    (WINDOW_SAMPLES, [0]),
    (WINDOW_SAMPLES + 1, [0, 1]),
    (WINDOW_SAMPLES + STRIDE_SAMPLES, [0, STRIDE_SAMPLES]),
    (WINDOW_SAMPLES + STRIDE_SAMPLES + 6000, [0, STRIDE_SAMPLES, STRIDE_SAMPLES + 6000]),
    (WINDOW_SAMPLES + 2 * STRIDE_SAMPLES, [0, STRIDE_SAMPLES, 2 * STRIDE_SAMPLES]),
])
def test_streaming_window_grid_matches_original_seek_based_grid(samples, expected):
    data = b"\x11\x00" * samples
    pieces = (data[i:i + 8192] for i in range(0, len(data), 8192))
    windows = _pcm(pieces)
    assert [start for start, _ in windows] == expected
    assert all(0 < len(pcm) <= 2 * WINDOW_SAMPLES for _, pcm in windows)
    assert windows[-1][0] + len(windows[-1][1]) // SAMPLE_BYTES == samples


def test_streaming_window_grid_handles_more_than_thirty_minutes_without_whole_audio_buffer():
    # All chunks reuse one bytes object; long PCM never accumulates in RAM.
    sample_bytes = b"\x00\x00" * STRIDE_SAMPLES
    count = math.ceil(31 * 60 * AST_RATE / STRIDE_SAMPLES)
    observed = 0
    last = 0
    for start, pcm in _windows(itertools.repeat(sample_bytes, count)):
        observed += 1
        last = start
        assert len(pcm) == WINDOW_SAMPLES * SAMPLE_BYTES
    assert observed > 900
    assert last == 31 * 60 * AST_RATE - WINDOW_SAMPLES


def test_streaming_ast_rejects_incorrect_pcm_word_alignment():
    with pytest.raises(ValueError, match="Misaligned"):
        _pcm([b"\x01"])


def test_streaming_ast_rejects_empty_and_invalid_clock():
    with pytest.raises(ValueError, match="no audio"):
        _pcm([])
    with pytest.raises(ValueError, match="stride"):
        _pcm([b"\x00\x00"], stride_samples=0)


def test_ffmpeg_ast_decoder_consumes_source_without_intermediate_wav(tmp_path):
    original = tmp_path / "sample.wav"
    with wave.open(str(original), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(48000)
        f.writeframesraw(b"\x00" * (48000 * 4 * 2))
    chunks = list(_ffmpeg_pcm_chunks(original))
    assert sum(len(chunk) for chunk in chunks) == 16000 * 2 * 2
    assert not (tmp_path / "mono.wav").exists()
