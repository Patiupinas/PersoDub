"""Prepare a read-only stage benchmark from an existing finished PersoDub job.

No source video or user audio is copied. Generated timing files are explicitly
source-derived proxies, not human-gold boundaries. The caller must state the
expected mode: a saved job's actual mode cannot assert user intent.
"""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

from app.qwen_assemble import _voiced_bounds


def _load(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def prepare_case(work_dir: Path, output_dir: Path, expected_mode: str):
    root = Path(work_dir).resolve()
    destination = Path(output_dir).resolve()
    if expected_mode not in ("replace", "overdub"):
        raise ValueError("Expected audio mode must be specified")
    job = _load(root / "job.json")
    if job.get("status") != "done":
        raise ValueError("Only completed jobs can provide benchmark evidence")
    if not (root / "input.mp4").is_file():
        raise ValueError("No local input.mp4 found")
    if not (root / "dubbed.mp4").is_file():
        raise ValueError("No local dubbed.mp4 found")
    case_id = job.get("id") or "local"
    manifest = {
        "schema_version": 1,
        "suite_id": "local-completed-dub-%s" % case_id,
        "cases": [
            {
                "id": "final-media", "stage": "export",
                "oracle_kind": "synthetic_invariant",
                "split": "local_diagnostic",
                "source": str(root / "input.mp4"),
                "candidate": str(root / "dubbed.mp4"),
                "expected_mode": expected_mode,
                "max_duration_drift_s": 0.15,
            },
            {
                "id": "output-audit", "stage": "job_audit",
                "oracle_kind": "source_derived_proxy",
                "split": "local_diagnostic",
                "job_dir": str(root),
                "expected_mode": expected_mode,
            },
        ],
    }
    ref_cues = root / "speakers.json"
    dub_lines = root / "lines.json"
    proxy = None
    if ref_cues.is_file() and dub_lines.is_file():
        source = _load(ref_cues)
        lines = _load(dub_lines).get("lines", [])
        if isinstance(source, list) and len(source) == len(lines) and source:
            orig, produced = [], []
            for i, (cue, line) in enumerate(zip(source, lines)):
                if not isinstance(cue, dict) or not isinstance(line, dict):
                    break
                path = root / ("qwen_line_%d.wav" % i)
                if not path.is_file() or not isinstance(line.get("start"), (int, float)):
                    break
                with wave.open(str(path), "rb") as audio:
                    raw = audio.readframes(audio.getnframes())
                    sw = audio.getsampwidth()
                    ch = audio.getnchannels()
                    rate = audio.getframerate()
                first, last = _voiced_bounds(raw, sw, ch, rate)
                if last <= first:
                    break
                orig.append({"start": cue["start"], "end": cue["end"]})
                onset = float(line["start"])
                produced.append({"start": onset, "end": onset + last - first})
            else:
                proxy = (orig, produced)

    destination.mkdir(parents=True, exist_ok=False)
    if proxy:
        (destination / "source_timing_proxy.json").write_text(
            json.dumps({"utterances": proxy[0]}, indent=2) + "\n"
        )
        (destination / "dub_timing_proxy.json").write_text(
            json.dumps({"utterances": proxy[1]}, indent=2) + "\n"
        )
    manifest["cases"].append({
        "id": "pre-placement-timing-proxy", "stage": "timing",
        "oracle_kind": "source_derived_proxy", "split": "local_diagnostic",
        "reference": "source_timing_proxy.json",
        "candidate": "dub_timing_proxy.json", "optional": True,
    })
    for case_id, stage, gold, pred in [
        ("protected-events", "events", "external_human_events.json",
         "suggested_actions.json"),
        ("source-asr", "asr", "independent_source_transcript.txt",
         "recognized_source.txt"),
        ("ru-tts-readback", "tts_readback", "approved_russian_text.txt",
         "independent_ru_recognition.txt"),
        ("original-mix", "mix", "source_mono_or_stereo.wav",
         "overdub_mixed_same_clock.wav"),
        ("human-panel", "human_review", "independent_ratings.json", None),
    ]:
        entry = {
            "id": case_id, "stage": stage, "oracle_kind": "human_gold",
            "split": "local_diagnostic", "reference": gold,
            "optional": True,
        }
        if pred is not None:
            entry["candidate"] = pred
        if stage == "events":
            entry["duration_s"] = job.get("result", {}).get("duration", 1)
        if stage == "mix":
            entry["events"] = "approved_mix_windows.json"
        manifest["cases"].append(entry)
    result = destination / "manifest.json"
    result.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-mode", choices=("overdub", "replace"), required=True)
    args = parser.parse_args(argv)
    print(prepare_case(args.work_dir, args.output_dir, args.expected_mode))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
