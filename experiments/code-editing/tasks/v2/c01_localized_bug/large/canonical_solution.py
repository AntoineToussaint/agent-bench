"""Canonical solution for c01_localized_bug / large."""

from __future__ import annotations

from pathlib import Path


def apply(workdir: Path) -> None:
    p = workdir / "ecom" / "coupons.py"
    text = p.read_text(encoding="utf-8")
    fixed = text.replace(
        "    return coupon.expires_on is not None and today >= coupon.expires_on",
        "    return coupon.expires_on is not None and today > coupon.expires_on",
    )
    assert fixed != text, "expected to find the buggy `>=` comparison in coupons.py"
    p.write_text(fixed, encoding="utf-8")
