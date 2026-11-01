"""Paired blinded listening scoring with honest non-gold status."""
import csv
import json

import pytest

from benchmarks.persodub.blind_review_score import summarize
from benchmarks.persodub.review_page import RATING_COLUMNS


def key_file(tmp_path, profile="voice"):
    key = tmp_path / "key.json"
    key.write_text(json.dumps({
        "schema_version": 1, "suite_id": "one-speaker-three-clips",
        "rating_profile": profile,
        "pairs": [
            {"id": "x1", "A": "baseline", "B": "candidate",
             "comparison": "old-vs-clean"},
            {"id": "x2", "A": "candidate", "B": "baseline",
             "comparison": "clean-vs-icl"},
        ],
    }))
    return key


def ratings(tmp_path, name, *, native="yes", changed=None, profile="voice"):
    rows = []
    for pair_id in ("x1", "x2"):
        row = dict.fromkeys(RATING_COLUMNS, "")
        row.update(
            rater_id=name, native_ru_self_reported=native, pair_id=pair_id,
            A_file=pair_id + "/A.wav", B_file=pair_id + "/B.wav",
            source_file=pair_id + "/source.wav",
            A_accent_1to5="2" if pair_id == "x1" else "5",
            B_accent_1to5="4" if pair_id == "x1" else "1",
            A_voice_1to5="2" if pair_id == "x1" else "5",
            B_voice_1to5="4" if pair_id == "x1" else "1",
            A_pauses_1to5="2" if pair_id == "x1" else "5",
            B_pauses_1to5="4" if pair_id == "x1" else "1",
            A_original_audibility_1to5=("N/A" if profile == "voice" else "2"),
            B_original_audibility_1to5=("N/A" if profile == "voice" else "4"),
            preference_A_B_tie=("B" if pair_id == "x1" else "A"),
        )
        if changed:
            row.update(changed)
        rows.append(row)
    path = tmp_path / (name + ".csv")
    with path.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=RATING_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_unrated_pack_is_not_reported_as_human_acceptance(tmp_path):
    report = summarize(key_file(tmp_path), [])
    assert report["status"] == "NOT_RUN"
    assert report["human_quality_acceptance"] is False
    assert report["groups"] == {}


def test_one_rater_is_incomplete_and_orientation_is_unblinded_only_in_result(tmp_path):
    key = key_file(tmp_path)
    report = summarize(key, [ratings(tmp_path, "ru1")])
    assert report["status"] == "INCOMPLETE_REVIEW_PANEL"
    assert report["native_ru_self_reported_raters"] == 1
    first = report["groups"]["old-vs-clean"]
    second = report["groups"]["clean-vs-icl"]
    assert first["dimensions"]["accent_1to5"]["candidate_minus_baseline"] == 2
    assert second["dimensions"]["accent_1to5"]["candidate_minus_baseline"] == 4
    assert first["preferences"] == {"baseline": 0, "candidate": 1, "tie": 0}
    assert second["preferences"] == {"baseline": 0, "candidate": 1, "tie": 0}
    assert first["dimensions"]["original_audibility_1to5"] == {
        "status": "NOT_APPLICABLE"
    }
    assert report["independent_native_russian_identity_verified"] is False


def test_three_native_self_reports_remain_observed_not_pass(tmp_path):
    key = key_file(tmp_path)
    files = [ratings(tmp_path, f"ru{i}") for i in range(3)]
    report = summarize(key, files)
    assert report["status"] == "OBSERVED_HUMAN_RATINGS"
    assert report["rater_count"] == 3
    assert report["native_ru_self_reported_raters"] == 3
    assert report["human_quality_acceptance"] is False
    assert report["generalization_across_speakers_or_videos"] is False
    assert report["groups"]["old-vs-clean"]["case_ratings"] == 3
    assert report["groups"]["clean-vs-icl"]["case_ratings"] == 3


@pytest.mark.parametrize("broken", [
    {"A_file": "../../different.wav"},
    {"A_accent_1to5": "0"},
    {"B_voice_1to5": "NA"},
    {"preference_A_B_tie": ""},
    {"A_original_audibility_1to5": "5"},
])
def test_malformed_or_inapplicable_scoring_is_rejected(tmp_path, broken):
    key = key_file(tmp_path)
    with pytest.raises(ValueError):
        summarize(key, [ratings(tmp_path, "bad", changed=broken)])


def test_duplicate_rater_id_is_not_counted_as_independent(tmp_path):
    key = key_file(tmp_path)
    first = ratings(tmp_path, "ru1")
    with pytest.raises(ValueError, match="Duplicate"):
        summarize(key, [first, first])


def test_explicit_non_native_rater_does_not_satisfy_native_panel(tmp_path):
    key = key_file(tmp_path)
    files = [ratings(tmp_path, "ru1"), ratings(tmp_path, "ru2"),
             ratings(tmp_path, "other", native="no")]
    report = summarize(key, files)
    assert report["status"] == "INCOMPLETE_REVIEW_PANEL"
    assert report["native_ru_self_reported_raters"] == 2
    assert report["excluded_non_native_raters"] == 1
    assert report["groups"]["old-vs-clean"]["case_ratings"] == 2
    assert report["groups"]["clean-vs-icl"]["case_ratings"] == 2


def test_overdub_profile_requires_actual_original_audibility_scores(tmp_path):
    key = key_file(tmp_path, profile="overdub")
    good = ratings(tmp_path, "r1", profile="overdub")
    report = summarize(key, [good])
    assert report["groups"]["old-vs-clean"]["dimensions"][
        "original_audibility_1to5"]["candidate_minus_baseline"] == 2
    bad = ratings(tmp_path, "r2", profile="voice")
    with pytest.raises(ValueError):
        summarize(key, [bad])
