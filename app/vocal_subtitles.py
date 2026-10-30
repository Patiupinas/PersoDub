"""Build three switchable subtitle tracks from approved selective-dub cues.

Source SRT, Russian SRT, and dual-language ASS reuse PersoDub renderers.
"""

from app.subtitle_ass import build_ass
from app.text.srt import build_srt


def build_subtitle_tracks(segments, *, sample_rate, width, height):
    """Render approved translation cues without captioning protected vocal sound.

    Each segment: id, start_sample, end_sample, action, source_text, ru_text.
    No new ASR text is created here, and REVIEW/PRESERVE never make up captions.
    """
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("Invalid sample rate")
    if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (width, height)):
        raise ValueError("Invalid video dimensions")
    if not isinstance(segments, list):
        raise ValueError("Expected list of selective-dub subtitle segments")
    seen, cues = set(), []
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError("Invalid subtitle segment")
        sid = segment.get("id")
        if not isinstance(sid, str) or not sid or sid in seen:
            raise ValueError("Each subtitle segment needs a unique id")
        seen.add(sid)
        action = segment.get("action")
        if action not in ("TRANSLATE", "PRESERVE", "REVIEW"):
            raise ValueError("Subtitles need resolved leaf actions")
        start, end = segment.get("start_sample"), segment.get("end_sample")
        if any(isinstance(x, bool) or not isinstance(x, int) for x in (start, end)) or start < 0 or end <= start:
            raise ValueError("Invalid source PCM subtitle bounds")
        if action != "TRANSLATE":
            continue
        source, translated = segment.get("source_text"), segment.get("ru_text")
        if not isinstance(source, str) or not source.strip() or not isinstance(translated, str) or not translated.strip():
            raise ValueError("Every translated speech segment requires both subtitle texts")
        if "-->" in source or "-->" in translated:
            raise ValueError("Subtitle text contains an SRT time-arrow sequence")
        cues.append((start, end, sid, source.strip(), translated.strip()))

    cues.sort()
    for i, (start, end, _, _, _) in enumerate(cues):
        if i and start < cues[i - 1][1]:
            raise ValueError("Translation subtitle cues overlap")
    original, translated, bilingual = [], [], []
    for start, end, _, src, ru in cues:
        start_sec, end_sec = start / sample_rate, end / sample_rate
        original.append({"start": start_sec, "end": end_sec, "text": src})
        translated.append({"start": start_sec, "end": end_sec, "text": ru})
        bilingual.append({"start": start_sec, "end": end_sec, "text": f"{src}\n{ru}"})
    return {
        "source_srt": build_srt(original),
        "russian_srt": build_srt(translated),
        "bilingual_ass": build_ass(bilingual, "clean", width=width, height=height),
        "translated_cues": len(cues),
        "protected_cues_skipped": len(segments) - len(cues),
    }
