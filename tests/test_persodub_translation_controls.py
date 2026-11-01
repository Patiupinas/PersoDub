"""Synthetic-probe and provenance tests, without model downloads."""
import json

import pytest

from benchmarks.persodub.translation_controls import (
    evaluate_scores,
    load_controls,
    load_real_groups,
)


def _control(cid="c1", faithful="Пойте мягко.", altered="Пойте громко."):
    return {
        "id": cid,
        "kind": "test",
        "source": "Sing softly.",
        "faithful": faithful,
        "altered": altered,
    }


def _fixture(path, cases):
    path.write_text(
        json.dumps({"schema_version": 1, "suite_id": "unit",
                    "cases": cases}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_control_fixture_is_versioned_and_has_distinct_candidates(tmp_path):
    file = _fixture(tmp_path / "cases.json",
                    [_control("a"), _control("b")])
    assert len(load_controls(file)) == 2

    with pytest.raises(ValueError, match="Duplicate"):
        load_controls(_fixture(file, [_control(), _control()]))
    with pytest.raises(ValueError, match="identical"):
        load_controls(_fixture(file, [_control("a", "Один.", "Один."),
                                    _control("b")]))
    with pytest.raises(ValueError, match="schema"):
        file.write_text('{"schema_version":2,"cases":[]}')
        load_controls(file)


def test_model_authored_controls_never_become_quality_certificate():
    cases = [_control("a"), _control("b")]
    report = evaluate_scores(
        cases, [0.9, 0.2, 0.4, 0.5],
        embedding_meta={"model": "fixture"},
        nli_scores=[
            {"symmetric_entailment": 0.7},
            {"symmetric_entailment": 0.1},
            {"symmetric_entailment": 0.8},
            {"symmetric_entailment": 0.9},
        ],
        nli_meta={"model": "fixture"},
    )
    assert report["status"] == "OBSERVED"
    assert report["translation_quality_verified"] is False
    assert report["summary"]["controls"] == 2
    assert report["summary"]["embedding_pairwise_wins"] == 1
    assert report["summary"]["nli_pairwise_wins"] == 1
    assert report["summary"]["embedding_missed_control_ids"] == ["b"]
    assert report["summary"]["nli_missed_control_ids"] == ["b"]
    assert "not_human_gold" in report["control_oracle"]
    assert report["real_rows"] == []


def test_control_report_covers_real_groups_without_fake_gold():
    report = evaluate_scores(
        [_control("a"), _control("b")],
        [0.8, 0.3, 0.9, 0.7, 0.42],
        embedding_meta={"model": "fixture"},
        real_groups=[{
            "start_s": 3.0, "end_s": 7.0,
            "source_cues": [1], "translation_cues": [1, 2],
            "source_text": "Hello.", "translation_text": "Привет."
        }],
    )
    assert len(report["real_rows"]) == 1
    assert report["real_rows"][0]["embedding_score"] == 0.42
    assert report["nli_model"]["status"] == "NOT_RUN"


def test_model_scores_must_be_complete_and_finite():
    for values in ([0.1], [0.3, float("nan"), 0.1, 0.9],
                   [0.3, float("inf"), 0.1, 0.2]):
        with pytest.raises(ValueError, match="Embedding score"):
            evaluate_scores(
                [_control("a"), _control("b")], values,
                embedding_meta={"model": "fixture"}
            )
    with pytest.raises(ValueError, match="NLI score count"):
        evaluate_scores(
            [_control("a"), _control("b")], [0.1] * 4,
            embedding_meta={}, nli_scores=[{}],
        )


def test_real_report_requires_source_bound_observed_status(tmp_path):
    path = tmp_path / "source.json"
    for obj in (
        {"schema_version": 2, "status": "OBSERVED",
         "semantic_quality_certified": False, "groups": []},
        {"schema_version": 1, "status": "PASS",
         "semantic_quality_certified": False, "groups": []},
        {"schema_version": 1, "status": "OBSERVED",
         "semantic_quality_certified": True, "groups": []},
    ):
        path.write_text(json.dumps(obj), encoding="utf-8")
        with pytest.raises(ValueError, match="observed"):
            load_real_groups(path)
    path.write_text(json.dumps({
        "schema_version": 1, "status": "OBSERVED",
        "semantic_quality_certified": False,
        "groups": [
            {"source_text": "Hello", "translation_text": "Привет"},
            {"source_text": "A", "translation_text": ""},
        ],
    }), encoding="utf-8")
    assert len(load_real_groups(path)) == 1


def test_real_synthetic_cases_are_not_user_media():
    from pathlib import Path

    fixture_path = (
        Path(__file__).resolve().parent.parent
        / "benchmarks/persodub/fixtures/translation_synthetic_controls_v1.json"
    )
    cases = load_controls(fixture_path)
    assert len(cases) == 20
    assert all(case["source"] != case["faithful"]
               and case["source"] != case["altered"] for case in cases)
    assert len({case["id"] for case in cases}) == len(cases)
