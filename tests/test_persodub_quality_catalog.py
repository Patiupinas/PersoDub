"""Keep the external quality benchmark catalog scoped to real oracle types."""
import json
from pathlib import Path


def test_quality_catalog_does_not_confuse_dataset_truth_with_model_proxies():
    path = Path(__file__).resolve().parents[1] / "benchmarks/persodub/stage_catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    assert catalog["schema_version"] == 1
    policy = catalog["policy"]
    assert policy["automatic_downloads"] is False
    assert policy["publish_audio_in_git"] is False
    assert policy["holdout_never_for_threshold_tuning"] is True
    assert policy["github_actions"] is False

    stages = {row["id"]: row for row in catalog["stages"]}
    assert len(stages) == len(catalog["stages"])
    assert {"asr", "translation", "vocal_events", "tts", "blind_listening"} <= stages.keys()

    datasets = {item["id"]: item for item in catalog["datasets"]}
    assert len(datasets) == len(catalog["datasets"])
    for dataset_id in ("FLEURS", "FLORES+", "CV3-Eval", "GTSinger",
                       "VocalSound", "MuST-C", "RAVDESS"):
        assert dataset_id in datasets
        item = datasets[dataset_id]
        assert item["url"].startswith("https://")
        assert item["oracles"]
        assert item["not_suitable_for"]
        assert item["data_license"]

    assert any("EN->RU" in value for value in datasets["CoVoST2"]["not_suitable_for"])
    assert "gated" in datasets["FLORES+"]["data_license"].lower() or (
        "terms acceptance" in datasets["FLORES+"]["data_license"].lower()
    )
    assert "native-Russian accent PASS" in datasets["CV3-Eval"]["not_suitable_for"][0]
    assert "NOT_RUN" in stages["blind_listening"]["automation"]
    assert "FLEURS" in stages["asr"]["dataset"]
    assert "A4" not in datasets["VocalSound"]["suitable_for"]
