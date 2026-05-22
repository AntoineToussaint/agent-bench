"""Regression smoke tests — must keep passing after the sweep."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app
import math_utils


def test_square_works() -> None:
    assert math_utils.square(5) == 25


def test_cube_works() -> None:
    assert math_utils.cube(3) == 27


def test_squares_works() -> None:
    assert app.squares([2, 3]) == [4, 9]


def test_total_works() -> None:
    assert app.total([1, 2, 3]) == 12
