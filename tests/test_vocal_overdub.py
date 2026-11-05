"""Synthetic, source-hashed WAV tests for sample-exact dual-language overdub."""

import hashlib
import json
import math
import struct
import wave

import pytest

from app.audio.overdub import (
    CHUNK_FRAMES,
    OverdubError,
    OverdubLevels,
    render_overdub,
)


def wav(path, seconds=3, amplitude=8000, rate=48000, channels=2):
    frames = int(seconds * rate)
    row = struct.pack("<%dh" % channels, *([amplitude] * channels))
    with wave.open(str(path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        for start in range(0, frames, 4800):
            out.writeframesraw(row * min(4800, frames - start))
    return path


def make_plan(tmp_path, source, events):
    with wave.open(str(source), "rb") as handle:
        frames = handle.getnframes()
    data = {
        "schema_version": 1,
        "sample_rate": 48000,
        "total_frames": frames,
        "source_wav_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "events": events,
    }
    dest = tmp_path / "plan.json"
    dest.write_text(json.dumps(data), encoding="utf-8")
    return dest


def sample(path, sec, channel=0):
    with wave.open(str(path), "rb") as handle:
        handle.setpos(int(round(sec * handle.getframerate())))
        data = handle.readframes(1)
    return struct.unpack("<hh", data)[channel]


def default_events(rate=48000):
    return [
        {"start_frame": 0, "end_frame": rate, "action": "TRANSLATE"},
        {"start_frame": rate, "end_frame": 2 * rate, "action": "PRESERVE"},
        {"start_frame": 2 * rate, "end_frame": 3 * rate, "action": "REVIEW"},
    ]


def test_speech_original_is_audible_but_lower_than_overdub_voice(tmp_path):
    src = wav(tmp_path / "source.wav", amplitude=8000)
    dub = wav(tmp_path / "voice.wav", amplitude=16000)
    plan = make_plan(tmp_path, src, default_events())
    output = tmp_path / "mixed.wav"
    receipt = render_overdub(src, dub, plan, output, levels=OverdubLevels())
    want = round(8000 * 10 ** (-16 / 20) + 16000 * 10 ** (-16 / 20))
    assert abs(sample(output, 0.5) - want) <= 1
    assert sample(output, 1.5) == 8000
    assert sample(output, 2.5) == 8000
    assert receipt["action_frames"] == {
        "TRANSLATE": 48000, "PRESERVE": 48000, "REVIEW": 48000
    }
    assert receipt["overdub_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    with wave.open(str(output), "rb") as f:
        assert f.getnframes() == 3 * 48000
        assert f.getframerate() == 48000
        assert f.getnchannels() == 2


def test_cosine_fade_is_smooth_and_fully_inside_translate_span(tmp_path):
    src = wav(tmp_path / "source.wav", amplitude=8000)
    dub = wav(tmp_path / "voice.wav", amplitude=16000)
    plan = make_plan(tmp_path, src, default_events())
    output = tmp_path / "mixed.wav"
    render_overdub(src, dub, plan, output, levels=OverdubLevels(fade_ms=400))
    settled_speech = sample(output, 0.5)
    settled_preserve = sample(output, 1.5)
    assert settled_speech < settled_preserve
    at_early = sample(output, 0.70)
    at_mid = sample(output, 0.83)
    at_late = sample(output, 0.98)
    assert settled_speech < at_early < at_mid < at_late <= settled_preserve
    assert abs(sample(output, 0.99998) - sample(output, 1.0)) <= 2
    assert sample(output, 0.60) == settled_speech
    assert sample(output, 1.00) == settled_preserve
    assert sample(output, 1.01) == settled_preserve


def test_review_does_not_invent_automatic_translation(tmp_path):
    src = wav(tmp_path / "source.wav", amplitude=6000)
    dub = wav(tmp_path / "voice.wav", amplitude=25000)
    events = [{"start_frame": 0, "end_frame": 3 * 48000, "action": "REVIEW"}]
    plan = make_plan(tmp_path, src, events)
    mixed = tmp_path / "mixed.wav"
    render_overdub(src, dub, plan, mixed)
    assert mixed.read_bytes() == src.read_bytes()


def test_shorter_dub_is_zero_padded_on_same_source_clock(tmp_path):
    src = wav(tmp_path / "source.wav", seconds=3, amplitude=5000)
    dub = wav(tmp_path / "voice.wav", seconds=1, amplitude=18000)
    plan = make_plan(
        tmp_path, src,
        [{"start_frame": 0, "end_frame": 3 * 48000, "action": "TRANSLATE"}],
    )
    mixed = tmp_path / "mixed.wav"
    render_overdub(src, dub, plan, mixed)
    expected = round((5000 + 18000) * 10 ** (-16 / 20))
    assert abs(sample(mixed, 0.4) - expected) <= 1
    assert sample(mixed, 1.4) == 5000
    assert sample(mixed, 1.4) == sample(src, 1.4)


def test_plan_action_must_cover_complete_source_without_overlap(tmp_path):
    src = wav(tmp_path / "source.wav")
    dub = wav(tmp_path / "voice.wav")
    for changes in (
        [{"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"}],
        [{"start_frame": 1, "end_frame": 144000, "action": "TRANSLATE"}],
        [
            {"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"},
            {"start_frame": 47000, "end_frame": 144000, "action": "PRESERVE"},
        ],
        [{"start_frame": 0, "end_frame": 144000, "action": "EXPLANATION"}],
        [{"start_frame": 0, "end_frame": 144000, "action": "TRANSLATE", "speech": True}],
        [{"start_frame": False, "end_frame": 144000, "action": "TRANSLATE"}],
    ):
        plan = make_plan(tmp_path, src, changes)
        with pytest.raises(OverdubError):
            render_overdub(src, dub, plan, tmp_path / "bad.wav")
        assert not (tmp_path / "bad.wav").exists()


def test_plan_identity_cannot_be_stale_or_cross_the_wrong_video(tmp_path):
    src = wav(tmp_path / "source.wav")
    dub = wav(tmp_path / "voice.wav")
    plan = make_plan(tmp_path, src, default_events())
    for key, bad in (
        ("source_wav_sha256", "f" * 64),
        ("sample_rate", 16000),
        ("total_frames", 144001),
        ("schema_version", 2),
    ):
        data = json.loads(plan.read_text())
        data[key] = bad
        plan.write_text(json.dumps(data))
        with pytest.raises(OverdubError):
            render_overdub(src, dub, plan, tmp_path / "bad.wav")
    assert not (tmp_path / "bad.wav").exists()


def test_profiles_with_invalid_headroom_or_nonfinite_values_rejected():
    for settings in (
        (0.0, 0.0, 300.0), (10.0, -12.0, 300.0),
        (-16.0, -2.0, float("nan")),
        (-16.0, -2.0, -1.0),
        (-16.0, -2.0, 3000.0),
        (True, -2.0, 300.0),
        (-16.0, float("inf"), 300.0),
    ):
        with pytest.raises(OverdubError):
            OverdubLevels(*settings)


def test_incompatible_wavs_and_longer_dub_rejected(tmp_path):
    src = wav(tmp_path / "source.wav")
    dub = wav(tmp_path / "voice.wav", rate=44100)
    plan = make_plan(tmp_path, src, default_events())
    with pytest.raises(OverdubError):
        render_overdub(src, dub, plan, tmp_path / "mixed.wav")
    dub = wav(tmp_path / "voice.wav", seconds=4)
    with pytest.raises(OverdubError, match="outlast"):
        render_overdub(src, dub, plan, tmp_path / "mixed.wav")
    assert not (tmp_path / "mixed.wav").exists()


def test_output_overwrite_and_source_alias_refused(tmp_path):
    src = wav(tmp_path / "source.wav")
    dub = wav(tmp_path / "voice.wav")
    plan = make_plan(tmp_path, src, default_events())
    with pytest.raises(OverdubError):
        render_overdub(src, dub, plan, src)
    output = wav(tmp_path / "already.wav")
    with pytest.raises(OverdubError):
        render_overdub(src, dub, plan, output)


def test_pcm_chunk_boundary_does_not_create_click_or_clock_drift(tmp_path):
    src = wav(tmp_path / "source.wav", seconds=2)
    dub = wav(tmp_path / "voice.wav", seconds=2)
    events = [
        {"start_frame": 0, "end_frame": CHUNK_FRAMES * 2 + 200, "action": "TRANSLATE"},
        {"start_frame": CHUNK_FRAMES * 2 + 200, "end_frame": 96000, "action": "PRESERVE"},
    ]
    plan = make_plan(tmp_path, src, events)
    output = tmp_path / "mixed.wav"
    render_overdub(src, dub, plan, output)
    assert abs(sample(output, (CHUNK_FRAMES * 2 - 1) / 48000)
               - sample(output, (CHUNK_FRAMES * 2) / 48000)) <= 2
    with wave.open(str(output), "rb") as f:
        assert f.getnframes() == 96000


def test_preserve_is_bit_identical_to_original_outside_fades(tmp_path):
    src = wav(tmp_path / "source.wav", seconds=3, amplitude=-32768)
    dub = wav(tmp_path / "voice.wav", seconds=3, amplitude=32767)
    plan = make_plan(tmp_path, src, default_events())
    out = tmp_path / "mixed.wav"
    render_overdub(src, dub, plan, out)
    for second in (1.5, 2.5):
        assert sample(out, second) == -32768


def test_silent_dub_does_not_bypass_verified_manifest(tmp_path):
    src = wav(tmp_path / "source.wav")
    dub = wav(tmp_path / "voice.wav", seconds=0)
    plan = make_plan(tmp_path, src, default_events())
    out = tmp_path / "mixed.wav"
    receipt = render_overdub(src, dub, plan, out)
    assert receipt["frames"] == 144000
    assert sample(out, 0.5) == sample(src, 0.5)


def test_gain_profile_math_is_bounded_by_unity():
    values = OverdubLevels(-16.0, -2.0, 300.0)
    assert sum(values.translate_gains) < 1.0
    assert not math.isclose(values.translate_gains[0], values.translate_gains[1])


def test_short_dub_tail_is_trimmed_without_changing_source_clock(tmp_path):
    src = wav(tmp_path / "source.wav", seconds=2, amplitude=4000)
    dub = wav(tmp_path / "voice.wav", seconds=2.02, amplitude=12000)
    plan = make_plan(tmp_path, src, [{
        "start_frame": 0, "end_frame": 96000, "action": "TRANSLATE",
    }])
    out = tmp_path / "mixed.wav"
    result = render_overdub(src, dub, plan, out)
    assert result["dub_tail_trimmed_frames"] == 960
    with wave.open(str(out), "rb") as handle:
        assert handle.getnframes() == 96000


@pytest.mark.parametrize("protected_action", ["PRESERVE", "REVIEW"])
def test_protected_intervals_are_byte_identical_up_to_both_boundaries(
    tmp_path, protected_action,
):
    source = wav(tmp_path / "source.wav", seconds=2.0, amplitude=-12000)
    translated = wav(tmp_path / "translated.wav", seconds=2.0, amplitude=25000)
    first, last = 24000, 36000
    plan = make_plan(tmp_path, source, [
        {"start_frame": 0, "end_frame": first, "action": "TRANSLATE"},
        {"start_frame": first, "end_frame": last, "action": protected_action},
        {"start_frame": last, "end_frame": 96000, "action": "TRANSLATE"},
    ])
    output = tmp_path / "mixed.wav"
    render_overdub(source, translated, plan, output, levels=OverdubLevels(fade_ms=300))
    with wave.open(str(source), "rb") as original, wave.open(str(output), "rb") as mixed:
        original.setpos(first)
        mixed.setpos(first)
        count = last - first
        assert mixed.readframes(count) == original.readframes(count)


def test_separator_51ms_silent_padding_preserves_exact_video_clock(tmp_path):
    """Real AAC/video clock mismatch: 2452 frames of harmless separator padding."""
    source = wav(tmp_path / "source.wav", seconds=2, amplitude=9000)
    voice = tmp_path / "voice.wav"
    tail_frames = 2452
    with wave.open(str(voice), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(48000)
        out.writeframes(struct.pack("<hh", 16000, 16000) * 96000)
        out.writeframes(b"\x00" * (tail_frames * 4))
    plan = make_plan(tmp_path, source, [
        {"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"},
        {"start_frame": 48000, "end_frame": 96000, "action": "PRESERVE"},
    ])
    result = render_overdub(source, voice, plan, tmp_path / "output.wav")
    assert result["dub_tail_trimmed_frames"] == tail_frames
    expected = round(9000 * 10 ** (-16 / 20) + 16000 * 10 ** (-16 / 20))
    assert abs(sample(tmp_path / "output.wav", 0.5) - expected) <= 1
    assert sample(tmp_path / "output.wav", 1.5) == 9000
    with wave.open(str(tmp_path / "output.wav")) as mixed:
        assert mixed.getnframes() == 96000


@pytest.mark.parametrize("tail_frames,tail_sample", [
    (2452, 9000), (12001, 0),
])
def test_separator_tail_rejects_non_silence_or_unbounded_padding(
    tmp_path, tail_frames, tail_sample,
):
    source = wav(tmp_path / "source.wav", seconds=1, amplitude=4000)
    voice = tmp_path / "voice.wav"
    with wave.open(str(voice), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(48000)
        out.writeframes(struct.pack("<hh", 8000, 8000) * 48000)
        out.writeframes(struct.pack("<hh", tail_sample, tail_sample) * tail_frames)
    plan = make_plan(tmp_path, source, [
        {"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"},
    ])
    with pytest.raises(OverdubError, match="outlast"):
        render_overdub(source, voice, plan, tmp_path / "output.wav")
    assert not (tmp_path / "output.wav").exists()


def test_original_voice_recovers_right_after_russian_voice_ends_inside_a_long_cue(tmp_path):
    """The first sung demonstration must not wait for the entire SRT window."""
    src = wav(tmp_path / "source.wav", seconds=4.0, amplitude=9500)
    dub = wav(tmp_path / "voice.wav", seconds=1.2, amplitude=16000)
    plan = make_plan(tmp_path, src, [
        {"start_frame": 0, "end_frame": 3 * 48000, "action": "TRANSLATE"},
        {"start_frame": 3 * 48000, "end_frame": 4 * 48000, "action": "PRESERVE"},
    ])
    mixed = tmp_path / "mixed.wav"
    render_overdub(src, dub, plan, mixed, levels=OverdubLevels(-16, -2, 300))
    assert sample(mixed, 0.5) > sample(src, 0.5)
    # Unlike a 300 ms cue-edge fade, original must be back within 150 ms
    # of the *actual* final voiced Russian sample.
    for at_second in (1.35, 1.5, 2.0, 2.7, 3.0, 3.5):
        assert sample(mixed, at_second) == sample(src, at_second)


def test_short_silent_gap_inside_russian_sentence_does_not_pump_original(tmp_path):
    src = wav(tmp_path / "source.wav", seconds=2.0, amplitude=8000)
    dub = tmp_path / "dub.wav"
    with wave.open(str(dub), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(struct.pack("<hh", 16000, 16000) * int(0.55 * 48000))
        w.writeframes(b"\x00" * int(0.09 * 48000 * 4))
        w.writeframes(struct.pack("<hh", 16000, 16000) * int(0.55 * 48000))
        w.writeframes(b"\x00" * int(0.81 * 48000 * 4))
    plan = make_plan(tmp_path, src, [
        {"start_frame": 0, "end_frame": 2 * 48000, "action": "TRANSLATE"},
    ])
    mixed = tmp_path / "mixed.wav"
    render_overdub(src, dub, plan, mixed)
    assert sample(mixed, 0.59) == round(8000 * 10 ** (-16 / 20))
    assert sample(mixed, 0.60) == round(8000 * 10 ** (-16 / 20))
    assert sample(mixed, 1.40) == sample(src, 1.40)


def test_full_original_is_audible_inside_translate_if_russian_track_is_silent(tmp_path):
    src = wav(tmp_path / "source.wav", seconds=2.0, amplitude=9000)
    dub = wav(tmp_path / "dub.wav", seconds=2.0, amplitude=0)
    plan = make_plan(tmp_path, src, [
        {"start_frame": 0, "end_frame": 2 * 48000, "action": "TRANSLATE"},
    ])
    output = tmp_path / "mixed.wav"
    render_overdub(src, dub, plan, output)
    assert output.read_bytes() == src.read_bytes()


def test_a4_protected_original_stays_bit_exact_with_voice_activity_release(tmp_path):
    src = wav(tmp_path / "source.wav", seconds=3.0, amplitude=-12000)
    dub = wav(tmp_path / "voice.wav", seconds=3.0, amplitude=28000)
    plan = make_plan(tmp_path, src, [
        {"start_frame": 0, "end_frame": 48000, "action": "TRANSLATE"},
        {"start_frame": 48000, "end_frame": 96000, "action": "PRESERVE"},
        {"start_frame": 96000, "end_frame": 144000, "action": "TRANSLATE"},
    ])
    out = tmp_path / "mixed.wav"
    render_overdub(src, dub, plan, out)
    with wave.open(str(src), "rb") as original, wave.open(str(out), "rb") as mixed:
        original.setpos(48000)
        mixed.setpos(48000)
        assert original.readframes(48000) == mixed.readframes(48000)
