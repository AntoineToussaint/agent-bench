"""Regression smoke tests — must keep passing after the rename."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
import utils


def test_triple_unchanged():
    assert utils.triple(4) == 12


def test_quadruple_unchanged():
    assert utils.quadruple(3) == 12


def test_compute_works():
    assert main.compute(3, 4) == 18
