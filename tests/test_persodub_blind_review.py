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

def test_offline_listening_html_escapes_source_text_and_has_no_private_key(tmp_path):
    import re
    import subprocess

    from benchmarks.persodub.review_page import RATING_COLUMNS, make_page

    html = make_page([
        ("case_a", True, 'Проверка пауз <script>alert("unexpected")</script>'),
        ("case_b", False, 'Другая фраза & "цитата"'),
    ])
    assert html.count('class="pair"') == 2
    assert "case_a/source.wav" in html
    assert "case_b/source.wav" not in html
    assert "case_a/A.wav" in html and "case_b/B.wav" in html
    assert "&lt;script&gt;" in html
    assert "<script>alert" not in html
    assert "Другая фраза &amp; &quot;цитата&quot;" in html
    assert "private" not in html
    assert "baseline" not in html and "candidate" not in html
    assert "fetch(" not in html and "http://" not in html and "https://" not in html
    assert "preload=\"none\"" in html
    assert 'name="A_accent_1to5"' in html
    assert 'name="B_voice_1to5"' in html
    assert 'name="preference_A_B_tie"' in html
    assert "ratings" in html
    assert "columns=" + json.dumps(RATING_COLUMNS) in html
    match = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    assert match is not None
    if shutil.which("node"):
        script = tmp_path / "review.js"
        script.write_text(match.group(1), encoding="utf-8")
        subprocess.run(["node", "--check", str(script)], check=True,
                       capture_output=True, timeout=10)


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="Requires FFmpeg")
def test_blind_pack_includes_offline_review_page_without_answer_mapping(tmp_path):
    from benchmarks.persodub.review_page import RATING_COLUMNS

    wav_a, wav_b = tmp_path / "one.wav", tmp_path / "two.wav"
    _wav(wav_a, 330)
    _wav(wav_b, 440)
    manifest = tmp_path / "pairs.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "pairs": [{
            "id": "russian1",
            "baseline": wav_a.name,
            "candidate": wav_b.name,
            "target_text": "Пение и дыхание",
        }],
    }, ensure_ascii=False))
    pack = tmp_path / "pack"
    key = tmp_path / "private_key.json"
    prepare(manifest, pack, key, seed=2)
    text = (pack / "index.html").read_text(encoding="utf-8")
    assert "russian1/A.wav" in text and "russian1/B.wav" in text
    assert "Пение и дыхание" in text
    assert "A_audio" not in text
    assert "russian1/source.wav" not in text
    assert "baseline" not in text and "candidate" not in text
    assert "A_accent_1to5" in text and "B_accent_1to5" in text
    assert len(list(csv.DictReader((pack / "ratings_template.csv").open()))) == 1
    assert list(csv.reader((pack / "ratings_template.csv").open()))[0] == RATING_COLUMNS
    assert key.parent == tmp_path
    assert (pack / "private_key.json").exists() is False


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                    reason="Requires FFmpeg")
def test_voice_only_profile_omits_unanswerable_original_bed_rating(tmp_path):
    from benchmarks.persodub.review_page import make_page

    voice = make_page([("voice1", True, "Проверка произношения")], voice_only=True)
    assert 'name="A_accent_1to5"' in voice
    assert 'name="B_voice_1to5"' in voice
    assert 'name="A_pauses_1to5"' in voice
    assert 'name="A_original_audibility_1to5"' not in voice
    assert "const voiceOnly=true;" in voice
    assert "values.A_original_audibility_1to5='N/A';" in voice
    assert "слышимость оригинала N/A" in voice

    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    _wav(a, 280)
    _wav(b, 330)
    manifest = tmp_path / "voice.json"
    manifest.write_text(json.dumps({
        "schema_version": 1, "rating_profile": "voice",
        "pairs": [{"id": "v01", "baseline": a.name, "candidate": b.name,
                   "target_text": "Слово"}],
    }, ensure_ascii=False))
    out = tmp_path / "review"
    prepare(manifest, out, tmp_path / "secret.json", seed=1)
    rows = list(csv.DictReader((out / "ratings_template.csv").open()))
    assert rows[0]["A_original_audibility_1to5"] == "N/A"
    assert rows[0]["B_original_audibility_1to5"] == "N/A"
    assert 'name="A_original_audibility_1to5"' not in (out / "index.html").read_text()
    bad_manifest = tmp_path / "invalid.json"
    bad_manifest.write_text(json.dumps({"schema_version": 1,
        "rating_profile": "speaker-magic",
        "pairs": [{"id": "v02", "baseline": a.name, "candidate": b.name}]}))
    with pytest.raises(ValueError, match="rating_profile"):
        prepare(bad_manifest, tmp_path / "newout", tmp_path / "other-secret.json")
