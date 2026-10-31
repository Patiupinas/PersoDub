"""Real metadata, real model responses; no media inference or human gold promotion."""

import copy
import json
from pathlib import Path

import pytest

from app.vocal_audio_tag_benchmark import AudioTagBenchmarkError, score_audio_tag_pilot

DATA = (
    Path(__file__).resolve().parents[1]
    / "docs/vocal-auto-events-benchmark-20261031"
)


def load():
    sources = json.loads((DATA / "selected-source-manifest.json").read_text(encoding="utf-8"))
    observed = json.loads((DATA / "model-observations.json").read_text(encoding="utf-8"))
    return sources, observed


def evaluate():
    return score_audio_tag_pilot(*load())


def test_actual_selected_source_labels_and_three_models():
    result = evaluate()
    assert result["status"] == "research_clip_level_scores_and_unreviewed_timeline"
    assert result["event_group_scores"]["AST"]["correct"] == 22
    assert result["event_group_scores"]["AST"]["total"] == 24
    assert result["event_group_scores"]["SenseVoice"]["correct"] == 14
    assert result["event_group_scores"]["SenseVoice"]["total"] == 24
    assert result["acted_speech_emotion"]["correct"] == 7
    assert result["acted_speech_emotion"]["eligible"] == 12
    assert result["unreviewed_navy_windows"] == 29
    assert result["human_segment_level_accuracy"] is None
    assert result["vocal_technique_accuracy"] is None
    assert result["no_automatic_dubbing_actions"] is True
    assert "TRANSLATE" not in json.dumps(result)


def test_real_per_corpus_results_are_not_aggregated_into_training_accuracy():
    result = evaluate()
    assert result["event_group_scores"]["AST"]["correct_by_dataset"] == {
        "ESC-50": {"correct": 8, "total": 10},
        "NUS-48E": {"correct": 4, "total": 4},
        "RAVDESS-speech": {"correct": 6, "total": 6},
        "VocalSet-subset": {"correct": 4, "total": 4},
    }
    assert result["event_group_scores"]["SenseVoice"]["correct_by_dataset"] == {
        "ESC-50": {"correct": 4, "total": 10},
        "NUS-48E": {"correct": 4, "total": 4},
        "RAVDESS-speech": {"correct": 6, "total": 6},
        "VocalSet-subset": {"correct": 0, "total": 4},
    }
    assert result["acted_speech_emotion"]["by_emotion"] == {
        "angry": {"correct": 3, "total": 3},
        "happy": {"correct": 1, "total": 3},
        "neutral": {"correct": 1, "total": 3},
        "sad": {"correct": 2, "total": 3},
    }
    assert len(result["acted_speech_emotion"]["out_of_ontology_excluded"]) == 2


def test_frozen_pilot_uses_true_separate_publisher_references_and_no_local_paths():
    sources, evidence = load()
    assert len(sources["clips"]) == 32
    assert len({entry["id"] for entry in sources["clips"]}) == 32
    assert sources["esc50_original_csv_sha256"]
    assert len([x for x in sources["clips"] if x["dataset"] == "ESC-50"]) == 10
    assert len([x for x in sources["clips"] if x["dataset"] == "NUS-48E"]) == 4
    assert len([x for x in sources["clips"] if x["dataset"] == "VocalSet-subset"]) == 4
    assert len([x for x in sources["clips"] if x["dataset"] == "RAVDESS-speech"]) == 14
    for sample in sources["clips"]:
        assert sample["url"].startswith("https://")
        assert sample["wav_sha256"] and len(sample["wav_sha256"]) == 64
        assert "local_path" not in sample and "transcript" not in sample
    assert len(evidence["ast_predictions"]) == 24
    assert len(evidence["sensevoice_predictions"]) == 24
    assert len(evidence["emotion_predictions"]) == 14


def test_matched_nus_read_and_sing_are_not_same_local_file_or_hash():
    sources, _ = load()
    nus = [r for r in sources["clips"] if r["dataset"] == "NUS-48E"]
    for speaker in ("ADIZ", "SAMF"):
        pairs = [r for r in nus if r["speaker"] == speaker]
        assert {r["dataset_label"] for r in pairs} == {"read", "sing"}
        assert len({r["wav_sha256"] for r in pairs}) == 2
        assert all("annotation_sha256" in r for r in pairs)


def test_emotion_and_sound_type_are_independent_axes():
    _, data = load()
    examples = {r["source_id"]: r for r in data["emotion_predictions"]}
    assert examples["RAVDESS-speech::audios/03-01-06-01-01-01-05.wav"]["emotion_supported"] is False
    assert examples["RAVDESS-speech::audios/03-01-08-01-01-01-06.wav"]["emotion_supported"] is False
    assert all("emotion_probabilities" not in r for r in data["ast_predictions"])
    assert all("source_text" not in r for r in data["sensevoice_predictions"])
    assert all("action" not in row for key in (
        "ast_predictions", "sensevoice_predictions", "emotion_predictions"
    ) for row in data[key])


def test_source_manifest_sha_exactly_matches_numeric_model_evidence():
    result = evaluate()
    assert result["source_manifest_canonical_sha256"] == (
        "a218024bed90c5714c335ed5f7602889daff7206e6e3855dbd0cb22919888019"
    )


@pytest.mark.parametrize("field,value", [
    ("schema_version", 2),
    ("artifact_kind", "human_gold"),
    ("no_automatic_dubbing_actions", False),
    ("source_manifest_canonical_sha256", "0" * 64),
])
def test_observation_root_contract_rejected(field, value):
    sources, evidence = load()
    evidence[field] = value
    with pytest.raises(AudioTagBenchmarkError):
        score_audio_tag_pilot(sources, evidence)


def test_source_sha_substitution_rejected():
    sources, evidence = load()
    evidence["ast_predictions"][0]["wav_sha256"] = "f" * 64
    with pytest.raises(AudioTagBenchmarkError, match="source content identity"):
        score_audio_tag_pilot(sources, evidence)


def test_duplicate_source_id_in_selected_prediction_rejected():
    sources, evidence = load()
    evidence["ast_predictions"][1]["source_id"] = evidence["ast_predictions"][0]["source_id"]
    with pytest.raises(AudioTagBenchmarkError):
        score_audio_tag_pilot(sources, evidence)


def test_same_clip_crop_must_be_identical_between_models():
    sources, evidence = load()
    evidence["sensevoice_predictions"][0]["crop_end_seconds"] -= 0.5
    with pytest.raises(AudioTagBenchmarkError, match="input crop differs"):
        score_audio_tag_pilot(sources, evidence)


@pytest.mark.parametrize("field,value", [
    ("category_scores", {"speech": 1}),
    ("category_ranking", ["speech"]),
    ("inference_seconds", float("nan")),
    ("action", "TRANSLATE"),
])
def test_bad_audio_event_model_evidence_rejected(field, value):
    sources, evidence = load()
    evidence["ast_predictions"][0][field] = value
    with pytest.raises(AudioTagBenchmarkError):
        score_audio_tag_pilot(sources, evidence)


def test_sensevoice_event_tag_cannot_be_relabelled_without_consistent_mapping():
    sources, evidence = load()
    evidence["sensevoice_predictions"][0]["recognized_groups"] = ["laughing"]
    with pytest.raises(AudioTagBenchmarkError, match="conversion inconsistent"):
        score_audio_tag_pilot(sources, evidence)


@pytest.mark.parametrize("bad", [
    {"emotion_supported": True},
    {"ground_truth_emotion": "angry"},
    {"predicted_emotion": "fearful"},
    {"emotion_probabilities": {"neutral": 1.0}},
    {"emotion_probabilities": {"neutral": 0.3, "happy": 0.3, "angry": 0.3, "sad": 0.3}},
])
def test_emotion_ontology_and_metadata_are_not_fabricated(bad):
    sources, evidence = load()
    row = next(r for r in evidence["emotion_predictions"]
               if r["ground_truth_emotion"] == "fearful")
    row.update(bad)
    with pytest.raises(AudioTagBenchmarkError):
        score_audio_tag_pilot(sources, evidence)


def test_original_source_label_cannot_be_silently_changed():
    sources, evidence = load()
    sources["clips"][0]["dataset_label"] = "speech"
    with pytest.raises(AudioTagBenchmarkError):
        score_audio_tag_pilot(sources, evidence)


def test_source_collision_cannot_be_silently_accepted():
    sources, evidence = load()
    sources["clips"][1] = copy.deepcopy(sources["clips"][0])
    with pytest.raises(AudioTagBenchmarkError):
        score_audio_tag_pilot(sources, evidence)


def test_timeline_cannot_claim_gold_or_shift_source_frame():
    sources, evidence = load()
    evidence["unreviewed_navy_timeline"]["windows"][0]["start_sample"] += 160
    with pytest.raises(AudioTagBenchmarkError, match="timestamp"):
        score_audio_tag_pilot(sources, evidence)
    _, evidence = load()
    evidence["unreviewed_navy_timeline"]["status"] = "independently_reviewed_gold"
    with pytest.raises(AudioTagBenchmarkError):
        score_audio_tag_pilot(sources, evidence)


def test_timeline_class_ranks_must_match_actual_model_logits():
    sources, evidence = load()
    evidence["unreviewed_navy_timeline"]["windows"][9]["top_categories"][0] = "sneezing"
    with pytest.raises(AudioTagBenchmarkError, match="time series scores"):
        score_audio_tag_pilot(sources, evidence)


def test_original_and_addendum_emotion_selection_stay_disjoint():
    sources, evidence = load()
    rated={r["source_id"] for r in evidence["emotion_predictions"]}
    ast={r["source_id"] for r in evidence["ast_predictions"]}
    extra={r["id"] for r in sources["clips"] if r.get("actor") in ("07","08")}
    assert len(rated)==14
    assert len(extra)==8
    assert extra <= rated
    assert not extra & ast


def test_report_cli_writes_only_explicit_destination(tmp_path):
    from app.vocal_audio_tag_benchmark import main
    out=tmp_path/"score.json"
    assert main([
        "--sources",str(DATA/"selected-source-manifest.json"),
        "--observations",str(DATA/"model-observations.json"),
        "--out",str(out),
    ]) == 0
    result=json.loads(out.read_text(encoding="utf-8"))
    assert result["event_group_scores"]["AST"]["correct"] == 22
    assert all("source_text" not in item for misses in result["event_group_misses"].values()
               for item in misses)
    with pytest.raises(SystemExit):
        main([
            "--sources",str(DATA/"selected-source-manifest.json"),
            "--observations",str(DATA/"model-observations.json"),
            "--out",str(out),
        ])
