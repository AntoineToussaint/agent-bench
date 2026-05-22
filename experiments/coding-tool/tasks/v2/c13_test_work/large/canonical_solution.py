"""Canonical solution for c13_test_work / large."""

from __future__ import annotations

from pathlib import Path


ADDITIONS = '''

def test_coupon_min_order_amount_blocks_below() -> None:
    order = _order(qty=1, unit_price=5.0)  # subtotal=5
    coupon = Coupon(
        code="BIG",
        coupon_type=CouponType.PERCENTAGE,
        value=10.0,
        min_order_amount=100.0,
    )
    with pytest.raises(CouponError):
        apply_coupon(order, coupon)


def test_coupon_usage_cap_exhausted() -> None:
    order = _order()
    coupon = Coupon(
        code="ONCE",
        coupon_type=CouponType.PERCENTAGE,
        value=5.0,
        max_uses=1,
    )
    apply_coupon(order, coupon)
    with pytest.raises(CouponError):
        apply_coupon(order, coupon)


def test_apply_coupon_free_shipping_combines_with_subtotal() -> None:
    from ecom.pricing import apply_tax

    order = _order(qty=1, unit_price=20.0)  # subtotal=20, below free-shipping threshold
    coupon = Coupon(code="FREESHIP2", coupon_type=CouponType.FREE_SHIPPING)
    new_total = apply_coupon(order, coupon)
    expected = round(apply_tax(order.subtotal), 2)
    assert new_total == expected


def test_register_coupon_roundtrip() -> None:
    clear_coupons()
    coupon = Coupon(code="ROUNDTRIP", coupon_type=CouponType.PERCENTAGE, value=5.0)
    register_coupon(coupon)
    assert get_coupon("ROUNDTRIP") is coupon
'''


def apply(workdir: Path) -> None:
    p = workdir / "tests" / "test_coupons.py"
    text = p.read_text(encoding="utf-8")
    if "def test_coupon_min_order_amount_blocks_below" in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    p.write_text(text + ADDITIONS, encoding="utf-8")
