"""Narrow, explainable EN->RU translation-fact review hints.

This intentionally covers only explicit cardinal numbers and musical keys.
It does not grade full semantics or infer a language from arbitrary input.
Use only when a case is explicitly known to be English -> Russian.
"""
from __future__ import annotations

import re

EN_CARDINALS = {
    "zero": 0, "one": 1, "two": 2, "three": 3,
    "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "twice": 2, "thrice": 3,
    "couple": 2,  # Approximate spoken count, used only as a review hint.
}
RU_CARDINALS = {
    "ноль": 0, "один": 1, "одна": 1, "одно": 1,
    "одну": 1, "одной": 1, "одного": 1, "одним": 1,
    "раз": 1, "два": 2, "две": 2, "двух": 2,
    "двум": 2, "двумя": 2, "двоих": 2, "три": 3,
    "трех": 3, "трем": 3, "тремя": 3,
    "четыре": 4, "четырех": 4, "четырьмя": 4,
    "пять": 5, "шесть": 6,
    "семь": 7, "восемь": 8, "девять": 9,
    "десять": 10, "одиннадцать": 11,
    "двенадцать": 12, "дважды": 2, "трижды": 3,
    "пара": 2, "пару": 2, "парой": 2,
}
EN_NOTE_NAMES = {
    "A": "la", "B": "si", "C": "do", "D": "re",
    "E": "mi", "F": "fa", "G": "sol",
}
RU_NOTE_NAMES = {
    "до": "do", "ре": "re", "ми": "mi",
    "фа": "fa", "соль": "sol", "ля": "la", "си": "si",
}
_WORD = re.compile(r"(?u)\b[\w]+\b")
_EN_KEY = re.compile(r"\b([A-G])\s+(major|minor)\b", re.IGNORECASE)
_RU_KEY = re.compile(
    r"\b(до|ре|ми|фа|соль|ля|си)[\s-]+(мажор|минор)\b",
    re.IGNORECASE,
)


def _cardinals(text: str, lookup: dict[str, int]) -> list[int]:
    numbers = []
    for token in _WORD.findall(text.lower().replace("ё", "е")):
        if token.isdigit():
            numbers.append(int(token))
        elif token in lookup:
            numbers.append(lookup[token])
    return numbers


def _music_keys_en(text: str) -> list[str]:
    return [
        EN_NOTE_NAMES[note.upper()] + ":" + mode.lower()
        for note, mode in _EN_KEY.findall(text)
    ]


def _music_keys_ru(text: str) -> list[str]:
    modes = {"мажор": "major", "минор": "minor"}
    return [
        RU_NOTE_NAMES[note.lower()] + ":" + modes[mode.lower()]
        for note, mode in _RU_KEY.findall(text)
    ]


def inspect_en_ru(source: str, candidate: str) -> dict:
    """Return optional REVIEW hints, never a translation pass/fail claim."""
    if not isinstance(source, str) or not isinstance(candidate, str):
        raise ValueError("EN/RU fact review requires text pairs")
    source_numbers = _cardinals(source, EN_CARDINALS)
    translated_numbers = _cardinals(candidate, RU_CARDINALS)
    source_keys = _music_keys_en(source)
    translated_keys = _music_keys_ru(candidate)
    flags = []
    if source_numbers != translated_numbers:
        flags.append("cardinal_numbers_differ_review")
    if source_keys != translated_keys:
        flags.append("musical_key_sequence_differ_review")
    return {
        "review_flags": flags,
        "source_cardinals": source_numbers,
        "translation_cardinals": translated_numbers,
        "source_keys": source_keys,
        "translation_keys": translated_keys,
        "scope": "en_to_ru_explicit_cardinals_and_major_minor_keys_only",
    }
