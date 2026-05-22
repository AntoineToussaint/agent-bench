"""Canonical solution for c01_localized_bug / small."""

from __future__ import annotations

from pathlib import Path


def apply(workdir: Path) -> None:
    p = workdir / "age.py"
    text = p.read_text(encoding="utf-8")
    fixed = text.replace(
        "    return age > LEGAL_AGE",
        "    return age >= LEGAL_AGE",
    )
    assert fixed != text, "expected to find the buggy comparison in age.py"
    p.write_text(fixed, encoding="utf-8")
