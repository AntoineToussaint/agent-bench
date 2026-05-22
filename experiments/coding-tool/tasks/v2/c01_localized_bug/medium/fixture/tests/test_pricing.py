"""Regression tests that should ALWAYS pass after any well-behaved edit."""

from ecom.models import Order, OrderLine, Product, User
from ecom.pricing import (
    apply_discount,
    apply_shipping,
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


def test_apply_shipping_free_above_threshold() -> None:
    assert apply_shipping(100.01, 5.0) == 100.01


def test_apply_shipping_charged_below_threshold() -> None:
    assert abs(apply_shipping(50.0, 2.0) - 55.0) < 1e-6


def test_compute_total_no_discount() -> None:
    o = _make_order()
    # subtotal=100, no discount, tax=108, free shipping
    assert compute_total(o) == 108.0


def test_compute_total_with_discount() -> None:
    o = _make_order(discount_pct=10.0)
    # subtotal=100, after disc=90, tax=97.2, weight=2kg, shipping=97.2+5=102.20
    assert compute_total(o) == 102.20


def test_estimate_savings() -> None:
    o = _make_order(discount_pct=10.0)
    # no-disc total = 108 + (108<100? no) -> 108. With disc = 102.20. Saved=5.80
    assert estimate_savings(o) == 5.80
