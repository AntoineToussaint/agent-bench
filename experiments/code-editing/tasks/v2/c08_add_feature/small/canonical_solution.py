"""Canonical solution for c08_add_feature / small."""

from __future__ import annotations

from pathlib import Path


ADDITION = '''

def category(age):
    if age < LEGAL_AGE:
        return "minor"
    if age < SENIOR_AGE:
        return "adult"
    return "senior"


def discount_pct(age):
    bracket = category(age)
    if bracket == "minor":
        return 0.5
    if bracket == "senior":
        return 0.3
    return 0.0
'''


def apply(workdir: Path) -> None:
    p = workdir / "ages.py"
    text = p.read_text(encoding="utf-8")
    if "def category(" in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    p.write_text(text + ADDITION, encoding="utf-8")
