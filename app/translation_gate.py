"""Conservative Russian dubbing candidate checks before TTS.

These are review gates, never a semantic-accuracy oracle: an apparently valid
candidate can still mistranslate the English source. A flagged line must not be
silently committed as an approved voice-over.
"""
import math
import re

_RU_WORD = re.compile(r"[А-Яа-яЁё]+", re.UNICODE)
_UNFINISHED = re.compile(r"(?:\b(?:когда|если|потому что|я только что|не могу|и тогда)\s*)$", re.I)
_FEMALE_PAST = re.compile(r"\b(?:я\s+)?(?:хотела|бегала|пела|делала|сказала|думала)\b", re.I)
_FORMAL = re.compile(r"\b(?:вы|вас|вам|ваш|ваша|ваши|выберите|пойте|запомните)\b", re.I)


def review_ru_lines(texts, translations, durations, *, max_words_per_second=2.3,
                    informal=True, male_narrator=False,
                    allow_source_continuations=False):
    """Return actionable line flags; do not infer translator superiority."""
    if len(texts) != len(translations) or len(texts) != len(durations):
        raise ValueError("Source, translations, and original durations must align")
    flags = []
    for number, (source, translated, duration) in enumerate(zip(texts, translations, durations), 1):
        issues = []
        if not isinstance(translated, str) or not _RU_WORD.search(translated):
            issues.append("missing_russian")
        else:
            words = len(_RU_WORD.findall(translated))
            if not isinstance(duration, (int, float)) or duration <= 0:
                issues.append("invalid_source_duration")
            elif words > math.ceil(duration * max_words_per_second) + (
                1 if allow_source_continuations else 0
            ):
                issues.append("too_long_for_source_clock")
            cleaned = translated.strip()
            source_continues = (
                allow_source_continuations
                and not source.strip().endswith((".", "?", "!", "…"))
            )
            if not source_continues and (
                not cleaned.endswith((".", "?", "!", "…"))
                or _UNFINISHED.search(cleaned.rstrip(".,!?… "))
            ):
                issues.append("possible_sentence_fragment")
            if informal and _FORMAL.search(cleaned):
                issues.append("address_register_inconsistent")
            if male_narrator and _FEMALE_PAST.search(cleaned):
                issues.append("narrator_gender_inconsistent")
        if issues:
            flags.append({"cue": number, "issues": issues})
    return flags
