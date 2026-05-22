"""Canonical solution for c03_xfile_rename / large (same as medium)."""

from __future__ import annotations

import re
from pathlib import Path


def apply(workdir: Path) -> None:
    pattern = re.compile(r"\bcompute_total\b")
    for p in workdir.rglob("*.py"):
        if "__pycache__" in p.parts or "_overlay" in p.parts:
            continue
        text = p.read_text(encoding="utf-8")
        if pattern.search(text):
            p.write_text(pattern.sub("calculate_order_total", text), encoding="utf-8")
