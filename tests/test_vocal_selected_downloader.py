"""Offline tests for selected-file download identity and read/sing name collisions."""

import hashlib
import io
import json
from pathlib import Path

import pytest

from tools.vocal_bench import download_selected as selected

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "docs/vocal-auto-events-benchmark-20261031/selected-source-manifest.json"
)


def test_source_id_filenames_are_corpus_qualified():
    read = "NUS-48E::corpus/ADIZ/read/01.wav"
    sing = "NUS-48E::corpus/ADIZ/sing/01.wav"
    assert selected.local_basename(read) != selected.local_basename(sing)
    assert selected.local_basename(read) == selected.local_basename(read)


def test_planning_does_not_fetch_or_write_files(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("dry run must never open a network connection")
    monkeypatch.setattr(selected.urllib.request, "urlopen", no_network)
    target = tmp_path / "not-created"
    selection = selected.collect(FIXTURE, target, dry_run=True)
    assert len(selection) == 32
    assert not target.exists()
    assert all(entry["status"] == "planned" for entry in selection.values())


def test_select_two_nus_files_with_identical_base_name(tmp_path, monkeypatch):
    ids = ["NUS-48E::corpus/ADIZ/read/01.wav", "NUS-48E::corpus/ADIZ/sing/01.wav"]
    monkeypatch.setattr(selected.urllib.request, "urlopen", lambda *a, **k: None)
    selection = selected.collect(FIXTURE, tmp_path, selected=ids, dry_run=True)
    assert set(selection) == set(ids)
    assert len({entry["wav_name"] for entry in selection.values()}) == 2
    assert all("publisher_alignment_name" in entry for entry in selection.values())


def test_rejected_unlisted_source_before_network(tmp_path, monkeypatch):
    monkeypatch.setattr(selected.urllib.request, "urlopen", lambda *a, **k: None)
    dest = tmp_path / "not-created"
    with pytest.raises(ValueError, match="not in the frozen benchmark"):
        selected.collect(FIXTURE, dest, selected=["missing"], dry_run=False)
    assert not dest.exists()


def test_fetch_hash_mismatch_never_writes_a_file(tmp_path, monkeypatch):
    payload = b"incorrect-source"
    monkeypatch.setattr(
        selected.urllib.request, "urlopen",
        lambda *a, **k: io.BytesIO(payload)
    )
    dest = tmp_path / "frozen.wav"
    with pytest.raises(ValueError, match="differs"):
        selected.fetch("https://example.com/source.wav", len(payload), "f" * 64, dest)
    assert not dest.exists()


def test_existing_selected_file_requires_byte_level_identity(tmp_path, monkeypatch):
    content = b"pre-existing-WAV-test-bytes"
    digest = hashlib.sha256(content).hexdigest()
    path = tmp_path / "verified.wav"
    path.write_bytes(content)
    monkeypatch.setattr(selected.urllib.request, "urlopen", lambda *a, **k: None)
    assert selected.fetch("https://example.com/source.wav", len(content), digest, path) == "verified_existing"
    with pytest.raises(ValueError, match="wrong hash"):
        selected.fetch("https://example.com/source.wav", len(content), "0" * 64, path)


def test_single_selected_mock_download_and_index(tmp_path, monkeypatch):
    manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
    specimen = manifest["clips"][0]
    raw = b"RIFFsynthetic-test-wave"
    specimen["wav_bytes"] = len(raw)
    specimen["wav_sha256"] = hashlib.sha256(raw).hexdigest()
    file_path = tmp_path / "synthetic-source-list.json"
    file_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(
        selected.urllib.request, "urlopen",
        lambda *a, **k: io.BytesIO(raw),
    )
    out = tmp_path / "downloaded"
    found = selected.collect(file_path, out, selected=[specimen["id"]])
    assert len(found) == 1
    wav_file = out / found[specimen["id"]]["wav_name"]
    assert wav_file.read_bytes() == raw
    assert (out / "source-index.json").is_file()
    with pytest.raises(ValueError, match="fresh output"):
        selected.collect(file_path, out, selected=[specimen["id"]])


def test_no_implicit_whole_dataset_download(tmp_path, monkeypatch):
    called = []
    def fake_open(url, **kwargs):
        called.append(url)
        raise AssertionError("would contact network only for whitelisted source")
    monkeypatch.setattr(selected.urllib.request, "urlopen", fake_open)
    single = "ESC-50::audio/4-132803-A-26.wav"
    result = selected.collect(FIXTURE, tmp_path, selected=[single], dry_run=True)
    assert set(result) == {single}
    assert called == []
