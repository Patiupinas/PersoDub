"""Exercise observation policy -> PCM assembler -> gold safety benchmark together.

All audio consists of deterministic synthetic tones. No model or lecture data.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.vocal_benchmark import score_vocal_decisions
from app.vocal_decisions import parse_decision_manifest
from app.vocal_offline_demo import RATE, create_demo
from app.vocal_pcm import PCMAssemblyError, assemble_vocal_wav, verify_preserved_wav
from app.vocal_policy import select_vocal_decisions


ROOT = Path(__file__).resolve().parents[1]


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _vote(model, label):
    return {"model_id": model, "label": label}


def _observation(gold):
    def part(start, end, language, words, first, second):
        return {
            "start_sample": start, "end_sample": end,
            "asr": None if language is None else {"language": language, "text": words},
            "votes": [_vote("ina", first), _vote("clap", second)],
        }

    return {
        "schema_version": 1,
        "source_sha256": gold["source_sha256"],
        "pcm_sha256": gold["pcm_sha256"],
        "sample_rate": gold["sample_rate"],
        "total_samples": gold["total_samples"],
        "model_revisions": {"ina": "synthetic-r1", "clap": "synthetic-r1"},
        "windows": [
            part(0, RATE, "de", "Jetzt ein A.", "speech", "speech"),
            part(RATE, 2 * RATE, None, None, "vocal", "vocal"),
            part(2 * RATE, 3 * RATE, "en", "Sing this.", "speech", "speech"),
            part(3 * RATE, 4 * RATE, None, None, "uncertain", "music"),
        ],
    }


def _tts(folder):
    return {
        "window-000000": folder / "speech-de.synthetic.wav",
        "window-000002": folder / "speech-en.synthetic.wav",
    }


def _run(folder, observations, *, output="vocal-pipeline.wav"):
    manifest = select_vocal_decisions(observations)
    rendered = folder / output
    assemble_vocal_wav(folder / "original.synthetic.wav", rendered, manifest, _tts(folder))
    return manifest, rendered


def test_policy_assembler_and_benchmark_agree_on_same_sample_timeline(tmp_path):
    folder = tmp_path / "demo"
    create_demo(folder)
    gold = _read(folder / "gold.synthetic.json")
    policy = _observation(gold)
    manifest, output = _run(folder, policy)
    assert [s.action for s in parse_decision_manifest(manifest).spans] == [
        "TRANSLATE", "PRESERVE", "TRANSLATE", "REVIEW"]
    assert output.read_bytes() == (folder / "dubbed.synthetic.wav").read_bytes()
    score = score_vocal_decisions(gold, manifest)
    assert score["vocal_preservation"]["wrongly_translated_samples"] == 0
    assert score["ambiguous_safety"]["wrongly_translated_samples"] == 0
    assert score["speech_utility"]["recall"] == 1.0
    assert verify_preserved_wav(folder / "original.synthetic.wav", output, gold) == 2 * RATE


def test_asr_hallucination_on_vocal_changes_preserve_to_review_not_translate(tmp_path):
    folder = tmp_path / "demo"
    create_demo(folder)
    gold = _read(folder / "gold.synthetic.json")
    obs = _observation(gold)
    obs["windows"][1]["asr"] = {"language": "de", "text": "Aaaa"}
    manifest, output = _run(folder, obs)
    assert manifest["segments"][1]["action"] == "REVIEW"
    assert score_vocal_decisions(gold, manifest)["vocal_preservation"]["wrongly_translated_samples"] == 0
    assert verify_preserved_wav(folder / "original.synthetic.wav", output, gold) == 2 * RATE


def test_disagreement_sacrifices_speech_coverage_but_not_vocal_safety(tmp_path):
    folder = tmp_path / "demo"
    create_demo(folder)
    gold = _read(folder / "gold.synthetic.json")
    obs = _observation(gold)
    obs["windows"][2]["votes"][1]["label"] = "vocal"
    manifest = select_vocal_decisions(obs)
    assert manifest["segments"][2]["action"] == "REVIEW"
    score = score_vocal_decisions(gold, manifest)
    assert score["speech_utility"]["recall"] == 0.5
    assert score["vocal_preservation"]["wrongly_translated_samples"] == 0
    assert score["predicted_review"]["samples"] == 2 * RATE


def test_unanimous_wrong_models_are_detected_by_independent_gold(tmp_path):
    folder = tmp_path / "demo"
    create_demo(folder)
    gold = _read(folder / "gold.synthetic.json")
    obs = _observation(gold)
    obs["windows"][1]["asr"] = {"language": "en", "text": "Singing A"}
    obs["windows"][1]["votes"] = [_vote("ina", "speech"), _vote("clap", "speech")]
    decision = select_vocal_decisions(obs)
    assert decision["segments"][1]["action"] == "TRANSLATE"
    score = score_vocal_decisions(gold, decision)
    assert score["vocal_preservation"]["wrongly_translated_samples"] == RATE
    assert score["vocal_preservation"]["affected_gold_segments"] == 1
    assert score["vocal_preservation"]["zero_corrupted_vocal_segments"] is False


def test_one_frame_boundary_error_fails_gold_pcm_integrity(tmp_path):
    folder = tmp_path / "demo"
    create_demo(folder)
    gold = _read(folder / "gold.synthetic.json")
    obs = _observation(gold)
    obs["windows"][1]["end_sample"] = 2 * RATE - 1
    obs["windows"][2]["start_sample"] = 2 * RATE - 1
    decisions, output = _run(folder, obs)
    report = score_vocal_decisions(gold, decisions)
    assert report["vocal_preservation"]["wrongly_translated_samples"] == 1
    assert report["vocal_preservation"]["affected_gold_segments"] == 1
    with pytest.raises(PCMAssemblyError, match="protected PCM was modified"):
        verify_preserved_wav(folder / "original.synthetic.wav", output, gold)


def test_gap_in_acoustic_window_prevents_assembly(tmp_path):
    folder = tmp_path / "demo"
    create_demo(folder)
    gold = _read(folder / "gold.synthetic.json")
    obs = _observation(gold)
    obs["windows"][1]["start_sample"] += 1
    with pytest.raises(ValueError, match="gap"):
        select_vocal_decisions(obs)
    assert not (folder / "not-published.wav").exists()


def test_cli_manifest_can_feed_pcm_cli_and_score_cli(tmp_path):
    folder = tmp_path / "demo"
    create_demo(folder)
    gold = _read(folder / "gold.synthetic.json")
    source = folder / "source-observations.json"
    source.write_text(json.dumps(_observation(gold)), encoding="utf-8")
    commands = [
        [sys.executable, "-m", "app.vocal_policy", "--observations", str(source)],
        [sys.executable, "-m", "app.vocal_pcm", "--source", str(folder / "original.synthetic.wav"),
         "--decisions", str(folder / "policy-output.json"),
         "--tts", f"window-000000={folder / 'speech-de.synthetic.wav'}",
         "--tts", f"window-000002={folder / 'speech-en.synthetic.wav'}",
         "--output", str(folder / "command-dub.wav")],
        [sys.executable, "-m", "app.vocal_benchmark", "--gold", str(folder / "gold.synthetic.json"),
         "--pred", str(folder / "policy-output.json"), "--fail-on-unsafe"],
    ]
    first = subprocess.run(commands[0], cwd=ROOT, text=True, capture_output=True, check=False)
    assert first.returncode == 0, first.stderr
    (folder / "policy-output.json").write_text(first.stdout, encoding="utf-8")
    assert parse_decision_manifest(json.loads(first.stdout)).total_samples == 4 * RATE
    for command in commands[1:]:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
    assert (folder / "command-dub.wav").is_file()

