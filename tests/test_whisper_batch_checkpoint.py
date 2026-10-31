"""Source-bound Whisper score-take checkpoints without ML/GPU dependencies."""

import json
import os
import sqlite3

import pytest

from app.scripts import whisper_transcribe as worker


@pytest.fixture
def setup_batch(tmp_path, monkeypatch):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "model.bin").write_bytes(b"frozen weights v1")
    (model_dir / "config.json").write_text('{"type":"test"}')
    monkeypatch.setenv("WHISPER_MODEL_DIR", str(model_dir))
    paths = [str(tmp_path / "take0.wav"), str(tmp_path / "take1.wav"),
             str(tmp_path / "take2.wav")]
    for i, path in enumerate(paths):
        with open(path, "wb") as handle:
            handle.write(("raw voice %d" % i).encode())
    calls = []

    def load():
        calls.append("model loaded")
        return object()

    def transcribe(model, path, language, words, allow_split=True):
        calls.append(("transcribed", path, language, words, allow_split))
        return [{"start": 0.0, "end": 1.0,
                 "text": "speech from %s" % os.path.basename(path)}], language

    monkeypatch.setattr(worker, "_load_model", load)
    monkeypatch.setattr(worker, "_transcribe_with", transcribe)
    return paths, calls, str(tmp_path / "checkpoint.sqlite3"), str(tmp_path / "progress.json"), model_dir


def _stored(cache):
    with sqlite3.connect(cache) as db:
        rows = db.execute("SELECT path,sha256,result FROM takes").fetchall()
        context_row = db.execute(
            "SELECT value FROM metadata WHERE key='context'"
        ).fetchone()
    return {
        "entries": {path: {"sha256": sha, "result": json.loads(result)}
                    for path, sha, result in rows},
        "context": json.loads(context_row[0]),
    }


def _run(batch, language="ru"):
    paths, _, checkpoint, progress, _ = batch
    return worker._transcribe_batch_checkpointed(paths, language, False, checkpoint, progress)


def test_first_pass_writes_atomic_per_take_cache_and_progress(setup_batch):
    paths, calls, cache, progress, _ = setup_batch
    output = _run(setup_batch)
    assert list(output) == paths
    assert all(x["ok"] is True for x in output.values())
    assert calls.count("model loaded") == 1
    assert len([x for x in calls if isinstance(x, tuple)]) == 3
    saved = _stored(cache)
    assert len(saved["entries"]) == 3
    assert saved["context"]["language"] == "ru"
    assert all(len(entry["sha256"]) == 64 for entry in saved["entries"].values())
    stats = json.load(open(progress, encoding="utf-8"))
    assert (stats["done"], stats["total"], stats["reused"]) == (3, 3, 0)
    assert not os.path.exists(cache + ".part")
    assert not os.path.exists(progress + ".part")


def test_resume_skips_all_cached_takes_and_model_load(setup_batch):
    paths, calls, _, progress, _ = setup_batch
    baseline = _run(setup_batch)
    calls.clear()
    repeated = _run(setup_batch)
    assert repeated == baseline
    assert calls == []
    stats = json.load(open(progress, encoding="utf-8"))
    assert (stats["done"], stats["reused"]) == (3, 3)


def test_changed_source_sha_recalculates_only_its_take(setup_batch):
    paths, calls, _, progress, _ = setup_batch
    _run(setup_batch)
    calls.clear()
    with open(paths[1], "ab") as f:
        f.write(b" NEW AUDIO BYTES")
    _run(setup_batch)
    rescored = [x for x in calls if isinstance(x, tuple)]
    assert len(rescored) == 1 and rescored[0][1] == paths[1]
    assert calls.count("model loaded") == 1
    assert json.load(open(progress, encoding="utf-8"))["reused"] == 2


def test_changed_language_or_model_invalidates_all_takes(setup_batch):
    paths, calls, _, _, model_dir = setup_batch
    _run(setup_batch)
    calls.clear()
    _run(setup_batch, language="en")
    assert len([x for x in calls if isinstance(x, tuple)]) == 3
    calls.clear()
    with open(model_dir / "model.bin", "ab") as f:
        f.write(b" changed weights")
    _run(setup_batch, language="en")
    assert len([x for x in calls if isinstance(x, tuple)]) == 3
    calls.clear()
    (model_dir / "config.json").write_text('{"type":"new"}')
    _run(setup_batch, language="en")
    assert len([x for x in calls if isinstance(x, tuple)]) == 3


def test_crash_after_one_take_retains_a_valid_resumable_checkpoint(setup_batch, monkeypatch):
    paths, calls, cache, progress, _ = setup_batch
    original = worker._transcribe_with

    def crash_on_second(model, path, *args, **kwargs):
        if path == paths[1]:
            raise KeyboardInterrupt("simulate lost process")
        return original(model, path, *args, **kwargs)

    monkeypatch.setattr(worker, "_transcribe_with", crash_on_second)
    with pytest.raises(KeyboardInterrupt):
        _run(setup_batch)
    assert len(_stored(cache)["entries"]) == 1
    assert json.load(open(progress))["done"] == 1
    monkeypatch.setattr(worker, "_transcribe_with", original)
    calls.clear()
    result = _run(setup_batch)
    assert all(entry["ok"] for entry in result.values())
    assert [call[1] for call in calls if isinstance(call, tuple)] == paths[1:]
    assert json.load(open(progress))["reused"] == 1


def test_failed_take_retried_and_not_cached(setup_batch, monkeypatch):
    paths, calls, cache, _, _ = setup_batch
    original = worker._transcribe_with

    def fail_one(model, path, *args, **kwargs):
        if path == paths[1]:
            raise RuntimeError("not ready")
        return original(model, path, *args, **kwargs)

    monkeypatch.setattr(worker, "_transcribe_with", fail_one)
    result = _run(setup_batch)
    assert result[paths[1]]["ok"] is False
    assert paths[1] not in _stored(cache)["entries"]
    monkeypatch.setattr(worker, "_transcribe_with", original)
    calls.clear()
    result = _run(setup_batch)
    assert result[paths[1]]["ok"]
    assert [x[1] for x in calls if isinstance(x, tuple)] == [paths[1]]


def test_corrupt_checkpoint_is_preserved_and_rebuilt(setup_batch):
    paths, calls, cache, _, _ = setup_batch
    with open(cache, "w") as f:
        f.write("{broken")
    _run(setup_batch)
    assert len([x for x in calls if isinstance(x, tuple)]) == 3
    assert len(_stored(cache)["entries"]) == 3
    assert list(__import__("pathlib").Path(cache).parent.glob("checkpoint.sqlite3.corrupt-*"))


def test_batch_refuses_duplicate_file_ids_or_shared_progress_path(setup_batch):
    paths, calls, cache, progress, _ = setup_batch
    with pytest.raises(ValueError, match="Duplicate"):
        worker._transcribe_batch_checkpointed(
            [paths[0], paths[0]], "ru", False, cache, progress,
        )
    with pytest.raises(ValueError, match="distinct"):
        worker._transcribe_batch_checkpointed(paths, "ru", False, cache, cache)
    assert calls == []
