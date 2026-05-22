"""Canonical solution for c02_multi_site / medium."""

from __future__ import annotations

import re
from pathlib import Path


def apply(workdir: Path) -> None:
    p = workdir / "ecom" / "notifications.py"
    text = p.read_text(encoding="utf-8")
    # Prefix every existing `print(f"sending ...")` with `[outbox] `.
    new_text = re.sub(
        r'print\(f"sending ',
        'print(f"[outbox] sending ',
        text,
    )
    assert new_text != text, "expected to find `print(f\"sending ` lines in notifications.py"
    p.write_text(new_text, encoding="utf-8")
