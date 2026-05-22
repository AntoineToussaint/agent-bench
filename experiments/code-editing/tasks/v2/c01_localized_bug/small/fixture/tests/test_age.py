"""Regression tests that must keep passing after the fix."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from age import is_minor, is_senior


def test_is_senior_at_threshold():
    assert is_senior(65) is True


def test_is_senior_below_threshold():
    assert is_senior(64) is False


def test_is_senior_above_threshold():
    assert is_senior(80) is True


def test_is_minor_below_threshold():
    assert is_minor(17) is True


def test_is_minor_at_threshold():
    assert is_minor(18) is False
