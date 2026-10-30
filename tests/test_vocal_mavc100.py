"""Parser-only tests; no acoustic models or MAVC100 media files are needed."""

import hashlib
from pathlib import Path

import pytest

from app.vocal_mavc100 import MAVCAnnotationError, audit_mavc_directory, parse_mavc_csv

HEAD = "Name\tStart\tDuration\tTime Format\tType\tDescription\r\n"


def raw(*rows, bom=True):
    text = HEAD + "".join(f"{code}\t0:{stamp}\t0:00.000\tdecimal\tCue\t\r\n" for code, stamp in rows)
    return text.encode("utf-8-sig" if bom else "utf-8")


def test_exact_published_tsv_format_bom_crlf_sha_and_source_grouping():
    data = raw(
        ("1s", "00.000"), ("1e", "01.230"),
        ("2s", "01.231"), ("2e", "02.450"),
        ("1s", "02.451"), ("1e", "03.500"),
    )
    clip = parse_mavc_csv(data, filename="Person_Session_5.csv")
    assert (clip.clip_id, clip.source_id) == ("Person_Session_5", "Person_Session")
    assert clip.annotation_sha256 == hashlib.sha256(data).hexdigest()
    assert [(e.kind, e.start_ms, e.end_ms) for e in clip.events] == [
        ("speech", 0, 1230),
        ("singing", 1231, 2450),
        ("speech", 2451, 3500),
    ]


def test_silence_is_not_an_action_or_dubbing_permission():
    clip = parse_mavc_csv(raw(("3s", "00.000"), ("3e", "00.053")), filename="A_1.csv")
    assert [e.kind for e in clip.events] == ["silence"]
    assert all(not hasattr(e, "action") for e in clip.events)


def test_empty_event_is_not_guessed_as_a_duration():
    clip = parse_mavc_csv(raw(("1s", "01.000"), ("1e", "01.000")), filename="A_1.csv")
    assert clip.events == ()


@pytest.mark.parametrize(
    "rows,reason",
    [
        ([("1e", "01.000")], "unmatched"),
        ([("1s", "00.000"), ("1s", "01.000")], "repeated"),
        ([("1s", "00.000")], "unclosed"),
        ([("1s", "02.000"), ("1e", "01.000")], "reversed"),
        ([("1s", "00.000"), ("2s", "01.000"),
          ("1e", "03.000"), ("2e", "04.000")], "overlapping"),
    ],
)
def test_broken_marker_sequences_are_rejected(rows, reason):
    with pytest.raises(MAVCAnnotationError, match=reason):
        parse_mavc_csv(raw(*rows), filename="A_1.csv")


@pytest.mark.parametrize("stamp", ["-1.000", "60.000", "00.0001", "nan", "inf", "bad"])
def test_non_millisecond_or_nonfinite_timestamps_are_rejected(stamp):
    with pytest.raises(MAVCAnnotationError):
        parse_mavc_csv(raw(("2s", stamp), ("2e", "20.000")), filename="A_1.csv")


def test_invalid_columns_and_utf8_are_rejected():
    for value in (b"garbage", b"\xff\xfe", b"Name\tStart\n1s\t0:00.000\n"):
        with pytest.raises(MAVCAnnotationError):
            parse_mavc_csv(value, filename="A_1.csv")


@pytest.mark.parametrize("name", ["bad.csv", "other.txt", "_0.csv", "A_x.csv", "a.CSV"])
def test_noncanonical_filename_is_rejected(name):
    with pytest.raises(MAVCAnnotationError):
        parse_mavc_csv(raw(("1s", "00.000"), ("1e", "01.000")), filename=name)


def test_source_disjoint_selection_and_invalid_file_reporting(tmp_path: Path):
    fixture = raw(
        ("1s", "00.000"), ("1e", "01.000"), ("2s", "01.001"),
        ("2e", "02.500"), ("1s", "02.501"), ("1e", "03.500"),
    )
    for name in ("A_0.csv", "A_1.csv", "B_4.csv", "C_1.csv"):
        (tmp_path / name).write_bytes(fixture)
    (tmp_path / "D_0.csv").write_bytes(raw(("3e", "00.000")))
    report = audit_mavc_directory(tmp_path, limit=3)
    assert report["total_label_files"] == 5
    assert report["valid_label_files"] == 4
    assert report["mixed_speech_singing_files"] == 4
    assert len(report["invalid_label_files"]) == 1
    assert [entry["source_id"] for entry in report["selected"]] == ["A", "B", "C"]
    assert report["selected"][0]["speech_singing_speech_patterns"] == 1


def test_large_gap_does_not_count_as_adjacent_transition(tmp_path: Path):
    (tmp_path / "A_1.csv").write_bytes(raw(
        ("1s", "00.000"), ("1e", "01.000"),
        ("2s", "05.000"), ("2e", "08.000"),
        ("1s", "08.001"), ("1e", "10.000"),
    ))
    result = audit_mavc_directory(tmp_path, max_gap_ms=3000)
    assert result["speech_singing_speech_files"] == 0
    assert result["selected"] == []


def test_subhalfsecond_events_do_not_count_as_vocal_transitions(tmp_path: Path):
    (tmp_path / "A_1.csv").write_bytes(raw(
        ("1s", "00.000"), ("1e", "00.300"),
        ("2s", "00.301"), ("2e", "01.500"),
        ("1s", "01.501"), ("1e", "02.500"),
    ))
    assert audit_mavc_directory(tmp_path)["selected"] == []


@pytest.mark.parametrize(
    "kwargs",
    [{"limit": 0}, {"limit": True}, {"max_gap_ms": -1},
     {"min_event_ms": -1}, {"min_event_ms": 1.5}],
)
def test_invalid_selection_configuration(tmp_path: Path, kwargs):
    (tmp_path / "A_1.csv").write_bytes(raw(("1s", "00.000"), ("1e", "01.000")))
    with pytest.raises(MAVCAnnotationError):
        audit_mavc_directory(tmp_path, **kwargs)


def test_no_csv_is_an_error_instead_of_an_empty_gold_dataset(tmp_path: Path):
    with pytest.raises(MAVCAnnotationError, match="no CSV"):
        audit_mavc_directory(tmp_path)


def test_cli_outputs_only_annotation_metadata(tmp_path: Path):
    from app.vocal_mavc100 import main

    (tmp_path / "labels").mkdir()
    (tmp_path / "labels" / "A_0.csv").write_bytes(raw(
        ("1s", "00.000"), ("1e", "01.000"),
        ("2s", "01.001"), ("2e", "02.000"),
        ("1s", "02.001"), ("1e", "03.000"),
    ))
    dest = tmp_path / "audit.json"
    assert main(["--labels", str(tmp_path / "labels"), "--output", str(dest)]) == 0
    assert '"speech_singing_speech_files": 1' in dest.read_text()
    with pytest.raises(MAVCAnnotationError, match="already exists"):
        main(["--labels", str(tmp_path / "labels"), "--output", str(dest)])


def test_published_trailing_whitespace_marker_preserves_original_annotation_hash():
    source = raw(("2s ", "00.000"), ("2e", "01.000"), ("3s", "01.001"), ("3e", "01.020"))
    clip = parse_mavc_csv(source, filename="Singer_9.csv")
    assert [(event.kind, event.start_ms) for event in clip.events] == [
        ("singing", 0), ("silence", 1001),
    ]
    assert clip.annotation_sha256 == hashlib.sha256(source).hexdigest()


def test_explicit_selected_clip_ids_preserve_requested_order(tmp_path: Path):
    example = raw(
        ("1s", "00.000"), ("1e", "01.000"),
        ("2s", "01.001"), ("2e", "02.000"),
        ("1s", "02.001"), ("1e", "03.000"),
    )
    for name in ("English_A_3.csv", "English_B_4.csv", "English_C_5.csv"):
        (tmp_path / name).write_bytes(example)
    result = audit_mavc_directory(
        tmp_path,
        limit=2,
        selected_clip_ids=("English_C_5", "English_A_3"),
    )
    assert [item["clip_id"] for item in result["selected"]] == ["English_C_5", "English_A_3"]


def test_explicit_select_rejects_source_leakage(tmp_path: Path):
    fixture = raw(
        ("1s", "00.000"), ("1e", "01.000"),
        ("2s", "01.001"), ("2e", "02.000"),
        ("1s", "02.001"), ("1e", "03.000"),
    )
    (tmp_path / "Artist_Song_1.csv").write_bytes(fixture)
    (tmp_path / "Artist_Song_2.csv").write_bytes(fixture)
    with pytest.raises(MAVCAnnotationError, match="reuse"):
        audit_mavc_directory(
            tmp_path, limit=2,
            selected_clip_ids=("Artist_Song_1", "Artist_Song_2"),
        )


@pytest.mark.parametrize("requested", [
    ("Unknown_0",),
    ("A_0", "A_0"),
    (),
    ("A_0", 4),
])
def test_invalid_explicit_selection_is_rejected(tmp_path: Path, requested):
    (tmp_path / "A_0.csv").write_bytes(raw(
        ("1s", "00.000"), ("1e", "01.000"),
        ("2s", "01.001"), ("2e", "02.000"),
        ("1s", "02.001"), ("1e", "03.000"),
    ))
    with pytest.raises(MAVCAnnotationError):
        audit_mavc_directory(tmp_path, limit=2, selected_clip_ids=requested)
