"""Canonical solution for c10_repetitive_structure / small."""

from __future__ import annotations

from pathlib import Path


def apply(workdir: Path) -> None:
    p = workdir / "handlers.py"
    text = p.read_text(encoding="utf-8")
    # Match the handle_404 body line specifically; "not found" appears only in
    # handle_404, so this won't accidentally hit other handlers.
    old = 'def handle_404():\n    status = 404\n    body = "not found"\n'
    new = 'def handle_404():\n    status = 404\n    body = "resource missing"\n'
    assert old in text, "expected handle_404 with 'not found' body"
    p.write_text(text.replace(old, new), encoding="utf-8")
