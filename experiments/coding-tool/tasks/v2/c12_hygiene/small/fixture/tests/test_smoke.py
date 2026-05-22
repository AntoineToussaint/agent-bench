"""Regression smoke tests — must keep passing after the hygiene edit."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import divider


def test_divide_happy_path():
    assert divider.divide(10, 2) == 5.0


def test_safe_divide_all_happy_path():
    assert divider.safe_divide_all([2, 4, 6], 2) == [1.0, 2.0, 3.0]


def test_average_happy_path():
    assert divider.average([2, 4, 6]) == 4.0
