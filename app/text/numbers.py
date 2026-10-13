"""Digits written out the way they are said, before Qwen3-TTS reads a line.

Handed "1990년대", "80년대" or "2020년" as digits, Qwen3-TTS read them oddly
in every dubbing the owner heard (2026-10-03). The voice engine gets the
spoken form; the script, the screen and the Whisper checks keep the digits
(Whisper writes what it hears back as digits).

Per language, the way OmniVoice and VoiceStudio do it: num2words for the
languages it reads right, and Korean's own rule, which num2words lacks --
a number before a counting word (명, 개, 번, 살, 시 ...) is said the native
way ("세 번", "두 명"), everything else the Sino-Korean way ("천구백구십년").
Chinese and Japanese keep their digits: num2words has no Chinese, and its
Japanese years come out as era names (1990 -> 平成二年).

Conservative, as VoiceStudio's text normalization is: whatever could be
misread is left as it is -- version strings, clock times, ranges, codes with
a leading zero, numbers of seven digits or more, digits inside a word.
"""
import re
from typing import Optional

from num2words import num2words

_LANGS = {"korean": "ko", "english": "en", "german": "de", "french": "fr", "russian": "ru",
          "portuguese": "pt", "spanish": "es", "italian": "it"}
_YEAR_LANGS = {"en", "de"}          # num2words' to="year" says these the way people do

# A number: an optional $, the digits (thousands grouped by commas or not), a decimal part.
_NUMBER = re.compile(r"(\$)?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")

# What may follow English digits: a decade's "s" ("80s", "'80s") or an ordinal's ending.
_EN_SUFFIX = re.compile(r"s\b|(st|nd|rd|th)\b")

_NATIVE_TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]
_NATIVE_ONES = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
_FIRST_ORDINALS = {1: "첫", 2: "두", 3: "세", 4: "네", 20: "스무"}
# Counting words said with a native number below 100. Longer words first, and
# the Sino ones that start like them ("개월") are tried before them.
_SINO_FIRST = ("개월",)
_NATIVE_COUNTERS = ("번째", "번", "명", "개", "살", "시간", "시", "마리", "가지", "잔", "권", "벌", "켤레",
                    "군데", "송이", "그루", "채", "척", "사람", "달")


def _lang(language: Optional[str]) -> Optional[str]:
    return _LANGS.get((language or "").strip().lower())


def _native(n: int) -> str:
    """1-99 the native Korean way, in the form used before a counting word."""
    if n == 20:
        return "스무"
    return _NATIVE_TENS[n // 10] + _NATIVE_ONES[n % 10]


def _korean(value: int, frac: Optional[str], after: str) -> tuple:
    """(spoken, characters of `after` it consumed)."""
    if after.startswith("%"):
        return num2words(value, lang="ko") + _korean_frac(frac) + " 퍼센트", 1
    if frac is None and after.startswith("월") and value in (6, 10):
        return {6: "유", 10: "시"}[value], 0
    if frac is None and 0 < value < 100 and not after.startswith(_SINO_FIRST):
        if after.startswith("번째"):
            return _FIRST_ORDINALS.get(value, _native(value)), 0
        if after.startswith(_NATIVE_COUNTERS):
            return _native(value), 0
    return num2words(value, lang="ko") + _korean_frac(frac), 0


def _korean_frac(frac: Optional[str]) -> str:
    return " 점 " + "".join(num2words(int(d), lang="ko") for d in frac) if frac else ""


def _plural(words: str) -> str:
    return words[:-1] + "ies" if words.endswith("y") else words + "s"


def _english(value: int, raw: str, frac: Optional[str], dollar: bool, after: str) -> tuple:
    if not dollar and frac is None:
        decade = re.match(r"'?s\b", after)
        if decade and value % 10 == 0 and (len(raw) == 2 or len(raw) == 4):
            words = num2words(value, lang="en", to="year" if len(raw) == 4 else "cardinal")
            return _plural(words), decade.end()
        ordinal = re.match(r"(st|nd|rd|th)\b", after)
        if ordinal:
            return num2words(value, lang="en", to="ordinal"), ordinal.end()
    words = num2words(value, lang="en").replace(",", "")
    if frac:
        words += " point " + " ".join(num2words(int(d), lang="en") for d in frac)
    elif not dollar and "," not in raw and len(raw) == 4 and 1100 <= value <= 2099:
        words = num2words(value, lang="en", to="year")
    if dollar:
        return words + (" dollar" if value == 1 and not frac else " dollars"), 0
    if after.startswith("%"):
        return words + " percent", 1
    return words, 0


def _readable(m, text: str, lang: str) -> bool:
    """Whether this number can be read without risk of misreading it."""
    raw, start, end = m.group(2), m.start(), m.end()
    before = text[start - 1] if start else ""
    after = text[end:end + 2]
    if before and (before.isalnum() or before in "._:/-"):
        return False                      # inside a word, a code, a time or a version
    if before == "," and start > 1 and text[start - 2].isdigit():
        return False                      # the decimals of "3,5"
    if after[:1] in (":", "-", ".", "/", ",") and after[1:2].isdigit():
        return False                      # a time, a range, a version, a date, "3,5"
    if after[:1].isalpha() and after[:1].isascii() and not (lang == "en" and _EN_SUFFIX.match(after)):
        return False                      # "3D", "4K"; English keeps "80s" and "21st"
    digits = raw.replace(",", "")
    if len(digits) > 1 and digits[0] == "0" or len(digits) >= 7 and "," not in raw:
        return False                      # a code with a leading zero, a phone number, an ID
    if "," in raw and lang not in ("ko", "en"):
        return False                      # "1,000" or "1,5" depends on the language
    # Decimals and currency only where their reading was checked.
    return not ((m.group(3) or m.group(1)) and lang not in ("ko", "en"))


def spoken_numbers(text: str, language: Optional[str]) -> str:
    """The line with its numbers written out the way they are said in
    `language` (a full name, "Korean"); unchanged for a language without
    a checked reading."""
    lang = _lang(language)
    if not lang or not text or not any(c.isdigit() for c in text):
        return text
    out, pos = [], 0
    for m in _NUMBER.finditer(text):
        if m.start() < pos or not _readable(m, text, lang):
            continue
        raw, frac, dollar = m.group(2), m.group(3), bool(m.group(1))
        value = int(raw.replace(",", ""))
        after = text[m.end():]
        if lang == "ko":
            words, used = _korean(value, frac, after)
        elif lang == "en":
            words, used = _english(value, raw, frac, dollar, after)
        else:
            words, used = num2words(value, lang=lang, to="year" if lang in _YEAR_LANGS and len(raw) == 4
                                    and 1100 <= value <= 2099 else "cardinal"), 0
        head = text[pos:m.start()]
        if lang == "en" and head.endswith("'") and words.endswith(("ties", "ds", "tens")):
            head = head[:-1]              # "'80s" -> "eighties"
        out.append(head)
        out.append(words)
        pos = m.end() + used
    out.append(text[pos:])
    return "".join(out)
