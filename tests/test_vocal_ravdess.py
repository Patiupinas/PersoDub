"""Small synthetic ZIP tests; no licensed RAVDESS audio or downloads needed."""

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from app.vocal_ravdess import RavdessIndexError, index_ravdess


def _member(actor, channel, emotion=1, intensity=1, repetition=1):
    return f"Actor_{actor:02d}/03-{channel:02d}-{emotion:02d}-{intensity:02d}-01-{repetition:02d}-{actor:02d}.wav"


def _archives(tmp_path, speech_names=None, song_names=None):
    speech_names = speech_names or [_member(a, 1) for a in (1, 17, 21)]
    song_names = song_names or [_member(a, 2) for a in (1, 17, 21)]
    paths, md5 = {}, {}
    for kind, names in (("speech", speech_names), ("song", song_names)):
        path = tmp_path / f"{kind}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for i, name in enumerate(names):
                archive.writestr(name, f"WAV synthetic bytes {i}".encode())
        paths[kind] = path
        md5[kind] = hashlib.md5(path.read_bytes()).hexdigest()
    return paths, md5


def _run(paths, digests, counts=None):
    return index_ravdess(paths["speech"], paths["song"], expected_md5=digests,
                         expected_counts={"speech": 3, "song": 3} if counts is None else counts)


def test_reproducible_split_and_whole_file_labels(tmp_path):
    paths, digests = _archives(tmp_path)
    manifest = _run(paths, digests)
    assert manifest["license"] == "CC BY-NC-SA 4.0"
    assert manifest["label_granularity"].startswith("whole-file")
    assert manifest["splits"] == {"train": ["actor-01"], "dev": ["actor-17"], "test": ["actor-21"]}
    assert manifest["counts"] == {s: {"speech": 1, "song": 1} for s in ("train", "dev", "test")}
    assert len(manifest["records"]) == 6
    assert all(rec["member"].endswith(".wav") for rec in manifest["records"])
    assert all(rec["uncompressed_size_bytes"] > 0 for rec in manifest["records"])
    assert manifest == _run(paths, digests)


def test_published_checksum_mismatch_stops_before_index(tmp_path):
    paths, digests = _archives(tmp_path)
    wrong = dict(digests, song="0" * 32)
    with pytest.raises(RavdessIndexError, match="MD5 mismatch"):
        _run(paths, wrong)


def test_wrong_channel_inside_speech_archive_is_rejected(tmp_path):
    paths, digests = _archives(tmp_path, speech_names=[_member(1, 2)])
    with pytest.raises(RavdessIndexError, match="vocal channel"):
        _run(paths, digests, {"speech": 1, "song": 3})


def test_actor_folder_cannot_disagree_with_filename(tmp_path):
    item = _member(1, 1).replace("Actor_01", "Actor_02")
    paths, digests = _archives(tmp_path, speech_names=[item])
    with pytest.raises(RavdessIndexError, match="actor ID mismatch"):
        _run(paths, digests, {"speech": 1, "song": 3})


def test_rejects_traversal_even_if_nothing_is_extracted(tmp_path):
    paths, digests = _archives(tmp_path, speech_names=["../" + _member(1, 1)])
    with pytest.raises(RavdessIndexError, match="unsafe ZIP member"):
        _run(paths, digests, {"speech": 1, "song": 3})


def test_neutral_strong_intensity_is_invalid(tmp_path):
    paths, digests = _archives(tmp_path, speech_names=[_member(1, 1, intensity=2)])
    with pytest.raises(RavdessIndexError, match="neutral"):
        _run(paths, digests, {"speech": 1, "song": 3})


def test_song_disgust_is_invalid(tmp_path):
    paths, digests = _archives(tmp_path, song_names=[_member(1, 2, emotion=7)])
    with pytest.raises(RavdessIndexError, match="song cannot"):
        _run(paths, digests, {"speech": 3, "song": 1})


def test_zero_or_wrong_archive_count_does_not_look_like_complete_dataset(tmp_path):
    paths, digests = _archives(tmp_path)
    with pytest.raises(RavdessIndexError, match="expected 1440"):
        index_ravdess(paths["speech"], paths["song"], expected_md5=digests)


def test_duplicates_in_zip_are_rejected(tmp_path):
    paths, digests = _archives(tmp_path)
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(paths["song"], "a") as archive:
            archive.writestr(_member(1, 2), b"duplicate")
    digests["song"] = hashlib.md5(paths["song"].read_bytes()).hexdigest()
    with pytest.raises(RavdessIndexError, match="duplicate WAV"):
        _run(paths, digests, {"speech": 3, "song": 4})


def test_missing_archive_is_an_explicit_error(tmp_path):
    paths, digests = _archives(tmp_path)
    paths["speech"].unlink()
    with pytest.raises(RavdessIndexError, match="not found"):
        _run(paths, digests)


def test_blank_or_wrong_modality_rejected(tmp_path):
    item = _member(1, 1).replace("03-01", "02-01", 1)
    paths, digests = _archives(tmp_path, speech_names=[item])
    with pytest.raises(RavdessIndexError, match="wrong modality"):
        _run(paths, digests, {"speech": 1, "song": 3})


def test_no_audio_is_extracted_to_filesystem(tmp_path):
    paths, digests = _archives(tmp_path)
    before = {p.name for p in tmp_path.iterdir()}
    _run(paths, digests)
    assert {p.name for p in tmp_path.iterdir()} == before


def test_cli_uses_official_checksums_and_never_overwrites(tmp_path):
    paths, _ = _archives(tmp_path)
    output = tmp_path / "index.json"
    cmd = [sys.executable, "-m", "app.vocal_ravdess", "--speech", str(paths["speech"]),
           "--song", str(paths["song"]), "--output", str(output)]
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "MD5 mismatch" in result.stderr
    assert not output.exists()
    output.write_text(json.dumps({"keep": True}))
    result = subprocess.run(cmd, cwd=root, capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert json.loads(output.read_text()) == {"keep": True}
