"""Regression smoke tests — must keep passing after the signature change."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app
import billing
import report


def test_quick_total_unchanged():
    assert billing.compute_total([("a", 100)]) == 100.0


def test_daily_unchanged():
    assert report.daily([[("a", 50)], [("b", 50)]]) == 100.0


def test_app_quick_total_unchanged():
    assert app.quick_total([("a", 200)]) == 200.0
