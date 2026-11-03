"""One Russian dubbing voice per verified source-speaker cluster group."""
import pytest

from app.speaker_voice_plan import apply_voice_groups, build_voice_plan


def cues():
    return [
        {"start": 0, "end": 3, "speaker_id": "SPK9", "text": "intro"},
        {"start": 3, "end": 6, "speaker_id": "SPK1", "text": "other"},
        {"start": 7, "end": 10, "speaker_id": "SPK9", "text": "return"},
        {"start": 11, "end": 14, "speaker_id": "SPK2", "text": "another"},
    ]


def pair(a, b, score):
    return {"a": a, "b": b, "similarity": score, "metric": "camplus_cosine"}


def test_eighty_percent_joins_only_dub_voice_without_changing_source_speakers():
    source = cues()
    plan = build_voice_plan(source, [pair("SPK1", "SPK9", 0.80)])
    result = apply_voice_groups(source, plan)
    assert plan["speaker_to_group"]["SPK1"] == plan["speaker_to_group"]["SPK9"]
    assert plan["speaker_to_group"]["SPK2"] != plan["speaker_to_group"]["SPK9"]
    assert result[0]["voice_group_id"] == result[1]["voice_group_id"]
    assert [c["speaker_id"] for c in result] == [c["speaker_id"] for c in source]
    assert all("voice_group_id" not in item for item in source)
    assert len(plan["merges"]) == 1


def test_seventy_nine_percent_keeps_distinct_voices():
    plan = build_voice_plan(cues(), [pair("SPK1", "SPK9", 0.7999)])
    assert plan["speaker_to_group"]["SPK1"] != plan["speaker_to_group"]["SPK9"]


def test_prevents_transitive_false_merge_without_all_pair_evidence():
    # A-B and B-C are close, but A-C is quite different.
    base = [
        {"start": n * 4, "end": n * 4 + 3, "speaker_id": speaker}
        for n, speaker in enumerate(("A", "B", "C"))
    ]
    result = build_voice_plan(base, [pair("A", "B", 0.89), pair("B", "C", 0.83), pair("A", "C", 0.2)])
    assert result["speaker_to_group"]["A"] == result["speaker_to_group"]["B"]
    assert result["speaker_to_group"]["A"] != result["speaker_to_group"]["C"]


def test_long_lecture_reappearance_has_same_voice_and_groups_follow_first_appearance():
    ordered = cues() + [
        {"start": 3700, "end": 3710, "speaker_id": "SPK1"},
        {"start": 7300, "end": 7310, "speaker_id": "SPK9"},
    ]
    plan = build_voice_plan(ordered, [pair("SPK1", "SPK9", 0.84)])
    a = apply_voice_groups(ordered, plan)
    assert a[0]["voice_group_id"] == a[1]["voice_group_id"] == a[-2]["voice_group_id"] == a[-1]["voice_group_id"]
    assert plan["groups"][0]["members"] == ["SPK9", "SPK1"]


def test_unverifiable_similarity_is_not_a_probability():
    base = cues()
    with pytest.raises(ValueError, match="metric"):
        build_voice_plan(base, [{"a": "SPK1", "b": "SPK9", "similarity": 0.94, "metric": "probability"}])
    with pytest.raises(ValueError, match="unknown"):
        build_voice_plan(base, [pair("SPK1", "UNRECOGNIZED", 0.9)])


def test_explicit_distinct_override_blocks_merging():
    plan = build_voice_plan(cues(), [pair("SPK1", "SPK9", 0.99)],
                            keep_distinct=[["SPK1", "SPK9"]])
    assert plan["speaker_to_group"]["SPK1"] != plan["speaker_to_group"]["SPK9"]


def test_same_source_different_diarization_invalidates_voice_plan():
    source = cues()
    plan = build_voice_plan(source, [pair("SPK1", "SPK9", 0.88)])
    rewritten = [dict(item) for item in source]
    rewritten[0]["speaker_id"] = "SPK7"
    with pytest.raises(ValueError, match="source"):
        apply_voice_groups(rewritten, plan)


def test_order_independent_pair_scores_and_no_phantom_speakers():
    source = cues()
    a = build_voice_plan(source, [pair("SPK9", "SPK1", .83), pair("SPK1", "SPK2", .4)])
    b = build_voice_plan(source, [pair("SPK2", "SPK1", .4), pair("SPK1", "SPK9", .83)])
    assert a == b
    assert set(a["speaker_to_group"]) == {"SPK9", "SPK1", "SPK2"}


def test_preserves_single_narrator_and_unknown_cues():
    source = [{"start": 0, "end": 2, "text": "narrator", "speaker_id": "A"},
              {"start": 2, "end": 3, "text": "silence"}]
    plan = build_voice_plan(source, [])
    changed = apply_voice_groups(source, plan)
    assert changed[0]["voice_group_id"] == "VOICE_01"
    assert "voice_group_id" not in changed[1]
