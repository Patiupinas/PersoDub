"""Read-only conversion of WhisperNotes session artifacts to source-PCM spans.

This adapter does not run ASR, diarization, or vocal-event classification.
"""

import re
from decimal import ROUND_HALF_UP, Decimal

SCHEMA_VERSION = 1
_LANGUAGE_CODES = {"en", "de", "es", "ru", "und"}
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")


def _seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("Timestamp must be a finite number")
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError("Timestamp must be a finite number") from exc
    if not result.is_finite():
        raise ValueError("Timestamp must be a finite number")
    return result


def _sample(seconds, sample_rate):
    return int((seconds * sample_rate).to_integral_value(rounding=ROUND_HALF_UP))


def _locale(value):
    if not isinstance(value, str):
        raise ValueError("selectedLocale must be a string")
    code = value.split("-")[0].split("_")[0].lower()
    return code if code in _LANGUAGE_CODES else "und"


def _regions(compact_map):
    if not isinstance(compact_map, dict) or not isinstance(compact_map.get("regions"), list):
        raise ValueError("compact mode requires a WhisperNotes compact map")
    regions = []
    for region in compact_map["regions"]:
        a, b = _seconds(region["compactStart"]), _seconds(region["compactEnd"])
        x, y = _seconds(region["originalStart"]), _seconds(region["originalEnd"])
        if a < 0 or b <= a or x < 0 or y <= x or abs((b - a) - (y - x)) > Decimal("0.002"):
            raise ValueError("Invalid compact map region")
        if regions and (a < regions[-1][1] or x < regions[-1][3]):
            raise ValueError("Compact map regions must be ordered")
        regions.append((a, b, x, y))
    if not regions:
        raise ValueError("Empty compact map")
    return regions


def _to_original(start, end, regions):
    if start < 0 or end <= start:
        raise ValueError("Invalid phrase/word interval")
    if regions is None:
        return start, end
    for compact_start, compact_end, original_start, _ in regions:
        # Both endpoints must be inside one continuous region. A compacted
        # interval crossing a removed gap cannot be mapped to a continuous cue.
        if compact_start <= start < compact_end and end <= compact_end:
            offset = original_start - compact_start
            return start + offset, end + offset
    raise ValueError("Interval crosses a removed compact-audio region")


def import_session(final_transcript, phrases, asr_candidates, *, pcm_sha256,
                   sample_rate, total_samples, time_domain, compact_map=None):
    """Normalize existing WhisperNotes JSON artifacts without modifying them.

    Candidate word times are phrase-relative, according to PhraseASRCandidate.
    The caller must explicitly state if its artifacts are in original or
    compact time; automatically remapping already-original times is incorrect.
    """
    if not isinstance(pcm_sha256, str) or not _SHA256.fullmatch(pcm_sha256):
        raise ValueError("pcm_sha256 must be a SHA-256 hex digest")
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("Invalid sample_rate")
    if isinstance(total_samples, bool) or not isinstance(total_samples, int) or total_samples <= 0:
        raise ValueError("Invalid total_samples")
    if time_domain not in ("original", "compact"):
        raise ValueError("time_domain must be explicitly original or compact")
    if time_domain == "original" and compact_map is not None:
        raise ValueError("Do not remap artifacts already on the original timeline")
    regions = _regions(compact_map) if time_domain == "compact" else None
    if not isinstance(final_transcript, dict) or not isinstance(final_transcript.get("segments"), list):
        raise ValueError("Missing final transcript segments")
    if not isinstance(phrases, dict) or not isinstance(phrases.get("phrases"), list):
        raise ValueError("Missing session phrases with stable speaker IDs")
    if asr_candidates is not None and (not isinstance(asr_candidates, dict)
                                       or not isinstance(asr_candidates.get("candidates"), list)):
        raise ValueError("Invalid ASR candidates")

    by_phrase = {}
    for phrase in phrases["phrases"]:
        pid, speaker = phrase.get("phraseID"), phrase.get("speaker")
        if not isinstance(pid, str) or not pid or pid in by_phrase or not isinstance(speaker, str) or not speaker:
            raise ValueError("Missing, duplicate, or invalid phrase/speaker ID")
        by_phrase[pid] = phrase
    by_candidate = {}
    for candidate in (asr_candidates or {}).get("candidates", []):
        cid = candidate.get("candidateID")
        if not isinstance(cid, str) or not cid or cid in by_candidate:
            raise ValueError("Invalid or duplicate ASR candidate ID")
        by_candidate[cid] = candidate

    seen = set()
    output = []
    for segment in final_transcript["segments"]:
        pid = segment.get("phraseID")
        if not isinstance(pid, str) or pid not in by_phrase or pid in seen:
            raise ValueError("Final segment missing matching unique phraseID")
        seen.add(pid)
        phrase = by_phrase[pid]
        start, end = _seconds(segment["start"]), _seconds(segment["end"])
        pstart, pend = _seconds(phrase["start"]), _seconds(phrase["end"])
        if start != pstart or end != pend:
            raise ValueError("Final transcript and source phrase disagree on time bounds")
        original_start, original_end = _to_original(start, end, regions)
        lo, hi = _sample(original_start, sample_rate), _sample(original_end, sample_rate)
        if lo < 0 or hi > total_samples or hi <= lo:
            raise ValueError("Transcript span outside source PCM")
        selected = [c for c in segment.get("candidates", []) if c.get("decision") == "selected"]
        if len(selected) > 1:
            raise ValueError("Multiple selected ASR candidates")
        chosen = selected[0]["candidateID"] if selected else None
        word_data = []
        if chosen is not None and chosen in by_candidate:
            candidate = by_candidate[chosen]
            if candidate.get("phraseID") != pid or candidate.get("text") != segment.get("text"):
                raise ValueError("Selected ASR candidate disagrees with final segment")
            for word in candidate.get("words", []):
                ws = pstart + _seconds(word["start"])
                we = pstart + _seconds(word["end"])
                if ws < start or we > end or we <= ws:
                    raise ValueError("Word outside selected phrase or reversed")
                a, b = _to_original(ws, we, regions)
                wa, wb = _sample(a, sample_rate), _sample(b, sample_rate)
                if wa < lo or wb > hi or wb <= wa:
                    raise ValueError("Word not representable on source PCM")
                word_data.append({"start_sample": wa, "end_sample": wb,
                                  "text": str(word["text"]),
                                  "is_estimated": bool(word.get("isEstimated", True))})
        if not isinstance(segment.get("text"), str):
            raise ValueError("Final transcript text must be a string")
        output.append({
            "phrase_id": pid,
            "speaker_id": phrase["speaker"],
            "display_speaker": segment.get("speaker"),
            "source_language": _locale(segment.get("selectedLocale")),
            "start_sample": lo,
            "end_sample": hi,
            "text": segment["text"],
            "words": word_data,
            "needs_review": bool(segment.get("needsReview", False)) or chosen is None or chosen not in by_candidate,
            "review_reason": segment.get("reviewReason") or ("missing_selected_candidate" if chosen is None or chosen not in by_candidate else None),
            "selected_candidate_id": chosen,
            "timing_precision": "rounded_whispernotes_seconds",
        })
    output.sort(key=lambda x: (x["start_sample"], x["end_sample"], x["phrase_id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "whispernotes.session_pipeline_v2",
        "time_domain_imported": time_domain,
        "pcm_sha256": pcm_sha256.lower(),
        "sample_rate": sample_rate,
        "total_samples": total_samples,
        "segments": output,
    }
