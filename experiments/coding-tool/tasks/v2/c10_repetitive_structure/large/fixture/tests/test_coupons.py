"""Tests for the coupon module."""

from datetime import date, timedelta

import pytest

from ecom.coupons import (
    Coupon,
    CouponError,
    CouponType,
    apply_coupon,
    clear_coupons,
    get_coupon,
    register_coupon,
)
from ecom.models import Order, OrderLine, Product, User
from ecom.pricing import compute_total


def _order(qty: int = 2, unit_price: float = 50.0) -> Order:
    user = User(user_id=1, email="a@b.com", name="A")
    product = Product(product_id=1, name="Widget", unit_price=unit_price, weight_kg=1.0)
    return Order(
        order_id=99,
        user=user,
        lines=[OrderLine(product=product, quantity=qty)],
    )


def test_percentage_coupon_reduces_total() -> None:
    order = _order()
    base = compute_total(order)
    coupon = Coupon(code="P10", coupon_type=CouponType.PERCENTAGE, value=10.0)
    new_total = apply_coupon(order, coupon)
    assert new_total < base
    assert coupon.uses == 1


def test_fixed_coupon_subtracts_amount() -> None:
    order = _order()
    base = compute_total(order)
    coupon = Coupon(code="FIVE", coupon_type=CouponType.FIXED, value=5.0)
    new_total = apply_coupon(order, coupon)
    assert new_total == round(base - 5.0, 2)


def test_free_shipping_coupon_zeroes_shipping() -> None:
    # subtotal below free-shipping threshold so shipping would normally apply
    order = _order(qty=1, unit_price=20.0)
    coupon = Coupon(code="FREESHIP", coupon_type=CouponType.FREE_SHIPPING)
    base = compute_total(order)
    new_total = apply_coupon(order, coupon)
    assert new_total < base


def test_expired_coupon_raises() -> None:
    order = _order()
    coupon = Coupon(
        code="OLD",
        coupon_type=CouponType.PERCENTAGE,
        value=10.0,
        expires_on=date.today() - timedelta(days=1),
    )
    with pytest.raises(CouponError):
        apply_coupon(order, coupon)


def test_min_order_amount_enforced() -> None:
    order = _order(qty=1, unit_price=10.0)  # subtotal 10
    coupon = Coupon(
        code="BIGORDER",
        coupon_type=CouponType.FIXED,
        value=2.0,
        min_order_amount=50.0,
    )
    with pytest.raises(CouponError):
        apply_coupon(order, coupon)


def test_register_and_get_coupon_roundtrip() -> None:
    clear_coupons()
    coupon = Coupon(code="HELLO", coupon_type=CouponType.PERCENTAGE, value=5.0)
    register_coupon(coupon)
    assert get_coupon("HELLO") is coupon
    with pytest.raises(CouponError):
        get_coupon("MISSING")
