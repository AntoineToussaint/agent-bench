"""Regression smoke tests — must keep passing after the feature is added."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ages


def test_is_adult_below() -> None:
    assert ages.is_adult(17) is False


def test_is_adult_at_legal_age() -> None:
    assert ages.is_adult(18) is True


def test_is_senior_below() -> None:
    assert ages.is_senior(64) is False


def test_is_senior_at_threshold() -> None:
    assert ages.is_senior(65) is True
