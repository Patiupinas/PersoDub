"""Deterministic EN->RU fact hints, separate from semantic acceptance."""
import pytest

from benchmarks.persodub.translation_facts import inspect_en_ru


def test_explicit_cardinals_detect_controlled_errors():
    source = "Sing three notes slowly."
    correct = inspect_en_ru(source, "Медленно спойте три ноты.")
    wrong = inspect_en_ru(source, "Быстро спойте семь нот.")
    assert correct["review_flags"] == []
    assert wrong["review_flags"] == ["cardinal_numbers_differ_review"]
    assert wrong["source_cardinals"] == [3]
    assert wrong["translation_cardinals"] == [7]


def test_musical_key_mode_and_order_preserved():
    source = "Play C major, not A minor."
    correct = inspect_en_ru(source, "Играй до мажор, а не ля минор.")
    changed = inspect_en_ru(source, "Играй ля минор, а не до мажор.")
    assert correct["review_flags"] == []
    assert changed["review_flags"] == ["musical_key_sequence_differ_review"]
    assert changed["source_keys"] == ["do:major", "la:minor"]
    assert changed["translation_keys"] == ["la:minor", "do:major"]


def test_spoken_number_and_digits_match():
    source = "Count one, two, three."
    correct = inspect_en_ru(source, "Считай раз два три.")
    assert correct["review_flags"] == []
    assert inspect_en_ru("Repeat twice.", "Повтори два раза.")["review_flags"] == []
    assert inspect_en_ru("Try a couple times.", "Попробуй дважды.")["review_flags"] == []
    assert inspect_en_ru("Wait a couple days.", "Подожди пару дней.")["review_flags"] == []


def test_inflected_russian_cardinals_do_not_create_false_flags():
    assert inspect_en_ru(
        "Two breathing exercises.", "Двумя дыхательными упражнениями."
    )["review_flags"] == []
    assert inspect_en_ru(
        "One long attempt.", "Одной долгой попыткой."
    )["review_flags"] == []
    assert inspect_en_ru(
        "Four repetitions.", "Четырьмя повторами."
    )["review_flags"] == []


def test_first_as_sequence_adverb_not_false_number():
    source = "First hum, then open into a vowel."
    target = "Сначала мычим, потом переходим к гласной."
    assert inspect_en_ru(source, target)["review_flags"] == []


def test_number_insertion_and_omission_are_review_hints():
    assert "cardinal_numbers_differ_review" in inspect_en_ru(
        "Just sing.", "Просто пой два раза."
    )["review_flags"]
    assert "cardinal_numbers_differ_review" in inspect_en_ru(
        "Sing four notes.", "Пой ноты."
    )["review_flags"]


def test_numeric_rules_stay_en_ru_only_and_reject_invalid_input():
    with pytest.raises(ValueError, match="requires text"):
        inspect_en_ru(None, "Привет")
    assert inspect_en_ru("Sing do re mi.", "Пой до ре ми.")["review_flags"] == []
