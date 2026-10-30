"""Human annotation validation and canonical scoring-contract projection."""

from copy import deepcopy

import pytest

from app.vocal_gold_annotations import GoldAnnotationError, compile_gold_annotations


def event(start, end, kind, identifier, **kwargs):
    row = {"event_id": identifier, "start_sample": start, "end_sample": end,
           "event_type": kind, "reason": kind}
    row.update(kwargs)
    return row


def annotations(events=None):
    return {"schema_version": 1, "source_sha256": "a" * 64, "pcm_sha256": "b" * 64,
            "sample_rate": 48000, "total_samples": 100,
            "source_revision": "pcm-prep-1", "annotation_revision": "adjudicated-v1",
            "events": events or [
                event(0, 25, "explanation", "speech1", source_language="de", source_text="Jetzt singe ich."),
                event(25, 55, "vocal_demo", "vowel"),
                event(55, 75, "non_target", "silence"),
                event(75, 100, "uncertain", "ambiguous")
            ]}


def test_complete_gold_manifest_and_vocal_only_counts():
    source = annotations()
    frozen = deepcopy(source)
    manifest, report = compile_gold_annotations(source)
    assert source == frozen
    assert [row["action"] for row in manifest["segments"]] == [
        "TRANSLATE", "PRESERVE", "PRESERVE", "REVIEW"]
    assert report["vocal_demo_events"] == 1
    assert report["vocal_demo_samples"] == 30
    assert report["event_samples"]["non_target"] == 20
    assert report["event_counts"]["uncertain"] == 1
    assert "model_revisions" not in manifest


def test_actual_source_words_and_speaker_are_preserved():
    row = event(0, 100, "explanation", "one", speaker_id="SPK1",
                source_language="en", source_text="Try this exercise.")
    result, _ = compile_gold_annotations(annotations([row]))
    assert result["segments"][0]["source_text"] == "Try this exercise."
    assert result["segments"][0]["speaker_id"] == "SPK1"


def test_speech_vocal_overlap_is_review_not_translate():
    row = event(0, 100, "speech_vocal_overlap", "mixed", source_language="de",
                source_text="Jetzt weiter")
    result, _ = compile_gold_annotations(annotations([row]))
    assert result["segments"][0]["action"] == "REVIEW"


@pytest.mark.parametrize("kind", ["vocal_demo", "non_target", "speech_vocal_overlap", "uncertain"])
def test_all_non_explanations_are_not_translated(kind):
    result, _ = compile_gold_annotations(annotations([event(0, 100, kind, "one")]))
    assert result["segments"][0]["action"] != "TRANSLATE"


def test_one_sample_vocal_demo_is_separately_counted():
    events = [event(0, 99, "non_target", "quiet"), event(99, 100, "vocal_demo", "onset")]
    _, result = compile_gold_annotations(annotations(events))
    assert result["vocal_demo_samples"] == 1
    assert result["vocal_demo_events"] == 1


@pytest.mark.parametrize("invalid", [
    {"events": []}, {"schema_version": 2}, {"schema_version": True},
    {"source_revision": " "}, {"annotation_revision": None},
    {"total_samples": 0}, {"sample_rate": True},
    {"unexpected_key": "ignored?"},
])
def test_metadata_rejected(invalid):
    x = annotations()
    x.update(invalid)
    with pytest.raises((GoldAnnotationError, ValueError)):
        compile_gold_annotations(x)


@pytest.mark.parametrize("bad", [
    event(0, 0, "vocal_demo", "bad"),
    event(0, 101, "vocal_demo", "bad"),
    event(-1, 100, "vocal_demo", "bad"),
    event(True, 100, "vocal_demo", "bad"),
    event(0.0, 100, "vocal_demo", "bad"),
    event(0, 100, "unknown", "bad"),
    event(0, 100, "vocal_demo", "bad", source_text="Aaaa"),
    event(0, 100, "non_target", "bad", source_text="Aaaa"),
    event(0, 100, "explanation", "bad", source_language="de"),
    event(0, 100, "explanation", "bad", source_language="und", source_text="voice"),
    event(0, 100, "explanation", "bad", source_language="es", source_text="hola"),
    event(0, 100, "explanation", "bad", source_language="de", source_text=" "),
    event(0, 100, "vocal_demo", "bad", reason=""),
    event(0, 100, "vocal_demo", "bad", speaker_id=3),
    event(0, 100, "vocal_demo", "bad", extra="silent field"),
])
def test_bad_event_is_rejected(bad):
    with pytest.raises((GoldAnnotationError, ValueError)):
        compile_gold_annotations(annotations([bad]))


def test_duplicate_ids_are_rejected():
    rows = [event(0, 50, "non_target", "dup"), event(50, 100, "vocal_demo", "dup")]
    with pytest.raises(GoldAnnotationError, match="duplicate"):
        compile_gold_annotations(annotations(rows))


def test_gap_and_overlap_are_rejected_by_canonical_validator():
    for rows in [
        [event(0, 49, "non_target", "a"), event(50, 100, "vocal_demo", "b")],
        [event(0, 51, "non_target", "a"), event(50, 100, "vocal_demo", "b")],
    ]:
        with pytest.raises(ValueError):
            compile_gold_annotations(annotations(rows))


def test_integer_sample_counts_remain_exact_above_float_range():
    base = 2**53 + 5
    source = annotations([event(0, base, "non_target", "quiet"), event(base, base + 1, "vocal_demo", "attack")])
    source["total_samples"] = base + 1
    _, report = compile_gold_annotations(source)
    assert report["event_samples"]["non_target"] == base
    assert report["vocal_demo_samples"] == 1


def test_schema_requires_integer_not_equal_float():
    value = annotations()
    value["schema_version"] = 1.0
    with pytest.raises(GoldAnnotationError, match="schema_version"):
        compile_gold_annotations(value)


def test_sample_rate_must_be_positive():
    value = annotations()
    value["sample_rate"] = 0
    with pytest.raises(GoldAnnotationError, match="sample_rate"):
        compile_gold_annotations(value)


def test_cli_exports_both_derived_files(tmp_path):
    import json

    from app.vocal_gold_annotations import main

    source = tmp_path / "human.json"
    manifest = tmp_path / "gold.decisions.json"
    summary = tmp_path / "gold.events.json"
    source.write_text(json.dumps(annotations()), encoding="utf-8")
    assert main(["--annotations", str(source), "--manifest-out", str(manifest),
                 "--summary-out", str(summary)]) == 0
    assert json.loads(manifest.read_text(encoding="utf-8"))["segments"][1]["action"] == "PRESERVE"
    assert json.loads(summary.read_text(encoding="utf-8"))["vocal_demo_samples"] == 30


def test_cli_invalid_annotation_never_writes_outputs(tmp_path):
    import json

    from app.vocal_gold_annotations import main

    invalid = annotations()
    invalid["events"] = []
    source = tmp_path / "invalid.json"
    manifest = tmp_path / "gold.decisions.json"
    summary = tmp_path / "gold.events.json"
    source.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(SystemExit) as failure:
        main(["--annotations", str(source), "--manifest-out", str(manifest),
              "--summary-out", str(summary)])
    assert failure.value.code == 2
    assert not manifest.exists() and not summary.exists()


def test_cli_does_not_overwrite_annotation_input(tmp_path):
    import json

    from app.vocal_gold_annotations import main

    source = tmp_path / "human.json"
    summary = tmp_path / "summary.json"
    source.write_text(json.dumps(annotations()), encoding="utf-8")
    with pytest.raises(SystemExit) as failure:
        main(["--annotations", str(source), "--manifest-out", str(source),
              "--summary-out", str(summary)])
    assert failure.value.code == 2

def test_summary_explicitly_zeroes_absent_event_categories():
    source = annotations([event(0, 100, "non_target", "quiet")])
    _, result = compile_gold_annotations(source)
    assert result["event_counts"] == {
        "explanation": 0, "vocal_demo": 0, "non_target": 1,
        "speech_vocal_overlap": 0, "uncertain": 0,
    }
    assert result["vocal_demo_events"] == 0
    assert result["vocal_demo_samples"] == 0
