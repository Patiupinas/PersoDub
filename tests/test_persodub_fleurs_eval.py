"""FLEURS evaluation uses immutable external test transcripts and local clips."""
import hashlib
import json
import math
import struct
import wave

import pytest

from benchmarks.persodub.fleurs_eval import run, select


def corpus(tmp_path, n=6):
    root = tmp_path / "corpus"
    clips = []
    root.mkdir()
    for i in range(n):
        path = root / f"example{i}.wav"
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            out.writeframes(struct.pack("<h", 100) * 16000)
        clips.append({
            "id": f"fleurs_ru_{i}", "wav": path.name,
            "rawText": f"Тестовая фраза номер {i}.",
            "text": f"тестовая фраза номер {i}",
            "durationSeconds": 1.0,
        })
    manifest = tmp_path / "fleurs.json"
    manifest.write_text(json.dumps({
        "language": "ru",
        "source": "google/fleurs ru_ru test (professional transcripts)",
        "clips": clips,
    }, ensure_ascii=False))
    return root, manifest, clips


def test_frozen_selection_is_order_independent_and_has_test_gold(tmp_path):
    root, manifest, clips = corpus(tmp_path)
    first = select(manifest, root, "ru", 3, seed="freeze-a")
    assert len(first["selected"]) == 3
    assert first["eligible_cases"] == 6
    assert len({r["id"] for r in first["selected"]}) == 3
    assert all("Тестовая" in r["text"] for r in first["selected"])
    ids = [r["id"] for r in first["selected"]]
    manifest.write_text(json.dumps({
        "language": "ru",
        "source": "google/fleurs ru_ru test (professional transcripts)",
        "clips": list(reversed(clips)),
    }, ensure_ascii=False))
    second = select(manifest, root, "ru", 3, seed="freeze-a")
    assert ids == [r["id"] for r in second["selected"]]
    assert first["manifest_sha256"] != second["manifest_sha256"]


def test_external_gold_scored_with_project_native_wer_cer(tmp_path):
    root, manifest, _ = corpus(tmp_path)
    frozen = select(manifest, root, "ru", 2)
    result = run(frozen, lambda file, lang:
                 "тестовая фраза номер " + file.stem.replace("example", ""))
    assert result["status"] == "OBSERVED"
    assert result["oracle"] == "original FLEURS test transcript, not model output"
    assert result["human_accent_validated"] is False
    assert result["summary"]["corpus_wer"] == 0.0
    assert result["summary"]["corpus_cer"] == 0.0
    assert all(len(row["source_sha256"]) == 64 for row in result["clips"])
    changed = run(frozen, lambda file, lang: "нет")
    assert changed["summary"]["corpus_wer"] > 0.0
    assert changed["summary"]["corpus_cer"] > 0.0


@pytest.mark.parametrize("mutate,match", [
    (lambda d: d.update(source="model prediction"), "source/language"),
    (lambda d: d.update(language="de"), "source/language"),
    (lambda d: d["clips"][0].update(rawText=""), "independent transcript"),
    (lambda d: d["clips"][0].update(durationSeconds=math.nan), "duration mismatch"),
    (lambda d: d["clips"][1].update(id=d["clips"][0]["id"]), "Duplicate dataset"),
    (lambda d: d["clips"][1].update(wav=d["clips"][0]["wav"]), "Duplicate dataset source"),
    (lambda d: d["clips"][1].update(wav="../fleurs.json"), "within local corpus"),
])
def test_rejects_mismatched_provenance_or_data(tmp_path, mutate, match):
    root, manifest, _ = corpus(tmp_path)
    raw = json.loads(manifest.read_text())
    mutate(raw)
    manifest.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match=match):
        select(manifest, root, "ru", 3)


def test_bad_selection_count_and_language_rejected(tmp_path):
    root, manifest, _ = corpus(tmp_path)
    with pytest.raises(ValueError, match="supported language"):
        select(manifest, root, "ru", 0)
    with pytest.raises(ValueError, match="supported language"):
        select(manifest, root, "ru", 31)
    with pytest.raises(ValueError, match="supported language"):
        select(manifest, root, "fr", 3)
    with pytest.raises(ValueError, match="Insufficient"):
        select(manifest, root, "ru", 10)


def test_decoder_must_return_text_without_mutating_reference(tmp_path):
    root, manifest, _ = corpus(tmp_path)
    selection = select(manifest, root, "ru", 2)
    before = hashlib.sha256(manifest.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="text string"):
        run(selection, lambda *_: None)
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == before


def test_source_metadata_cannot_escape_using_a_symlink(tmp_path):
    root, manifest, raw = corpus(tmp_path)
    outside = tmp_path / "not-corpus.wav"
    outside.write_bytes((root / "example0.wav").read_bytes())
    link = root / "link.wav"
    link.symlink_to(outside)
    raw[0]["wav"] = link.name
    obj = json.loads(manifest.read_text())
    obj["clips"] = raw
    manifest.write_text(json.dumps(obj))
    with pytest.raises(ValueError, match="source WAV path"):
        select(manifest, root, "ru", 3)
