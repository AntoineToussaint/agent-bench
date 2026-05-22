"""Canonical solution for c09_remove_sweep / medium."""

from __future__ import annotations

from pathlib import Path


NEW_PRICING = '''"""Pricing calculations.

Intentional shape:
  - `apply_tax`, `apply_discount` follow a similar "compute adjustment as a
    percentage" pattern (extract-method candidate).
  - `TAX_RATE` constant is referenced from multiple places (multi-site candidate).
  - `compute_total` is the orchestrator that all callers go through.
"""

from __future__ import annotations

from ecom.models import Order

TAX_RATE = 0.08
MAX_DISCOUNT_PCT = 50.0


def apply_discount(subtotal: float, discount_pct: float) -> float:
    if discount_pct < 0 or discount_pct > MAX_DISCOUNT_PCT:
        raise ValueError(f"discount_pct out of range: {discount_pct}")
    adjustment = subtotal * (discount_pct / 100.0)
    return subtotal - adjustment


def apply_tax(subtotal: float) -> float:
    adjustment = subtotal * TAX_RATE
    return subtotal + adjustment


def compute_total(order: Order) -> float:
    subtotal = order.subtotal
    after_discount = apply_discount(subtotal, order.discount_pct)
    after_tax = apply_tax(after_discount)
    return round(after_tax, 2)


def estimate_savings(order: Order) -> float:
    """How much does the customer save vs no-discount."""
    no_disc = apply_tax(order.subtotal)
    return round(no_disc - compute_total(order), 2)
'''


NEW_TEST_PRICING = '''"""Regression tests that should ALWAYS pass after any well-behaved edit."""

from ecom.models import Order, OrderLine, Product, User
from ecom.pricing import (
    apply_discount,
    apply_tax,
    compute_total,
    estimate_savings,
)


def _user() -> User:
    return User(user_id=1, email="a@b.com", name="A")


def _make_order(discount_pct: float = 0.0) -> Order:
    p = Product(product_id=1, name="Widget", unit_price=50.0, weight_kg=1.0)
    return Order(
        order_id=1,
        user=_user(),
        lines=[OrderLine(product=p, quantity=2)],
        discount_pct=discount_pct,
    )


def test_apply_discount_zero() -> None:
    assert apply_discount(100.0, 0.0) == 100.0


def test_apply_discount_ten() -> None:
    assert apply_discount(100.0, 10.0) == 90.0


def test_apply_tax_default_rate() -> None:
    assert abs(apply_tax(100.0) - 108.0) < 1e-6


def test_compute_total_no_discount() -> None:
    o = _make_order()
    # subtotal=100, no discount, tax=108
    assert compute_total(o) == 108.0


def test_compute_total_with_discount() -> None:
    o = _make_order(discount_pct=10.0)
    # subtotal=100, after disc=90, tax=97.2
    assert compute_total(o) == 97.20


def test_estimate_savings() -> None:
    o = _make_order(discount_pct=10.0)
    # no-disc tax-only total = 108. With disc = 97.20. Saved = 10.80
    assert estimate_savings(o) == 10.80
'''


def apply(workdir: Path) -> None:
    (workdir / "ecom" / "pricing.py").write_text(NEW_PRICING, encoding="utf-8")
    (workdir / "tests" / "test_pricing.py").write_text(
        NEW_TEST_PRICING, encoding="utf-8"
    )
