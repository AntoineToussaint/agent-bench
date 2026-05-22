"""Regression smoke tests — must keep passing after the extraction."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stats


def test_mean_basic():
    assert stats.mean([1, 2, 3, 4]) == 2.5


def test_median_odd():
    assert stats.median([3, 1, 2]) == 2.0


def test_median_even():
    assert stats.median([1, 2, 3, 4]) == 2.5


def test_range_basic():
    assert stats.range_([1, 5, 3]) == 4.0


def test_mean_coerces_strings():
    assert stats.mean(["1", "2", "3"]) == 2.0


def test_empty_raises():
    with pytest.raises(ValueError):
        stats.mean([])
    with pytest.raises(ValueError):
        stats.median([])
    with pytest.raises(ValueError):
        stats.range_([])
