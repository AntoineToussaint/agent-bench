"""Canonical solution for c03_xfile_rename / small."""

from __future__ import annotations

from pathlib import Path


def apply(workdir: Path) -> None:
    for rel in ("utils.py", "main.py", "tests/test_smoke.py"):
        p = workdir / rel
        text = p.read_text(encoding="utf-8")
        # Word-boundary-ish: replace `helper` only when not adjacent to letters/digits/underscore
        import re

        new_text = re.sub(r"\bhelper\b", "double_value", text)
        p.write_text(new_text, encoding="utf-8")
