"""Canonical solution for c13_test_work / small."""

from __future__ import annotations

from pathlib import Path


ADDITIONS = '''

def test_add_negative():
    assert add(-2, -3) == -5


def test_add_zero():
    assert add(0, 7) == 7


def test_add_large():
    assert add(1_000_000, 2_000_000) == 3_000_000
'''


def apply(workdir: Path) -> None:
    p = workdir / "tests" / "test_calc.py"
    text = p.read_text(encoding="utf-8")
    if "def test_add_negative" in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    p.write_text(text + ADDITIONS, encoding="utf-8")
