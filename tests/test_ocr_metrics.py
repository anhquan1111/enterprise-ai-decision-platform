"""Test cho ocr_metrics.py: Levenshtein viet tay dung cho CER/WER."""

import pytest

from src.ocr_metrics import cer, wer


def test_identical_text_has_zero_error() -> None:
    assert cer("hello world", "hello world") == 0.0
    assert wer("hello world", "hello world") == 0.0


def test_one_character_substitution() -> None:
    # "hallo" vs "hello": 1 ky tu khac trong 5 ky tu cua reference
    assert cer("hallo", "hello") == pytest.approx(1 / 5)


def test_one_word_substitution() -> None:
    assert wer("toi la mot", "toi la hai") == pytest.approx(1 / 3)


def test_missing_word_counts_as_deletion() -> None:
    assert wer("toi mot", "toi la mot") == pytest.approx(1 / 3)


def test_extra_text_still_produces_a_valid_rate() -> None:
    """Hypothesis dài hơn reference rất nhiều vẫn ra một số hợp lệ, không chặn ở 1.0."""
    result = cer("a" * 100, "a")

    assert result == 99.0


def test_empty_reference_raises_instead_of_dividing_by_zero() -> None:
    with pytest.raises(ValueError):
        cer("bat ky gi", "")
    with pytest.raises(ValueError):
        wer("bat ky gi", "")


def test_empty_hypothesis_against_nonempty_reference_is_full_error() -> None:
    assert cer("", "hello") == 1.0
