"""Canonical solution for c01_localized_bug / medium."""

from __future__ import annotations

from pathlib import Path


def apply(workdir: Path) -> None:
    p = workdir / "ecom" / "pricing.py"
    text = p.read_text(encoding="utf-8")
    fixed = text.replace(
        "    if subtotal > FREE_SHIPPING_THRESHOLD:",
        "    if subtotal >= FREE_SHIPPING_THRESHOLD:",
    )
    assert fixed != text, "expected to find the buggy `>` comparison in pricing.py"
    p.write_text(fixed, encoding="utf-8")
