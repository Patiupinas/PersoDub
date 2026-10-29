"""Offline RAVDESS archive index, checksum validation and speaker-disjoint splits.

This only indexes file-level speech/song labels from original filenames. It
must NOT be converted directly into selective-dubbing frame-level gold.
No audio extraction, network access, model execution, or changes to datasets.
"""

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path


PUBLISHED_MD5 = {
    "speech": "bc696df654c87fed845eb13823edef8a",
    "song": "5411230427d67a21e18aa4d466e6d1b9",
}
EXPECTED_COUNTS = {"speech": 1440, "song": 1012}
ARCHIVE_LINKS = {
    "speech": "https://zenodo.org/api/records/1188976/files/Audio_Speech_Actors_01-24.zip/content",
    "song": "https://zenodo.org/api/records/1188976/files/Audio_Song_Actors_01-24.zip/content",
}
LICENSE = "CC BY-NC-SA 4.0"
FILENAME = re.compile(r"(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})\.wav\Z", re.I)
ACTOR = re.compile(r"Actor_(\d{2})\Z", re.I)
# Predeclare the partition to avoid outcome-driven cherry-picking of speakers.
SPLITS = {"train": range(1, 17), "dev": range(17, 21), "test": range(21, 25)}


class RavdessIndexError(ValueError):
    """A ZIP or its metadata is not safe for a reproducible benchmark."""


def _digests(path):
    sha = hashlib.sha256()
    md5 = hashlib.md5()  # noqa: S324 - comparison with published file checksum only
    with open(path, "rb") as archive:
        for chunk in iter(lambda: archive.read(1024 * 1024), b""):
            sha.update(chunk)
            md5.update(chunk)
    return sha.hexdigest(), md5.hexdigest()


def _split(actor):
    for name, ids in SPLITS.items():
        if actor in ids:
            return name
    raise RavdessIndexError(f"out-of-range actor {actor}")


def _member(name, archive_kind, size):
    """Validate RAVDESS 7-field recording ID and its optional Actor folder."""
    if "\\" in name or name.startswith("/"):
        raise RavdessIndexError(f"unsafe ZIP member path: {name!r}")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise RavdessIndexError(f"unsafe ZIP member path: {name!r}")
    if not name.lower().endswith(".wav"):
        return None
    if len(parts) < 2 or len(parts) > 3:
        raise RavdessIndexError(f"unexpected WAV ZIP hierarchy: {name!r}")
    folder = ACTOR.fullmatch(parts[-2])
    match = FILENAME.fullmatch(parts[-1])
    if folder is None or match is None:
        raise RavdessIndexError(f"unexpected RAVDESS WAV name: {name!r}")
    modality, channel, emotion, intensity, statement, repetition, actor = map(int, match.groups())
    required_channel = 1 if archive_kind == "speech" else 2
    if modality != 3 or channel != required_channel:
        raise RavdessIndexError(f"wrong modality or vocal channel: {name!r}")
    if not (1 <= actor <= 24 and int(folder.group(1)) == actor):
        raise RavdessIndexError(f"actor ID mismatch: {name!r}")
    if emotion not in range(1, 9) or intensity not in (1, 2):
        raise RavdessIndexError(f"invalid emotion/intensity: {name!r}")
    if emotion == 1 and intensity != 1:
        raise RavdessIndexError(f"neutral RAVDESS emotion cannot be strong: {name!r}")
    if archive_kind == "song" and emotion in (7, 8):
        raise RavdessIndexError(f"song cannot be disgust/surprised: {name!r}")
    if statement not in (1, 2) or repetition not in (1, 2):
        raise RavdessIndexError(f"invalid statement/repetition: {name!r}")
    if size <= 0:
        raise RavdessIndexError(f"empty WAV file: {name!r}")
    return {
        "archive": archive_kind,
        "member": name,
        "label": archive_kind,
        "actor_id": actor,
        "speaker_id": f"actor-{actor:02d}",
        "split": _split(actor),
        "emotion_code": emotion,
        "intensity_code": intensity,
        "statement_code": statement,
        "repetition_code": repetition,
        "compressed_member": False,
        "uncompressed_size_bytes": size,
    }


def _archive(path, kind, expected_md5):
    if not path.is_file():
        raise RavdessIndexError(f"{kind}: ZIP not found: {path}")
    sha, md5 = _digests(path)
    if md5.lower() != expected_md5.lower():
        raise RavdessIndexError(f"{kind}: published ZIP MD5 mismatch: {md5}")
    records = []
    seen = set()
    with zipfile.ZipFile(path, "r") as data:
        if len(data.infolist()) > 15000:
            raise RavdessIndexError(f"{kind}: suspiciously large ZIP directory")
        for entry in data.infolist():
            if entry.is_dir():
                continue
            info = _member(entry.filename, kind, entry.file_size)
            if info is None:
                continue
            identity = entry.filename.lower()
            if identity in seen:
                raise RavdessIndexError(f"{kind}: duplicate WAV ZIP member: {entry.filename}")
            seen.add(identity)
            info["compressed_member"] = entry.compress_type != zipfile.ZIP_STORED
            info["zip_crc32"] = f"{entry.CRC:08x}"
            records.append(info)
    records.sort(key=lambda item: item["member"])
    return {"name": path.name, "url": ARCHIVE_LINKS[kind], "md5": md5, "sha256": sha,
            "size_bytes": path.stat().st_size, "wav_count": len(records)}, records


def index_ravdess(speech_zip, song_zip, *, expected_md5=None, expected_counts=None):
    """Index two already-downloaded public ZIPs without unpacking their audio.

    Override checksum/count expectations only in synthetic unit tests. The CLI
    uses the fixed official Zenodo 2018 checksums and archive file counts.
    """
    checksums = PUBLISHED_MD5 if expected_md5 is None else expected_md5
    counts = EXPECTED_COUNTS if expected_counts is None else expected_counts
    archives = {}
    rows = []
    for kind, path in (("speech", Path(speech_zip)), ("song", Path(song_zip))):
        archive, records = _archive(path, kind, checksums[kind])
        if len(records) != counts[kind]:
            raise RavdessIndexError(f"{kind}: expected {counts[kind]} WAVs, found {len(records)}")
        archives[kind] = archive
        rows.extend(records)
    speakers = {split: sorted({r["speaker_id"] for r in rows if r["split"] == split})
                for split in SPLITS}
    if len(set(sum(speakers.values(), []))) != sum(map(len, speakers.values())):
        raise RavdessIndexError("actor leakage across train/dev/test")
    distribution = {split: {kind: sum(r["split"] == split and r["label"] == kind for r in rows)
                            for kind in ("speech", "song")} for split in SPLITS}
    return {
        "schema_version": 1,
        "dataset": "RAVDESS",
        "label_granularity": "whole-file speech/song ONLY, not PCM-frame decisions",
        "license": LICENSE,
        "reference": "https://zenodo.org/records/1188976",
        "archives": archives,
        "splits": speakers,
        "counts": distribution,
        "records": sorted(rows, key=lambda item: (item["speaker_id"], item["archive"], item["member"])),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Index publicly downloadable RAVDESS ZIPs offline")
    parser.add_argument("--speech", type=Path, required=True, help="Public Audio_Speech ZIP")
    parser.add_argument("--song", type=Path, required=True, help="Public Audio_Song ZIP")
    parser.add_argument("--output", type=Path, required=True, help="New JSON manifest path")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.exit(2, f"RAVDESS index failed: output already exists: {args.output}\n")
    try:
        result = index_ravdess(args.speech, args.song)
        with args.output.open("x", encoding="utf-8") as target:
            json.dump(result, target, ensure_ascii=False, sort_keys=True, indent=2)
            target.write("\n")
    except (OSError, RavdessIndexError, zipfile.BadZipFile) as exc:
        parser.exit(2, f"RAVDESS index failed: {exc}\n")
    print(json.dumps({"manifest": str(args.output), "counts": result["counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
