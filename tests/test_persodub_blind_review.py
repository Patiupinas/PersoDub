"""Blinded, balanced A/B listening packs with a separate private mapping."""

import csv
import json
import math
import shutil
import struct
import wave

import pytest

from benchmarks.persodub.blind_review import prepare


def _wav(path, hz, seconds=0.12, sample_rate=16000):
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        data = [
            round(7000 * math.sin(i * math.pi * 2 * hz / sample_rate))
            for i in range(round(seconds * sample_rate))
        ]
        f.writeframes(b"".join(struct.pack("<h", n) for n in data))


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="Requires FFmpeg")
def test_blind_review_never_exposes_labels_and_balances_assignment(tmp_path):
    orig = tmp_path / "source.wav"
    v1 = tmp_path / "first.wav"
    v2 = tmp_path / "second.wav"
    _wav(orig, 330)
    _wav(v1, 440)
    _wav(v2, 660)
    manifest = tmp_path / "pairs.json"
    manifest.write_text(json.dumps({
        "schema_version": 1, "suite_id": "blind-wave-test",
        "pairs": [{
            "id": "case-%02d" % i,
            "source": orig.name, "baseline": v1.name, "candidate": v2.name,
            "target_text": "Проверка пауз",
        } for i in range(4)],
    }, ensure_ascii=False))
    pack = tmp_path / "review"
    key = tmp_path / "private_key.json"
    result = prepare(manifest, pack, key, seed=12345)
    assert result["pairs"] == 4
    assert key.is_file() and not (pack / key.name).exists()
    assert key.stat().st_mode & 0o077 == 0
    content = (pack / "ratings_template.csv").read_text()
    assert "baseline" not in content
    assert "candidate" not in content
    rows = list(csv.DictReader(content.splitlines()))
    assert len(rows) == 4
    assert all("Проверка пауз" in row["target_text"] for row in rows)
    for row in rows:
        folder = pack / row["pair_id"]
        for wav in ("A.wav", "B.wav", "source.wav"):
            with wave.open(str(folder / wav), "rb") as f:
                assert f.getframerate() == 48000
                assert f.getnchannels() == 2
                assert f.getsampwidth() == 2
    map_data = json.loads(key.read_text())
    assert sum(x["A"] == "candidate" for x in map_data["pairs"]) == 2
    assert sum(x["A"] == "baseline" for x in map_data["pairs"]) == 2
    with pytest.raises(FileExistsError):
        prepare(manifest, pack, tmp_path / "newkey.json", seed=99)


def test_blind_review_rejects_answer_key_in_pack(tmp_path):
    manifest = tmp_path / "cases.json"
    manifest.write_text('{"schema_version":1,"pairs":[{}]}')
    with pytest.raises(ValueError, match="outside"):
        prepare(manifest, tmp_path / "pack", tmp_path / "pack" / "key.json")
    assert not (tmp_path / "pack").exists()


def test_blind_review_rejects_identical_audio_and_bad_ids(tmp_path):
    a = tmp_path / "sample.wav"
    _wav(a, 440)
    manifest = tmp_path / "pairs.json"
    manifest.write_text(json.dumps({
        "schema_version": 1, "pairs": [{
            "id": "same", "baseline": "sample.wav", "candidate": "sample.wav",
        }],
    }))
    with pytest.raises(ValueError, match="itself"):
        prepare(manifest, tmp_path / "pack", tmp_path / "key.json")
    assert not (tmp_path / "pack").exists()
    manifest.write_text(json.dumps({
        "schema_version": 1, "pairs": [{
            "id": "../../escape", "baseline": "sample.wav", "candidate": "sample.wav",
        }],
    }))
    with pytest.raises(ValueError, match="IDs"):
        prepare(manifest, tmp_path / "pack", tmp_path / "key.json")


def test_blind_review_rejects_long_clips_before_copy(tmp_path):
    path = tmp_path / "long.wav"
    with wave.open(str(path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(8000)
        file.writeframes(b"\0" * (46 * 8000 * 2))
    short = tmp_path / "short.wav"
    _wav(short, 500)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "pairs": [{"id": "long", "baseline": short.name, "candidate": path.name}],
    }))
    with pytest.raises(ValueError, match="<=45s"):
        prepare(manifest, tmp_path / "out", tmp_path / "key.json")
    assert not (tmp_path / "out").exists()
