"""Fail-closed tests for exact PCM sample alignment without any audio models."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from app.vocal_align import ObservationAlignmentError, align_observations
from app.vocal_policy import select_vocal_decisions

ROOT = Path(__file__).resolve().parents[1]


def acoustic(*parts):
    """Tuples of start/end/label become an explicit fully covering track."""
    return [{"start_sample": a, "end_sample": b, "label": label} for a, b, label in parts]


def transcript(start=10, end=90, text="Jetzt singen wir", language="de", speaker="S0"):
    return {"start_sample": start, "end_sample": end, "text": text,
            "language": language, "speaker_id": speaker}


def source(*, length=100, asr=None, ina=None, clap=None):
    return {"schema_version": 1, "source_sha256": "a" * 64,
            "pcm_sha256": "b" * 64, "sample_rate": 48000,
            "total_samples": length, "model_revisions": {"ina": "ina@sha", "clap": "clap@sha"},
            "asr_segments": [transcript()] if asr is None else asr,
            "acoustic_tracks": {
                "ina": acoustic((0, length, "speech")) if ina is None else ina,
                "clap": acoustic((0, length, "speech")) if clap is None else clap,
            }}


def result(raw):
    observations = align_observations(raw)
    manifest = select_vocal_decisions(observations)
    return observations, manifest["segments"]


def test_no_mutation_and_preserve_one_asr_phrase():
    raw = source()
    original = deepcopy(raw)
    obs, segments = result(raw)
    assert raw == original
    assert [(s["start_sample"], s["end_sample"], s["action"]) for s in segments] == [
        (0, 10, "REVIEW"), (10, 90, "TRANSLATE"), (90, 100, "REVIEW")]
    assert segments[1]["source_text"] == "Jetzt singen wir"
    assert sum(win["end_sample"] - win["start_sample"] for win in obs["windows"]) == 100


def test_acoustic_internal_split_same_label_does_not_repeat_text():
    ina = acoustic((0, 20, "speech"), (20, 80, "speech"), (80, 100, "speech"))
    obs, segments = result(source(ina=ina))
    assert [w["asr"] is not None for w in obs["windows"]] == [False, True, False]
    assert [s["action"] for s in segments] == ["REVIEW", "TRANSLATE", "REVIEW"]
    assert [s.get("source_text") for s in segments].count("Jetzt singen wir") == 1


def test_one_sample_vocal_attack_blocks_entire_phrase():
    raw = source(asr=[transcript(0, 100)],
                 ina=acoustic((0, 49, "speech"), (49, 50, "vocal"), (50, 100, "speech")))
    obs, segments = result(raw)
    assert len(obs["windows"]) == 1
    assert [v["label"] for v in obs["windows"][0]["votes"]] == ["speech", "uncertain"]
    assert segments[0]["action"] == "REVIEW"
    assert segments[0]["start_sample"] == 0 and segments[0]["end_sample"] == 100


def test_acoustic_conflict_throughout_phrase_forces_review():
    obs, segments = result(source(ina=acoustic((0, 100, "vocal"))))
    assert obs["windows"][1]["asr"]["text"] == "Jetzt singen wir"
    assert segments[1]["action"] == "REVIEW"


def test_interphrase_gaps_partition_acoustic_boundaries_without_asr():
    raw = source(asr=[transcript(0, 40)],
                 ina=acoustic((0, 40, "speech"), (40, 70, "vocal"), (70, 100, "breath")),
                 clap=acoustic((0, 40, "speech"), (40, 70, "music"), (70, 100, "silence")))
    obs, segments = result(raw)
    assert [(s["start_sample"], s["end_sample"], s["action"]) for s in segments] == [
        (0, 40, "TRANSLATE"), (40, 70, "PRESERVE"), (70, 100, "PRESERVE")]
    assert obs["windows"][1]["asr"] is None


def test_acoustic_change_inside_asr_does_not_duplicate_translation():
    raw = source(asr=[transcript(10, 90)],
                 ina=acoustic((0, 20, "speech"), (20, 60, "vocal"), (60, 100, "speech")))
    _, segments = result(raw)
    assert all(s["action"] != "TRANSLATE" for s in segments)
    assert sum(bool(s.get("source_text")) for s in segments) == 1


def test_no_asr_but_speech_acoustics_are_review_not_translate():
    _, segments = result(source(asr=[]))
    assert len(segments) == 1 and segments[0]["action"] == "REVIEW"


def test_no_asr_all_vocal_acoustics_preserves():
    raw = source(asr=[], ina=acoustic((0, 100, "vocal")),
                 clap=acoustic((0, 100, "vocal")))
    _, segments = result(raw)
    assert [s["action"] for s in segments] == ["PRESERVE"]


def test_no_detectors_is_always_review():
    raw = source()
    raw["model_revisions"] = {}
    raw["acoustic_tracks"] = {}
    _, segments = result(raw)
    assert [s["action"] for s in segments] == ["REVIEW", "REVIEW", "REVIEW"]


def test_one_detector_does_not_fake_two_votes():
    raw = source()
    raw["model_revisions"].pop("clap")
    raw["acoustic_tracks"].pop("clap")
    _, segments = result(raw)
    assert all(s["action"] != "TRANSLATE" for s in segments)


def test_unknown_asr_language_protects_audio():
    _, segments = result(source(asr=[transcript(language="und")]))
    assert all(s["action"] == "REVIEW" for s in segments)


def test_two_asr_phrases_keep_identity_across_acoustic_change_in_gap():
    raw = source(asr=[transcript(0, 40, "Singen", "de"),
                      transcript(70, 100, "Sing", "en")],
                 ina=acoustic((0, 45, "speech"), (45, 65, "vocal"), (65, 100, "speech")),
                 clap=acoustic((0, 45, "speech"), (45, 65, "vocal"), (65, 100, "speech")))
    _, segments = result(raw)
    assert [s["action"] for s in segments] == ["TRANSLATE", "REVIEW", "PRESERVE", "REVIEW", "TRANSLATE"]
    assert [s.get("source_text") for s in segments if s.get("source_text")] == ["Singen", "Sing"]


@pytest.mark.parametrize("bad", [
    [transcript(0, 60), transcript(50, 100)],
    [transcript(70, 100), transcript(0, 60)],
])
def test_overlapping_or_unsorted_asr_rejected(bad):
    with pytest.raises(ObservationAlignmentError, match="overlapping or unsorted"):
        align_observations(source(asr=bad))


@pytest.mark.parametrize("segments,reason", [
    (acoustic((0, 50, "speech"), (51, 100, "speech")), "uncovered"),
    (acoustic((0, 60, "speech"), (59, 100, "speech")), "overlapping"),
    (acoustic((0, 101, "speech")), "out-of-range"),
    (acoustic((0, 0, "speech"), (0, 100, "speech")), "empty"),
    (acoustic((False, 100, "speech")), "integer"),
    (acoustic((0, 100, "angry")), "unknown acoustic"),
    ([], "empty acoustic"),
])
def test_invalid_acoustic_tracks_rejected(segments, reason):
    with pytest.raises(ObservationAlignmentError, match=reason):
        align_observations(source(ina=segments))


def test_mismatched_model_registry_is_rejected():
    raw = source()
    raw["model_revisions"].pop("clap")
    with pytest.raises(ObservationAlignmentError, match="match declared"):
        align_observations(raw)


def test_unknown_top_level_field_rejected():
    raw = source()
    raw["auto_translate_everything"] = True
    with pytest.raises(ObservationAlignmentError, match="unknown"):
        align_observations(raw)


def test_unknown_asr_field_rejected():
    raw = source()
    raw["asr_segments"][0]["skip_vocals"] = False
    with pytest.raises(ObservationAlignmentError, match="unknown"):
        align_observations(raw)


def test_out_of_range_asr_rejected():
    with pytest.raises(ObservationAlignmentError, match="out-of-range"):
        align_observations(source(asr=[transcript(0, 101)]))


def test_invalid_manifest_hash_rejected():
    raw = source()
    raw["pcm_sha256"] = "not-a-hash"
    with pytest.raises(ValueError, match="SHA-256"):
        align_observations(raw)


def test_large_offsets_are_integers_without_float_rounding():
    total = 2**53 + 100
    raw = source(length=total, asr=[transcript(total - 5, total)],
                 ina=acoustic((0, total, "speech")), clap=acoustic((0, total, "speech")))
    obs, segments = result(raw)
    assert [s["start_sample"] for s in segments] == [0, total - 5]
    assert [s["end_sample"] for s in segments] == [total - 5, total]


def test_cli_emits_json_and_handles_invalid_data(tmp_path):
    inp = tmp_path / "input.json"
    inp.write_text(json.dumps(source()), encoding="utf-8")
    cmd = [sys.executable, "-m", "app.vocal_align", "--source", str(inp)]
    okay = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    assert okay.returncode == 0, okay.stderr
    assert [s["action"] for s in select_vocal_decisions(json.loads(okay.stdout))["segments"]] == [
        "REVIEW", "TRANSLATE", "REVIEW"]
    inp.write_text('{not json', encoding="utf-8")
    failed = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    assert failed.returncode == 2 and "alignment failed" in failed.stderr
