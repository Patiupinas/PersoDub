"""Read-only, source-bound quality audit of a completed local dubbing job.

An MP4 mux succeeding is not proof of audible source material, timing, clear
Russian pronunciation, or speaker identity. This report makes objective
mismatches visible without pretending to grade accent or naturalness.
"""
import argparse
import json
import math
import re
import subprocess
import wave
from pathlib import Path

from app.qwen_assemble import _voiced_bounds
from app.source_transcript_quality import summarize_source_timing

VOICE_REFERENCE_MIN_SECONDS = 2.0
VOICE_REFERENCE_MAX_WORDS_PER_SECOND = 6.0
CUE_OVERRUN_SECONDS = 0.20
MAX_ASR_SCORE_LINES = 100000


def _load(path, default=None):
    try:
        with Path(path).open(encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return default


def _media_streams(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=index,codec_type:stream_tags=title,handler_name:stream_disposition=default",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60, check=True,
    )
    obj = json.loads(result.stdout)
    if type(obj) is not dict or type(obj.get("streams")) is not list:
        raise ValueError("ffprobe returned no audio/video stream inventory")
    return obj["streams"]


def _wav_duration(path):
    with wave.open(str(path), "rb") as wav:
        if wav.getframerate() <= 0:
            raise ValueError("Invalid WAV sample rate")
        return wav.getnframes() / wav.getframerate()


def _voiced_seconds(path):
    """Measure speech-like duration using the renderer's existing VAD envelope."""
    with wave.open(str(path), "rb") as wav:
        n, sr, sw, ch = (
            wav.getnframes(), wav.getframerate(),
            wav.getsampwidth(), wav.getnchannels(),
        )
        # Individual TTS lines are short. These read bounds are only per line,
        # not the complete video, so peak RAM does not scale with video length.
        if n / sr > 180:
            raise ValueError("One synthesized line exceeds 180 seconds")
        data = wav.readframes(n)
    start, end = _voiced_bounds(data, sw, ch, sr)
    return max(0.0, end - start)


def audit_completed(work_dir, expected_mode=None, output_name=None):
    root = Path(work_dir).resolve()
    job = _load(root / "job.json", {})
    if type(job) is not dict:
        raise ValueError("Invalid job manifest")
    if job.get("status") != "done":
        raise ValueError("Only completed dubbing jobs can be audited")
    result = job.get("result") or {}
    if not isinstance(result, dict):
        result = {}
    video = (root / "dubbed.mp4").resolve()
    out_path = result.get("out_path")
    if out_path and Path(out_path).resolve().parent == root:
        video = Path(out_path).resolve()
    if output_name is not None:
        if not isinstance(output_name, str) or not re.fullmatch(
            r"finished-overdub(?:-[0-9]+)?\.mp4", output_name
        ):
            raise ValueError("Invalid reviewed Overdub output name")
        video = (root / output_name).resolve()
    if video.parent != root or not video.is_file():
        raise FileNotFoundError("Finished video missing from the project folder")

    streams = _media_streams(video)
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    declared_mode = result.get("audio_mode") or job.get("audio_mode") or "replace"
    if output_name is not None:
        # A separately reviewed export is not the original job's Replace file.
        # Its actual streams and labels must agree with the Overdub contract.
        declared_mode = "overdub"
    issues = []
    if not video_streams or not audio:
        issues.append({"code": "media_stream_missing"})
    if expected_mode == "overdub" and len(audio) != 2:
        issues.append({
            "code": "source_track_missing",
            "expected_audio_tracks": 2, "actual_audio_tracks": len(audio),
        })
    if output_name is not None and len(audio) == 2:
        names = [stream.get("tags", {}).get("handler_name") for stream in audio]
        defaults = [stream.get("disposition", {}).get("default") for stream in audio]
        if names != ["Overdub", "Original"] or defaults != [1, 0]:
            issues.append({"code": "overdub_stream_metadata_mismatch"})
    if expected_mode and declared_mode != expected_mode:
        issues.append({
            "code": "output_mode_mismatch",
            "expected": expected_mode, "actual": declared_mode,
        })

    refs = _load(root / "speaker_refs.json", {}) or {}
    if not isinstance(refs, dict):
        raise ValueError("Invalid speaker reference manifest")
    ref_quality = {}
    for speaker, metadata in sorted(refs.items()):
        relative = metadata.get("ref_wav")
        if not isinstance(relative, str):
            continue
        path = (root / relative).resolve()
        if path.parent != root or not path.is_file():
            issues.append({"code": "speaker_reference_missing", "speaker": speaker})
            continue
        seconds = _wav_duration(path)
        words = len((metadata.get("ref_text") or "").split())
        words_per_second = words / seconds if seconds else math.inf
        ref_quality[speaker] = {
            "audio_seconds": round(seconds, 3),
            "transcript_words": words,
            "words_per_second": round(words_per_second, 2),
        }
        if seconds < VOICE_REFERENCE_MIN_SECONDS:
            issues.append({
                "code": "speaker_reference_too_short",
                "speaker": speaker, "audio_seconds": round(seconds, 3),
            })
        if words_per_second > VOICE_REFERENCE_MAX_WORDS_PER_SECOND:
            issues.append({
                "code": "speaker_reference_text_mismatch",
                "speaker": speaker, "words_per_second": round(words_per_second, 2),
            })

    source_timing = summarize_source_timing(_load(root / "transcript.json"))
    if source_timing["status"] == "review_required":
        issues.append({
            "code": "source_transcript_timing_review",
            "count": source_timing["review_cue_count"],
            "zero_duration_words": source_timing["zero_duration_words"],
        })

    translated = _load(root / "lines.json", {}) or {}
    speaker_cues = _load(root / "speakers.json", []) or []
    lines = translated.get("lines", []) if isinstance(translated, dict) else []
    duration_issues = []
    if isinstance(lines, list) and isinstance(speaker_cues, list):
        if len(lines) != len(speaker_cues):
            issues.append({
                "code": "source_timeline_unmatched",
                "source_cue_count": len(speaker_cues),
                "translation_line_count": len(lines),
            })
        for index, (entry, cue) in enumerate(zip(lines, speaker_cues)):
            if (
                not isinstance(entry, dict) or not isinstance(cue, dict)
                or type(entry.get("start")) not in (int, float)
                or type(cue.get("start")) not in (int, float)
                or abs(entry["start"] - cue["start"]) > 0.1
            ):
                issues.append({
                    "code": "source_line_timing_unmatched", "line": index + 1,
                })
                continue
            path = root / ("qwen_line_%d.wav" % index)
            if not path.is_file():
                continue
            start = cue.get("start")
            end = cue.get("end")
            if not all(type(x) in (int, float) for x in (start, end)):
                continue
            source_slot = end - start
            if source_slot <= 0:
                continue
            voiced = _voiced_seconds(path)
            overrun = voiced - source_slot
            if overrun > CUE_OVERRUN_SECONDS:
                duration_issues.append({
                    "line": index + 1, "source_slot_seconds": round(source_slot, 3),
                    "dub_voiced_seconds": round(voiced, 3),
                    "excess_seconds": round(overrun, 3),
                })
    if duration_issues:
        issues.append({
            "code": "timing_slot_overruns", "count": len(duration_issues),
            "total_excess_seconds": round(
                sum(row["excess_seconds"] for row in duration_issues), 3,
            ),
        })
    cuts = _load(root / "clipped_lines.json", {}) or {}
    cuts = cuts.get("clipped", []) if isinstance(cuts, dict) else []
    if cuts:
        issues.append({
            "code": "speech_audio_clipped", "count": len(cuts),
            "total_cut_seconds": round(
                sum(float(row.get("cut_s", 0)) for row in cuts), 3,
            ),
        })

    score_data = _load(root / "qwen_scorer_output.json", {}) or {}
    scores = score_data.get("lines", {}) if isinstance(score_data, dict) else {}
    raw_similarity = {}
    if isinstance(scores, dict):
        for key, takes in list(scores.items())[:MAX_ASR_SCORE_LINES]:
            if not isinstance(takes, list):
                continue
            available = [
                take.get("sim") for take in takes
                if isinstance(take, dict)
                and type(take.get("sim")) in (int, float)
                and math.isfinite(take["sim"])
            ]
            if available:
                raw_similarity[key] = round(max(available), 4)

    return {
        "schema_version": 1,
        "status": "review_required" if issues else "not_perceptually_verified",
        "job_id": job.get("id"),
        "output_file": video.name,
        "actual_audio_streams": len(audio),
        "declared_audio_mode": declared_mode,
        "expected_audio_mode": expected_mode,
        "reference_quality": ref_quality,
        "timing_overruns": duration_issues,
        "source_transcript_timing": source_timing,
        "issues": issues,
        "speaker_similarity_model_scores": raw_similarity,
        "human_review_remaining": [
            "Russian accent and pronunciation", "speaker likeness and naturalness",
            "within-utterance pauses", "audible original-to-translation balance",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--expected-mode", choices=("replace", "overdub"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_completed(args.work_dir, args.expected_mode)
    content = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as file:
            file.write(content)
    print(content, end="")


if __name__ == "__main__":
    main()
