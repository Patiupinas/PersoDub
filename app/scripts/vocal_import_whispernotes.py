"""Import existing WhisperNotes session JSON as a PersoDub observation artifact."""

import argparse
import json
import os
import tempfile
from pathlib import Path

from app.vocal_whispernotes import import_session


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--pcm-sha256", required=True)
    parser.add_argument("--sample-rate", type=int, required=True)
    parser.add_argument("--total-samples", type=int, required=True)
    parser.add_argument("--time-domain", choices=("original", "compact"), required=True)
    parser.add_argument("--compact-map", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    opts = parser.parse_args(argv)

    def read_json(path):
        with path.open(encoding="utf-8") as source:
            return json.load(source)

    session = opts.session
    final = read_json(session / "session.final_transcript.json")
    phrases = read_json(session / "session.phrases.json")
    candidates_path = session / "session.asr_candidates.json"
    candidates = read_json(candidates_path) if candidates_path.exists() else None
    compact_map = read_json(opts.compact_map) if opts.compact_map else None
    result = import_session(final, phrases, candidates,
                            pcm_sha256=opts.pcm_sha256,
                            sample_rate=opts.sample_rate,
                            total_samples=opts.total_samples,
                            time_domain=opts.time_domain,
                            compact_map=compact_map)

    opts.output.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=opts.output.parent,
                                         prefix=".whispernotes-", suffix=".tmp", delete=False) as stream:
            temp = Path(stream.name)
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, opts.output)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
