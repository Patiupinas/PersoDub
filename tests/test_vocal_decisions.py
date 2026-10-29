"""Fail-closed, pure-data checks for sample-accurate selective dubbing decisions."""

from copy import deepcopy

import pytest

from app.vocal_decisions import DecisionValidationError, parse_decision_manifest


SOURCE_SHA = "a" * 64
PCM_SHA = "b" * 64


def speech(start=0, end=48000, segment_id="speech"):
    return {"segment_id": segment_id, "start_sample": start, "end_sample": end,
            "action": "TRANSLATE", "source_language": "de", "source_text": "Jetzt singen wir."}


def preserve(start=48000, end=96000, segment_id="sung-vowel"):
    return {"segment_id": segment_id, "start_sample": start, "end_sample": end,
            "action": "PRESERVE", "reason": "original sung vowel"}


def review(start=48000, end=96000, segment_id="uncertain"):
    return {"segment_id": segment_id, "start_sample": start, "end_sample": end,
            "action": "REVIEW", "reason": "speech and singing overlap"}


def manifest(segments=None, **overrides):
    data = {"schema_version": 1, "source_sha256": SOURCE_SHA,
            "pcm_sha256": PCM_SHA, "sample_rate": 48000, "total_samples": 96000,
            "model_revisions": {"detector": "stub@sha256"},
            "segments": [speech(), preserve()] if segments is None else segments}
    data.update(overrides)
    return data


def invalid(data, needle):
    with pytest.raises(DecisionValidationError, match=needle):
        parse_decision_manifest(data)


def test_adjacent_spans_cover_entire_pcm_without_mutating_input():
    raw = manifest()
    copy = deepcopy(raw)
    result = parse_decision_manifest(raw)
    assert result.sample_rate == 48000
    assert result.total_samples == 96000
    assert result.source_sha256 == SOURCE_SHA
    assert result.pcm_sha256 == PCM_SHA
    assert result.model_revisions == (("detector", "stub@sha256"),)
    assert [(s.action, s.start_sample, s.end_sample) for s in result.spans] == [
        ("TRANSLATE", 0, 48000), ("PRESERVE", 48000, 96000)]
    assert raw == copy


def test_mixed_phrase_flattens_to_leaf_actions():
    first = speech(0, 30000, "start")
    vowel = preserve(30000, 60000, "long-a")
    last = speech(60000, 96000, "finish")
    raw = manifest([{"segment_id": "mixed", "start_sample": 0, "end_sample": 96000,
                     "action": "MIXED", "children": [first, vowel, last]}])
    result = parse_decision_manifest(raw)
    assert [s.segment_id for s in result.spans] == ["start", "long-a", "finish"]
    assert [s.action for s in result.spans] == ["TRANSLATE", "PRESERVE", "TRANSLATE"]


def test_uncertain_segment_keeps_explicit_review_action():
    result = parse_decision_manifest(manifest([speech(), review()]))
    assert result.spans[-1].action == "REVIEW"
    assert result.spans[-1].reason == "speech and singing overlap"


def test_human_override_tracks_previous_model_action():
    voice = preserve()
    voice["human_override"] = {"previous_action": "TRANSLATE", "reason": "manual: sung vowel"}
    result = parse_decision_manifest(manifest([speech(), voice]))
    assert result.spans[-1].human_override.previous_action == "TRANSLATE"


def test_confidence_zero_and_one_are_valid_but_no_infinities():
    a, b = speech(), preserve()
    a["confidence"] = 0
    b["confidence"] = 1.0
    result = parse_decision_manifest(manifest([a, b]))
    assert [s.confidence for s in result.spans] == [0.0, 1.0]


@pytest.mark.parametrize("start,end,needle", [
    (1, 48000, "gap"),
    (0, 48001, "overlap"),
    (0, 0, "invalid"),
    (-1, 48000, "integer"),
    (0.25, 48000, "integer"),
    (False, 48000, "integer"),
    (0, 96001, "out-of-range"),
])
def test_bad_first_interval_fails(start, end, needle):
    invalid(manifest([speech(start, end), preserve()]), needle)


def test_uncovered_tail_fails_instead_of_dropping_audio():
    invalid(manifest([speech(), preserve(48000, 95000)]), "uncovered tail")


def test_uncovered_head_fails_instead_of_dropping_audio():
    invalid(manifest([preserve(500, 96000)]), "gap")


def test_bad_child_partition_does_not_widen_original_vocal():
    raw = manifest([{"segment_id": "mixed", "start_sample": 0, "end_sample": 96000,
                     "action": "MIXED", "children": [speech(0, 30000, "a"),
                                                    preserve(29999, 96000, "b")]}])
    invalid(raw, "overlap")


def test_mixed_requires_at_least_two_children():
    raw = manifest([{"segment_id": "mixed", "start_sample": 0, "end_sample": 96000,
                     "action": "MIXED", "children": [speech(0, 96000)]}])
    invalid(raw, "MIXED needs >= 2")


def test_nested_mixed_rejected_before_audio_mutation():
    raw = manifest([{"segment_id": "outer", "start_sample": 0, "end_sample": 96000,
                     "action": "MIXED", "children": [
                         {"segment_id": "nested", "start_sample": 0,
                          "end_sample": 48000, "action": "MIXED", "children": []},
                         preserve()]}])
    invalid(raw, "nested MIXED")


def test_leaf_cannot_contain_children_even_if_empty():
    b = preserve()
    b["children"] = []
    invalid(manifest([speech(), b]), "leaf actions must not have children")


def test_duplicate_parent_and_leaf_id_rejected():
    raw = manifest([{"segment_id": "dup", "start_sample": 0, "end_sample": 96000,
                     "action": "MIXED", "children": [speech(0, 48000, "dup"), preserve()]}])
    invalid(raw, "duplicate segment_id")


@pytest.mark.parametrize("value,needle", [
    ("DUB", "unknown decision"),
    (None, "unknown decision"),
    (1, "unknown decision"),
])
def test_unknown_action_rejected(value, needle):
    b = preserve()
    b["action"] = value
    invalid(manifest([speech(), b]), needle)


@pytest.mark.parametrize("field,value,needle", [
    ("schema_version", 2, "unsupported schema_version"),
    ("schema_version", True, "unsupported schema_version"),
    ("sample_rate", 0, "integer"),
    ("sample_rate", True, "integer"),
    ("total_samples", 0, "integer"),
    ("source_sha256", "SHA", "SHA-256"),
    ("pcm_sha256", "A" * 64, "SHA-256"),
    ("model_revisions", ["a"], "expected object"),
])
def test_invalid_manifest_metadata_rejected(field, value, needle):
    invalid(manifest(**{field: value}), needle)


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), float("-inf"),
                                         -0.1, 1.1, True, "0.5"])
def test_nonfinite_or_invalid_confidence_rejected(confidence):
    b = preserve()
    b["confidence"] = confidence
    invalid(manifest([speech(), b]), "finite confidence")


def test_translate_requires_actual_text_and_supported_source_language():
    a = speech()
    a["source_text"] = " "
    invalid(manifest([a, preserve()]), "non-empty string")
    a = speech()
    a["source_language"] = "und"
    invalid(manifest([a, preserve()]), "requires DE/EN")


def test_review_without_reason_is_not_a_valid_complete_decision():
    a = review()
    del a["reason"]
    invalid(manifest([speech(), a]), "REVIEW requires a reason")


def test_unknown_fields_fail_closed_instead_of_disappearing():
    data = manifest()
    data["something_else"] = True
    invalid(data, "unknown keys")
    data = manifest()
    data["segments"][0]["translated_text"] = "текст"
    invalid(data, "unknown keys")


def test_human_override_requires_reason_and_different_previous_action():
    b = preserve()
    b["human_override"] = {"previous_action": "PRESERVE", "reason": "same"}
    invalid(manifest([speech(), b]), "different leaf action")
    b["human_override"] = {"previous_action": "TRANSLATE", "reason": " "}
    invalid(manifest([speech(), b]), "non-empty string")


def test_invalid_segments_container_is_rejected():
    invalid(manifest(segments=()), "segment list")
    invalid(manifest(segments=[]), "segment list")


def test_unhashable_override_value_is_rejected_as_contract_error():
    b = preserve()
    b["human_override"] = {"previous_action": [], "reason": "invalid input"}
    invalid(manifest([speech(), b]), "different leaf action")


def test_non_string_json_key_is_rejected():
    data = manifest()
    data[123] = "unexpected"
    invalid(data, "object keys must be strings")


def test_unequal_sample_rate_does_not_require_float_seconds():
    raw = manifest([speech(0, 12345), preserve(12345, 96000)], sample_rate=44100)
    result = parse_decision_manifest(raw)
    assert result.sample_rate == 44100
    assert result.spans[0].end_sample == result.spans[1].start_sample == 12345
