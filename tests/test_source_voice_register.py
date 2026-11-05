"""Source-register voice routing must use evidence, not diarizer ordinal labels."""
import json
import subprocess

import pytest

from app.engines.silero_ru import SileroRuEngine
from app.source_voice_register import (
    OVERRIDES,
    RECEIPT,
    _bounded_samples,
    resolve_source_voice_registers,
)


def _cue(speaker, start, end, **values):
    return {"speaker_id": speaker, "start": start, "end": end, **values}


def test_explicit_source_cue_uses_male_preset_without_running_any_worker(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Explicit source register should not probe acoustics")
    monkeypatch.setattr(subprocess, "run", unexpected)
    source = [_cue("VOICE_01", 0.35, 8.9, source_voice_register="male")]
    assigned = resolve_source_voice_registers(
        "unused.wav", source, source, ["VOICE_01"], str(tmp_path), lambda _: None,
    )
    assert assigned == {"VOICE_01": "male"}
    report = json.loads((tmp_path / RECEIPT).read_text())
    assert report["speakers"]["VOICE_01"]["method"] == "source_cue_label"


def test_reviewed_voice_register_override_wins_over_acoustic_or_source_label(tmp_path):
    (tmp_path / OVERRIDES).write_text(json.dumps({
        "version": 1, "speaker_to_register": {"VOICE_01": "male"}
    }))
    source = [_cue("VOICE_01", 0.35, 8.9, source_voice_register="female")]
    actual = resolve_source_voice_registers(
        "unused.wav", source, source, ["VOICE_01"], str(tmp_path), lambda _: None,
    )
    assert actual == {"VOICE_01": "male"}
    report = json.loads((tmp_path / RECEIPT).read_text())
    assert report["speakers"]["VOICE_01"]["method"] == "reviewed_override"


def test_rejects_conflicting_source_voice_labels(tmp_path):
    cues = [_cue("VOICE_01", 0, 4, source_voice_register="male"),
            _cue("VOICE_01", 5, 9, source_voice_register="female")]
    with pytest.raises(ValueError, match="Conflicting"):
        resolve_source_voice_registers("unused", cues, cues, ["VOICE_01"], tmp_path, lambda _: None)


def test_override_must_name_real_source_group(tmp_path):
    (tmp_path / OVERRIDES).write_text(json.dumps({
        "version": 1, "speaker_to_register": {"VOICE_99": "male"}
    }))
    cues = [_cue("VOICE_01", 0, 4)]
    with pytest.raises(ValueError, match="Invalid"):
        resolve_source_voice_registers("unused", cues, cues, ["VOICE_01"], tmp_path, lambda _: None)


def test_only_reviewed_speech_windows_are_used_for_acoustic_probe():
    cues = [_cue("VOICE_01", 0.35, 8.9),
            _cue("VOICE_01", 17.76, 25.64),
            _cue("VOICE_01", 49.12, 55.5)]
    selected = [{"start": 0.35, "end": 8.9}, {"start": 49.12, "end": 55.5}]
    assert _bounded_samples(cues, selected, ["VOICE_01"]) == {
        "VOICE_01": [
            {"start": 0.5, "end": 6.0},
            {"start": 49.27, "end": 54.77},
        ],
    }


def test_acoustic_probe_routes_low_register_to_male_and_records_evidence(monkeypatch, tmp_path):
    seen = []

    def fake_probe(args, text, capture_output, timeout):
        request = json.loads(open(args[args.index("--input") + 1], encoding="utf-8").read())
        seen.append((request, timeout))
        with open(args[args.index("--output") + 1], "w", encoding="utf-8") as output:
            json.dump({"version": 1, "speakers": {"VOICE_01": {
                "register": "male", "speech_pitch_p25_hz": 115.0,
                "evidence": [{"start": 0.5, "end": 6.0}],
            }}}, output)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_probe)
    cues = [_cue("VOICE_01", 0.35, 8.9)]
    got = resolve_source_voice_registers(
        "vocals.wav", cues, cues, ["VOICE_01"], tmp_path, lambda _: None,
    )
    assert got == {"VOICE_01": "male"}
    assert seen[0][0]["vocals_wav_path"] == "vocals.wav"
    report = json.loads((tmp_path / RECEIPT).read_text())
    assert report["speakers"]["VOICE_01"]["speech_pitch_p25_hz"] == 115.0


def test_ambiguous_pitch_requires_review_instead_of_assigning_female(monkeypatch, tmp_path):
    def fake_probe(args, **kwargs):
        output_path = args[args.index("--output") + 1]
        with open(output_path, "w", encoding="utf-8") as output:
            json.dump({"version": 1, "speakers": {"VOICE_01": {
                "register": "review", "speech_pitch_p25_hz": 159.1, "evidence": [],
            }}}, output)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_probe)
    cue = _cue("VOICE_01", 0.35, 8.9)
    with pytest.raises(ValueError, match="could not be distinguished"):
        resolve_source_voice_registers(
            "vocals.wav", [cue], [cue], ["VOICE_01"], tmp_path, lambda _: None,
        )
    report = json.loads((tmp_path / RECEIPT).read_text())
    assert report["speakers"]["VOICE_01"]["register"] == "review"


def test_no_speech_sample_does_not_guess_any_voice(tmp_path):
    cues = [_cue("VOICE_01", 18.0, 25.0)]
    selected = [{"start": 0.35, "end": 8.9}]
    with pytest.raises(ValueError, match="No approved source speech"):
        resolve_source_voice_registers(
            "vocals.wav", cues, selected, ["VOICE_01"], tmp_path, lambda _: None,
        )


def test_silero_assigns_male_and_female_by_source_not_voice_index(tmp_path):
    engine = SileroRuEngine(base_url="http://localhost:3000")
    speakers = ["VOICE_01", "VOICE_02", "VOICE_03", "VOICE_04"]
    mapping = engine.assign_voices({}, speakers, tmp_path, lambda _: None,
                                   source_registers={"VOICE_01": "female",
                                                     "VOICE_02": "male",
                                                     "VOICE_03": "male",
                                                     "VOICE_04": "female"})
    assert mapping == {
        "VOICE_01": "kseniya", "VOICE_02": "aidar",
        "VOICE_03": "eugene", "VOICE_04": "xenia",
    }
    report = json.loads((tmp_path / "russian_voice_assignments.json").read_text())
    assert report["source_registers"]["VOICE_01"] == "female"


def test_silero_rejects_source_voice_count_exceeding_one_register_bank(tmp_path):
    engine = SileroRuEngine(base_url="http://localhost:3000")
    with pytest.raises(ValueError, match="Insufficient"):
        engine.assign_voices({}, ["A", "B", "C"], tmp_path, lambda _: None,
                             source_registers={"A": "male", "B": "male", "C": "male"})


def test_default_new_overdub_mix_is_six_db_quieter():
    from app.audio.overdub import OverdubLevels

    profile = OverdubLevels()
    assert profile.speech_original_db == -16.0
    assert profile.speech_dub_db == -16.0
    assert profile.translate_gains[1] <= 0.16


def test_regenerated_voxcpm_overdub_checks_selected_external_engine_not_qwen(monkeypatch):
    import app.api.dub as dub_api
    import app.api.overdub as api
    from app.engines.voxcpm2_ru import VoxCPM2RuEngine

    calls = []
    monkeypatch.setattr(api.launch_api, "missing_models",
                        lambda *args, **kwargs: (calls.append(kwargs) or []))
    monkeypatch.setattr(dub_api, "_require_voice_engine_running",
                        lambda: pytest.fail("Do not require the unrelated Qwen/Silero sidecar"))
    monkeypatch.setattr(VoxCPM2RuEngine, "is_available", lambda self: True)
    api._require_selected_voice_engine(1, "voxcpm2_ru")
    assert calls[0]["need_tts"] is False
    assert calls[0]["need_silero_ru"] is False

    monkeypatch.setattr(VoxCPM2RuEngine, "is_available", lambda self: False)
    with pytest.raises(api.HTTPException) as error:
        api._require_selected_voice_engine(1, "voxcpm2_ru")
    assert error.value.status_code == 422


def test_low_voice_register_source_is_not_tied_to_speaker_order(tmp_path):
    from app.engines.voxcpm2_ru import VoxCPM2RuEngine

    engine = VoxCPM2RuEngine(base_url="http://127.0.0.1:3909")
    with pytest.raises(ValueError, match="requires verified"):
        engine.assign_voices({}, ["VOICE_01"], str(tmp_path), lambda _: None)
