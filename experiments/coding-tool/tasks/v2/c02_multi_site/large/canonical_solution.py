"""Canonical solution for c02_multi_site / large."""

from __future__ import annotations

from pathlib import Path


OLD = "support@example.com"
NEW = "help@example.com"


def apply(workdir: Path) -> None:
    for p in workdir.rglob("*.py"):
        if "__pycache__" in p.parts or "_overlay" in p.parts:
            continue
        text = p.read_text(encoding="utf-8")
        if OLD in text:
            p.write_text(text.replace(OLD, NEW), encoding="utf-8")
