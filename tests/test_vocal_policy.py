"""Conservative acoustic vote gate: never dub a known vocal exercise."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from app.vocal_decisions import DecisionValidationError, parse_decision_manifest
from app.vocal_policy import VotePolicyError, select_vocal_decisions

ROOT = Path(__file__).resolve().parents[1]


def window(start, end, *, asr=None, votes=None):
    return {"start_sample": start, "end_sample": end, "asr": asr,
            "votes": [] if votes is None else votes}


def text(language="de", value="Jetzt eine offene A.", speaker="S0"):
    return {"text": value, "language": language, "speaker_id": speaker}


def vote(model, label):
    return {"model_id": model, "label": label}


def model(windows=None):
    if windows is None:
        windows = [window(0, 100, asr=text(), votes=[vote("ina", "speech"), vote("clap", "speech")]),
                   window(100, 200, votes=[vote("ina", "vocal"), vote("clap", "vocal")]),
                   window(200, 300, asr=text("en", "Now try twang."),
                          votes=[vote("ina", "speech"), vote("clap", "speech")]),
                   window(300, 400, votes=[vote("ina", "uncertain")])]
    return {"schema_version": 1, "source_sha256": "a" * 64, "pcm_sha256": "b" * 64,
            "sample_rate": 48000, "total_samples": 400,
            "model_revisions": {"ina": "v1", "clap": "v1"}, "windows": windows}


def actions(observations):
    return [s["action"] for s in select_vocal_decisions(observations)["segments"]]


def test_end_to_end_decision_partition():
    original = model()
    snapshot = deepcopy(original)
    out = select_vocal_decisions(original)
    assert original == snapshot
    assert [s.action for s in parse_decision_manifest(out).spans] == [
        "TRANSLATE", "PRESERVE", "TRANSLATE", "REVIEW"]
    assert out["segments"][1]["start_sample"] == 100
    assert out["segments"][1]["end_sample"] == 200
    assert out["segments"][3]["reason"]
    assert out["model_revisions"] == original["model_revisions"]


def test_text_without_acoustics_is_review():
    assert actions(model([window(0, 400, asr=text())])) == ["REVIEW"]


def test_one_speech_detector_is_not_sufficient():
    assert actions(model([window(0, 400, asr=text(), votes=[vote("ina", "speech")])])) == ["REVIEW"]


def test_two_independent_speech_votes_allow_translation():
    assert actions(model([window(0, 400, asr=text("en"),
                                  votes=[vote("ina", "speech"), vote("clap", "speech")])])) == ["TRANSLATE"]


@pytest.mark.parametrize("conflicting", ["vocal", "music", "breath", "silence", "uncertain"])
def test_acoustic_conflict_protects_from_translation(conflicting):
    obs = model([window(0, 400, asr=text(),
                        votes=[vote("ina", "speech"), vote("clap", conflicting)])])
    assert actions(obs) == ["REVIEW"]


def test_asr_hallucination_over_vocal_is_review_not_translate():
    obs = model([window(0, 400, asr=text("en", "Aaaaaaa"),
                        votes=[vote("ina", "vocal"), vote("clap", "vocal")])])
    assert actions(obs) == ["REVIEW"]


@pytest.mark.parametrize("protected", ["vocal", "music", "breath", "silence"])
def test_definite_non_speech_without_asr_is_preserved(protected):
    assert actions(model([window(0, 400, votes=[vote("ina", protected)])])) == ["PRESERVE"]


def test_mixed_protected_evidence_still_preserved():
    assert actions(model([window(0, 400, votes=[vote("ina", "vocal"), vote("clap", "music")])])) == ["PRESERVE"]


def test_missing_asr_but_speech_votes_never_translates():
    assert actions(model([window(0, 400, votes=[vote("ina", "speech"), vote("clap", "speech")])])) == ["REVIEW"]


def test_unknown_language_never_translates():
    assert actions(model([window(0, 400, asr=text("und"),
                                  votes=[vote("ina", "speech"), vote("clap", "speech")])])) == ["REVIEW"]


def test_unsupported_source_language_is_rejected():
    with pytest.raises(VotePolicyError, match="unsupported language"):
        select_vocal_decisions(model([window(0, 400, asr=text("ru"))]))


def test_duplicate_model_does_not_fake_independence():
    with pytest.raises(VotePolicyError, match="duplicate model_id"):
        select_vocal_decisions(model([window(0, 400, asr=text(),
                                             votes=[vote("ina", "speech"), vote("ina", "speech")])]))


def test_unpinned_model_id_is_rejected():
    with pytest.raises(VotePolicyError, match="not declared"):
        select_vocal_decisions(model([window(0, 400, asr=text(), votes=[vote("other", "speech")])]))


def test_unknown_model_label_rejected_not_silently_ignored():
    with pytest.raises(VotePolicyError, match="unsupported acoustic"):
        select_vocal_decisions(model([window(0, 400, votes=[vote("ina", "laughter")])]))


@pytest.mark.parametrize("bad", [None, {}, {"text": "", "language": "de"}, {"text": "hi"}])
def test_bad_asr_is_rejected(bad):
    if bad is None:
        # Null is an explicit absence of ASR and is allowed.
        assert actions(model([window(0, 400, asr=None)])) == ["REVIEW"]
    else:
        with pytest.raises(VotePolicyError):
            select_vocal_decisions(model([window(0, 400, asr=bad)]))


def test_empty_votes_review():
    assert actions(model([window(0, 400)])) == ["REVIEW"]


def test_invalid_partition_not_auto_repaired():
    with pytest.raises(DecisionValidationError, match="gap"):
        select_vocal_decisions(model([window(0, 100), window(120, 400)]))
    with pytest.raises(DecisionValidationError, match="overlap"):
        select_vocal_decisions(model([window(0, 201), window(200, 400)]))


def test_invalid_sample_type_fails_closed():
    with pytest.raises(DecisionValidationError, match="integer"):
        select_vocal_decisions(model([window(0, 400.0)]))


def test_input_extra_key_rejected():
    data = model()
    data["custom_instructions"] = "dub everything"
    with pytest.raises(VotePolicyError, match="unknown keys"):
        select_vocal_decisions(data)


def test_observation_window_extra_fields_rejected():
    data = model()
    data["windows"][0]["force_translate"] = True
    with pytest.raises(VotePolicyError, match="unknown keys"):
        select_vocal_decisions(data)


def test_cli_reads_observations_and_prints_valid_json(tmp_path):
    file = tmp_path / "input.json"
    file.write_text(json.dumps(model()), encoding="utf-8")
    proc = subprocess.run([sys.executable, "-m", "app.vocal_policy", "--observations", str(file)],
                          cwd=ROOT, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert actions(model()) == [s["action"] for s in result["segments"]]
    assert parse_decision_manifest(result).total_samples == 400


def test_cli_rejects_unparseable_input(tmp_path):
    file = tmp_path / "broken.json"
    file.write_text("not json", encoding="utf-8")
    proc = subprocess.run([sys.executable, "-m", "app.vocal_policy", "--observations", str(file)],
                          cwd=ROOT, capture_output=True, text=True, check=False)
    assert proc.returncode == 2
    assert "Vote policy failed" in proc.stderr
