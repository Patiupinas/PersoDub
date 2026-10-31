"""Retrieve only pinned benchmark audio, keeping each file outside Git."""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

from app.vocal_audio_tag_benchmark import _validate_sources


def local_basename(source_id):
    """Avoid collisions between NUS read/01.wav and sing/01.wav."""
    return hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:24]


def fetch(url, size, sha, path):
    if path.exists():
        content = path.read_bytes()
        if len(content) != size or hashlib.sha256(content).hexdigest() != sha:
            raise ValueError("existing file has wrong hash or size: " + str(path))
        return "verified_existing"
    if not url.startswith("https://") or not 0 < size < 20_000_000:
        raise ValueError("unexpected source URL or file size")
    request = urllib.request.Request(
        url, headers={"User-Agent": "PersoDub-selected-audio-benchmark/1.0"}
    )
    with urllib.request.urlopen(request, timeout=50) as response:
        data = response.read(size + 1)
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
        raise ValueError("publisher asset differs from frozen source")
    with path.open("xb") as output:
        output.write(data)
    return "downloaded"


def collect(manifest_path, output, selected=None, dry_run=False):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    sources = _validate_sources(manifest)
    wanted = set(selected) if selected else set(sources)
    if not wanted <= set(sources):
        raise ValueError("source-id is not in the frozen benchmark")
    dest = Path(output)
    if not dry_run:
        dest.mkdir(parents=True, exist_ok=True)
        if (dest / "source-index.json").exists():
            raise ValueError("choose a fresh output directory for this run")
    index = {}
    for source_id, meta in sources.items():
        if source_id not in wanted:
            continue
        stem = local_basename(source_id)
        wav = dest / (stem + ".wav")
        status = "planned" if dry_run else fetch(
            meta["url"], meta["wav_bytes"], meta["wav_sha256"], wav
        )
        entry = {
            "source_id": source_id, "wav_name": wav.name,
            "wav_sha256": meta["wav_sha256"], "status": status,
        }
        if "annotation_url" in meta:
            txt = dest / (stem + ".txt")
            if not dry_run:
                if meta["annotation_bytes"] > 150_000:
                    raise ValueError("publisher NUS alignment too large")
                fetch(meta["annotation_url"], meta["annotation_bytes"],
                      meta["annotation_sha256"], txt)
            entry["publisher_alignment_name"] = txt.name
            entry["publisher_alignment_sha256"] = meta["annotation_sha256"]
        index[source_id] = entry
    if not dry_run:
        (dest / "source-index.json").write_text(
            json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description="Download selected original WAVs only")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--source-id", action="append")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        records = collect(args.manifest, args.out, args.source_id, args.dry_run)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"source collection rejected: {exc}\n")
    print(json.dumps({"selected_files": len(records), "dry_run": args.dry_run}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
