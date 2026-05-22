"""Regression smoke tests — must keep passing after inlining."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import geometry


def test_circle_area():
    assert geometry.circle_area(2) == 3.14159 * 4


def test_rectangle_diagonal_3_4_5():
    assert geometry.rectangle_diagonal(3, 4) == 5.0


def test_cube_volume():
    assert geometry.cube_volume(3) == 27


def test_cube_surface_area():
    assert geometry.cube_surface_area(2) == 24
