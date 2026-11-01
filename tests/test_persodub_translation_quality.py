"""Tests for source-bound, reference-free translation quality triage."""
import json

import pytest

from benchmarks.persodub.translation_quality import (
    _align,
    _number_tokens,
    evaluate,
    main,
)


def _srt(path, rows):
    blocks = []
    for i, (start, end, text) in enumerate(rows, 1):
        def stamp(s):
            seconds = int(s)
            millis = round((s - seconds) * 1000)
            return f"00:00:{seconds:02d},{millis:03d}"

        blocks.append(f"{i}\n{stamp(start)} --> {stamp(end)}\n{text}")
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return path


def test_source_one_cue_to_two_translation_cues_is_single_group():
    source = [{"start": 0.0, "end": 5.0, "text": "One. Two."}]
    target = [
        {"start": 0.0, "end": 2.0, "text": "Один."},
        {"start": 2.0, "end": 5.0, "text": "Два."},
    ]
    groups = _align(source, target)
    assert len(groups) == 1
    assert groups[0]["source_cues"] == [1]
    assert groups[0]["translation_cues"] == [1, 2]
    assert groups[0]["translation_text"] == "Один. Два."


def test_many_source_cues_to_one_translation_cue_is_single_group():
    source = [
        {"start": 0, "end": 2, "text": "One."},
        {"start": 2, "end": 4, "text": "Two."},
    ]
    target = [{"start": 0, "end": 4, "text": "Один. Два."}]
    groups = _align(source, target)
    assert len(groups) == 1
    assert groups[0]["source_cues"] == [1, 2]


def test_mismatched_timelines_keep_unmatched_source_and_translation():
    source = [{"start": 0, "end": 1, "text": "Hello."},
              {"start": 3, "end": 4, "text": "Omitted."}]
    target = [{"start": 0, "end": 1, "text": "Привет."},
              {"start": 6, "end": 7, "text": "Invented."}]
    groups = _align(source, target)
    assert len(groups) == 3
    assert any(row["source_cues"] == [2] and not row["translation_cues"]
               for row in groups)
    assert any(row["translation_cues"] == [2] and not row["source_cues"]
               for row in groups)


def test_source_bound_report_ranks_and_never_certifies(tmp_path):
    source = _srt(tmp_path / "original.srt", [
        (0, 1, "Take 3 breaths."),
        (2, 4, "Keep singing."),
        (5, 6, "This is not translated."),
    ])
    translation = _srt(tmp_path / "translated.srt", [
        (0, 1, "Сделайте три вдоха."),
        (2, 4, "Продолжайте петь."),
    ])
    called = []

    def scorer(pairs):
        called.extend(pairs)
        return [0.8, 0.25]

    report = evaluate(source, translation, score_fn=scorer)
    assert called == [
        ("Take 3 breaths.", "Сделайте три вдоха."),
        ("Keep singing.", "Продолжайте петь."),
    ]
    assert report["input"]["source_cues"] == 3
    assert report["input"]["translation_cues"] == 2
    assert report["summary"]["scored_groups"] == 2
    assert report["summary"]["mean_similarity"] == 0.525
    assert report["summary"]["unmatched_source_groups"] == 1
    assert report["status"] == "OBSERVED"
    assert report["alignment"] == "bounded_monotone_time_dp_v1"
    assert report["semantic_quality_certified"] is False
    assert any("missing_translation" in group["review_flags"]
               for group in report["groups"])
    assert source.read_text(encoding="utf-8").startswith("1\n")


def test_digits_are_review_hints_not_a_score():
    assert _number_tokens("Use 3 tools and 10 seconds") == ["10", "3"]
    assert _number_tokens("Возьмите три приёма") == []
    assert _number_tokens("1,2,3") == ["1,2", "3"]


def test_identical_files_and_invalid_timing_are_rejected(tmp_path):
    source = _srt(tmp_path / "s.srt", [(0, 1, "Hello.")])
    with pytest.raises(ValueError, match="different"):
        evaluate(source, source, score_fn=lambda pairs: [1.0])
    target = _srt(tmp_path / "t.srt", [(3, 2, "Привет.")])
    with pytest.raises(ValueError, match="timestamp"):
        evaluate(source, target, score_fn=lambda pairs: [0.5])


def test_incomplete_non_finite_scorer_never_passes(tmp_path):
    source = _srt(tmp_path / "s.srt", [(0, 1, "One."), (2, 3, "Two.")])
    target = _srt(tmp_path / "t.srt", [(0, 1, "Один."), (2, 3, "Два.")])
    for values in ([], [float("nan"), 0.5], [0.5]):
        with pytest.raises(ValueError, match="Scorer"):
            evaluate(source, target, score_fn=lambda pairs, v=values: v)


def test_cli_writes_scored_report_without_modifying_inputs(tmp_path, monkeypatch):
    source = _srt(tmp_path / "s.srt", [(0, 1, "Hello.")])
    target = _srt(tmp_path / "t.srt", [(0, 1, "Привет.")])
    out = tmp_path / "reports" / "quality.json"
    import benchmarks.persodub.translation_quality as mod

    monkeypatch.setattr(mod, "_embedding_scores",
                        lambda pairs, *a: ([0.7], {"method": "fixture"}))
    assert main(["--source", str(source), "--translation", str(target),
                 "--out", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["summary"]["scored_groups"] == 1
    assert result["model"]["method"] == "fixture"
    assert source.exists() and target.exists()


def test_comet_requires_existing_checkpoint(tmp_path):
    source = _srt(tmp_path / "s.srt", [(0, 1, "Hello.")])
    target = _srt(tmp_path / "t.srt", [(0, 1, "Привет.")])
    with pytest.raises(ValueError, match="checkpoint"):
        evaluate(source, target, scorer="comet")


def test_time_alignment_does_not_chain_adjacent_cues():
    source = [
        {"start": i * 2, "end": (i + 1) * 2, "text": f"Source {i}"}
        for i in range(8)
    ]
    translated = [
        {"start": i * 2, "end": (i + 1) * 2 + 0.2,
         "text": f"Translation {i}"}
        for i in range(8)
    ]
    groups = _align(source, translated)
    assert len(groups) == 8
    assert all(len(row["source_cues"]) == 1 for row in groups)
    assert all(len(row["translation_cues"]) == 1 for row in groups)


def test_chain_ingests_only_matching_source_bound_quality_report(tmp_path):
    from benchmarks.persodub.runner import run_chain

    source = _srt(tmp_path / "en.srt", [(0, 1, "One."), (2, 3, "Two.")])
    target = _srt(tmp_path / "ru.srt", [(0, 1, "Один."), (2, 3, "Два.")])
    report = evaluate(source, target, score_fn=lambda pairs: [0.5, 0.6])
    (tmp_path / "scores.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8"
    )
    manifest = {
        "schema_version": 1,
        "suite_id": "real-score-ingestion",
        "cases": [{
            "id": "translation", "stage": "translation",
            "oracle_kind": "source_derived_proxy",
            "reference": "en.srt", "candidate": "ru.srt",
            "quality_report": "scores.json",
        }],
    }
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = run_chain(path)
    assert result["overall"] == "INCOMPLETE"
    assert result["cases"][0]["status"] == "OBSERVED"
    assert result["cases"][0]["metrics"]["mean_similarity"] == 0.55

    target.write_text(target.read_text() + "\nChanged", encoding="utf-8")
    result = run_chain(path)
    assert result["cases"][0]["status"] == "ERROR"
    assert "identity mismatch" in result["cases"][0]["reason"]
