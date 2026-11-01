"""Bounded source ASR: checkpoint ownership, overlap, timeout, and source QA."""
import json
import subprocess
from types import SimpleNamespace

import pytest

from benchmarks.persodub import chunked_source_probe as probe


def _job(tmp_path, monkeypatch):
    media = tmp_path / "src" / "input.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video-original-without-mutation")
    transcript = media.parent / "transcript.json"
    transcript.write_text(json.dumps({"cues": [
        {
            "start": 0.5, "end": 1.7, "text": "First line.",
            "words": [{"start": 0.5, "end": 1.7, "word": "First line."}],
        },
        {
            "start": 31.6, "end": 33.8, "text": "Second line.",
            "words": [{"start": 31.6, "end": 31.6, "word": "Second"},
                      {"start": 32, "end": 33.8, "word": " line."}],
        },
        {
            "start": 38, "end": 40, "text": "Third line.",
            "words": [{"start": 38, "end": 40, "word": "Third line."}],
        },
    ]}), encoding="utf-8")
    model = tmp_path / "models" / "large"
    model.mkdir(parents=True)
    (model / "model.bin").write_bytes(b"model-v1")
    (model / "config.json").write_text("{}")
    monkeypatch.setattr(probe, "_media_duration", lambda _: 60.0)
    monkeypatch.setattr(probe.importlib.metadata, "version", lambda _: "fixture")
    output = tmp_path / "reports" / "report.json"
    output.parent.mkdir()
    return media, transcript, model, output


def _fake_runner(counts):
    def run(command, **kwargs):
        counts.append((command, kwargs))
        start = float(command[command.index("--start") + 1])
        end = float(command[command.index("--end") + 1])
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "status": "complete",
            "source_language": "en",
            "segments": [{
                "start_s": start + 0.5,
                "end_s": min(end, start + 2),
                "text": "First line",
                "words": [{
                    "start": start + 0.5, "end": start + 1,
                    "word": " First",
                }, {
                    "start": start + 1, "end": min(end, start + 2),
                    "word": " line",
                }],
            }],
        }))
    return run


def test_planning_avoids_tiny_tail_and_assigns_disjoint_overlap():
    plan = probe.plan_windows(234.684, 34, 5)
    assert len(plan) == 8
    assert plan[0]["core_start_s"] == 0.0
    assert plan[-1]["end_s"] == pytest.approx(234.684)
    assert plan[-1]["core_end_s"] == pytest.approx(234.684)
    for a, b in zip(plan, plan[1:]):
        assert a["end_s"] > b["start_s"]
        assert a["core_end_s"] == b["core_start_s"]
    assert max(x["end_s"] - x["start_s"] for x in plan) <= 34


@pytest.mark.parametrize("duration,window,overlap", [
    (0, 34, 5), (float("inf"), 34, 5), (35, 40, 5),
    (35, 15, 10), (35, 8, 1), (35, 30, -1),
])
def test_bad_window_plans_rejected(duration, window, overlap):
    with pytest.raises(ValueError):
        probe.plan_windows(duration, window, overlap)


def test_boundary_words_belong_to_one_core_only():
    first = {"core_start_s": 0, "core_end_s": 31.5, "end_s": 34}
    second = {"core_start_s": 31.5, "core_end_s": 60,
              "end_s": 60}
    cues = [{"start": 31.4, "end": 31.6, "text": "Shared phrase",
             "words": [{"start": 31.4, "end": 31.6, "word": " Shared"},
                       {"start": 31.6, "end": 31.9, "word": " phrase"}]}]
    original = [{
        "start": 31.4, "end": 31.9, "text": "Shared phrase",
        "words": cues[0]["words"],
    }]
    a = probe.window_comparison(first, cues, original)
    b = probe.window_comparison(second, cues, original)
    assert a["fresh_owned_words"] == 0
    assert b["fresh_owned_words"] == 2
    assert a["source_cues"] == 0
    assert b["source_cues"] == 1


def test_real_checkpoint_resume_does_not_rerun_completed(tmp_path, monkeypatch):
    media, transcript, model, output = _job(tmp_path, monkeypatch)
    original_bytes = media.read_bytes()
    called = []
    r = _fake_runner(called)
    first = probe.run_probe(media, transcript, model, output,
                            max_new_chunks=1, runner=r)
    assert first["summary"]["completed"] == 1
    assert first["summary"]["not_run"] == 1
    assert len(called) == 1
    assert called[0][1]["timeout"] == 70
    assert "model.bin" not in str(called[0][0])  # CLI receives directory
    second = probe.run_probe(media, transcript, model, output, runner=r)
    assert second["summary"]["completed"] == 2
    assert len(called) == 2
    assert second["summary"]["source_owned_zero_duration_words"] == 1
    assert second["summary"]["fresh_raw_word_count_with_overlap"] == 4
    assert second["summary"]["fresh_raw_zero_duration_words_with_overlap"] == 0
    assert second["summary"]["fresh_owned_word_count"] <= 4
    assert media.read_bytes() == original_bytes
    third = probe.run_probe(media, transcript, model, output, runner=r)
    assert third["summary"] == second["summary"]
    assert len(called) == 2


def test_changed_source_or_model_rejects_reusing_old_checkpoint(tmp_path, monkeypatch):
    media, transcript, model, output = _job(tmp_path, monkeypatch)
    runner = _fake_runner([])
    probe.run_probe(media, transcript, model, output, max_new_chunks=1, runner=runner)
    media.write_bytes(b"changed-video")
    with pytest.raises(ValueError, match="identity"):
        probe.run_probe(media, transcript, model, output, runner=runner)
    media.write_bytes(b"video-original-without-mutation")
    (model / "model.bin").write_bytes(b"changed-model")
    with pytest.raises(ValueError, match="identity"):
        probe.run_probe(media, transcript, model, output, runner=runner)


def test_timeout_is_recorded_never_treated_as_completed(tmp_path, monkeypatch):
    media, transcript, model, output = _job(tmp_path, monkeypatch)
    calls = []
    def time_out(command, **kwargs):
        calls.append(1)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
    first = probe.run_probe(
        media, transcript, model, output, max_new_chunks=1, runner=time_out,
    )
    assert first["summary"]["timeouts"] == 1
    assert first["summary"]["completed"] == 0
    second = probe.run_probe(
        media, transcript, model, output, runner=_fake_runner(calls),
        max_new_chunks=1,
    )
    assert second["summary"]["timeouts"] == 1
    assert second["summary"]["completed"] == 1
    third = probe.run_probe(
        media, transcript, model, output, runner=_fake_runner(calls),
        retry_failed=True,
        max_new_chunks=1,
    )
    assert third["summary"]["timeouts"] == 0
    assert third["summary"]["completed"] == 2


def test_no_source_audio_or_model_weight_mutation(tmp_path, monkeypatch):
    media, transcript, model, output = _job(tmp_path, monkeypatch)
    orig = {
        "media": probe.sha256(media),
        "transcript": probe.sha256(transcript),
        "model": probe.sha256(model / "model.bin"),
    }
    probe.run_probe(media, transcript, model, output, runner=_fake_runner([]))
    assert probe.sha256(media) == orig["media"]
    assert probe.sha256(transcript) == orig["transcript"]
    assert probe.sha256(model / "model.bin") == orig["model"]
    assert json.loads(output.read_text())["observational_only"] is True
    assert json.loads(output.read_text())["translation_adequacy_verified"] is False


def test_select_only_critical_windows_then_resume_other_regions(tmp_path, monkeypatch):
    media, transcript, model, output = _job(tmp_path, monkeypatch)
    calls = []
    one = probe.run_probe(
        media, transcript, model, output, only_indices={1},
        runner=_fake_runner(calls),
    )
    assert one["summary"]["completed"] == 1
    assert [x["index"] for x in one["chunks"]] == [1]
    assert one["summary"]["not_run"] == 1
    all_done = probe.run_probe(
        media, transcript, model, output,
        runner=_fake_runner(calls),
    )
    assert all_done["summary"]["completed"] == 2
    assert len(calls) == 2


@pytest.mark.parametrize("selection", [set(), {-1}, {2}, {1, "0"}])
def test_invalid_window_selection_rejected(tmp_path, monkeypatch, selection):
    media, transcript, model, output = _job(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="index"):
        probe.run_probe(
            media, transcript, model, output,
            only_indices=selection, runner=_fake_runner([]),
        )


def _overlap_window(words):
    """Synthetic, timestamped ASR words around the 29-34-second overlap."""
    return {"segments": [{
        "start_s": 30.0, "end_s": 33.0,
        "text": " ".join(words),
        "words": [{
            "start": 30.1 + i * 0.5,
            "end": 30.4 + i * 0.5,
            "word": " " + word,
        } for i, word in enumerate(words)],
    }]}


def test_lexical_overlap_agreement_is_only_observed_not_asr_gold():
    left, right = probe.plan_windows(60, 34, 5)[:2]
    a = _overlap_window(["take", "a", "breath", "now"])
    b = _overlap_window(["take", "a", "breath", "now"])
    diagnostic = probe.overlap_diagnostic(left, right, a, b)
    assert diagnostic["start_s"] == 29
    assert diagnostic["end_s"] == 34
    assert diagnostic["lexical_ratio"] == 1
    assert diagnostic["status"] == "observed_not_human_verified"
    assert diagnostic["verified_source_text"] is False


def test_lexical_overlap_disagreement_and_one_sided_are_review_items():
    left, right = probe.plan_windows(60, 34, 5)[:2]
    a = _overlap_window(["take", "a", "breath", "now"])
    b = _overlap_window(["move", "your", "shoulders", "gently"])
    disagreement = probe.overlap_diagnostic(left, right, a, b)
    assert disagreement["status"] == "needs_review_different_words"
    assert disagreement["lexical_ratio"] == 0
    only_one = probe.overlap_diagnostic(
        left, right, a, {"segments": []}
    )
    assert only_one["status"] == "needs_review_one_sided"
    no_speech = probe.overlap_diagnostic(
        left, right, {"segments": []}, {"segments": []}
    )
    assert no_speech["status"] == "no_observed_words"
    assert no_speech["lexical_ratio"] is None


def test_spelled_alphabet_overlap_does_not_raise_false_vocal_review():
    left, right = probe.plan_windows(60, 34, 5)[:2]
    a = _overlap_window(["ABCD"])
    b = _overlap_window(["A,", "B,", "C,", "D."])
    result = probe.overlap_diagnostic(left, right, a, b)
    assert result["status"] == "observed_not_human_verified"
    assert result["lexical_ratio"] == 1.0
    assert probe._normalize_alphabet_runs(
        ["a", "b", "c", "d", "but", "a", "b", "c", "d"]
    ) == ["abcd", "but", "abcd"]
    # The metric must not erase an actually missing letter.
    assert probe._normalize_alphabet_runs(["a", "b", "d"]) == ["a", "b", "d"]
