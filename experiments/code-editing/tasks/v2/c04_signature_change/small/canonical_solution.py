"""Canonical solution for c04_signature_change / small."""

from __future__ import annotations

from pathlib import Path


BILLING_NEW = '''"""Tiny billing helper — toy size."""

from __future__ import annotations


def compute_total(items, discount=0.0, *, tax_rate: float = 0.0):
    subtotal = sum(price for _, price in items)
    after_discount = subtotal * (1 - discount)
    return after_discount * (1 + tax_rate)
'''


APP_NEW = '''from billing import compute_total


def checkout(cart):
    return compute_total(cart, discount=0.05, tax_rate=0.1)


def quick_total(cart):
    return compute_total(cart)   # no discount
'''


def apply(workdir: Path) -> None:
    (workdir / "billing.py").write_text(BILLING_NEW, encoding="utf-8")
    (workdir / "app.py").write_text(APP_NEW, encoding="utf-8")
    # report.py is intentionally untouched
