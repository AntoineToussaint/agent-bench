"""Oracle for c01_localized_bug / large — coupon expiry off-by-one."""

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


def _order():
    from ecom.models import Order, OrderLine, Product, User

    user = User(user_id=1, email="a@b.com", name="A")
    product = Product(product_id=1, name="Widget", unit_price=50.0, weight_kg=1.0)
    return Order(
        order_id=99,
        user=user,
        lines=[OrderLine(product=product, quantity=2)],
    )


def test_coupon_expiring_today_is_still_valid() -> None:
    from ecom.coupons import Coupon, CouponType, apply_coupon

    today = date.today()
    coupon = Coupon(
        code="LASTDAY",
        coupon_type=CouponType.PERCENTAGE,
        value=10.0,
        expires_on=today,
    )
    # Should not raise — the coupon is valid through its expiry date.
    apply_coupon(_order(), coupon, today=today)


def test_coupon_expired_yesterday_still_rejected() -> None:
    from ecom.coupons import Coupon, CouponError, CouponType, apply_coupon

    today = date.today()
    coupon = Coupon(
        code="OLD",
        coupon_type=CouponType.PERCENTAGE,
        value=10.0,
        expires_on=today - timedelta(days=1),
    )
    try:
        apply_coupon(_order(), coupon, today=today)
    except CouponError:
        return
    raise AssertionError("expected CouponError for coupon expired yesterday")


def test_coupon_with_no_expiry_still_valid() -> None:
    from ecom.coupons import Coupon, CouponType, apply_coupon

    coupon = Coupon(code="FOREVER", coupon_type=CouponType.PERCENTAGE, value=10.0)
    # No expires_on -> never expires.
    apply_coupon(_order(), coupon)


def test_is_expired_uses_strict_inequality() -> None:
    src = (ROOT / "ecom" / "coupons.py").read_text(encoding="utf-8")
    assert "today > coupon.expires_on" in src
    assert "today >= coupon.expires_on" not in src
