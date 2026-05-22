"""Coupon definitions and order-level coupon application."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

from ecom.models import Order
from ecom.pricing import (
    MAX_DISCOUNT_PCT,
    apply_shipping,
    apply_tax,
    compute_total,
)


class CouponType(str, Enum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"
    FREE_SHIPPING = "free_shipping"


class CouponError(Exception):
    pass


@dataclass
class Coupon:
    code: str
    coupon_type: CouponType
    value: float = 0.0
    min_order_amount: float = 0.0
    expires_on: Optional[date] = None
    max_uses: Optional[int] = None
    uses: int = 0
    active: bool = True
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.coupon_type == CouponType.PERCENTAGE:
            if self.value < 0 or self.value > MAX_DISCOUNT_PCT:
                raise CouponError(
                    f"percentage coupon out of range: {self.value} "
                    f"(max {MAX_DISCOUNT_PCT})"
                )
        elif self.coupon_type == CouponType.FIXED:
            if self.value < 0:
                raise CouponError(f"fixed coupon must be non-negative: {self.value}")
        elif self.coupon_type == CouponType.FREE_SHIPPING:
            # value is ignored for free shipping coupons
            pass

    @property
    def exhausted(self) -> bool:
        return self.max_uses is not None and self.uses >= self.max_uses


def _is_expired(coupon: Coupon, today: date) -> bool:
    return coupon.expires_on is not None and today > coupon.expires_on


def validate_coupon(
    coupon: Coupon,
    order: Order,
    today: Optional[date] = None,
) -> None:
    today = today or date.today()
    if not coupon.active:
        raise CouponError(f"coupon {coupon.code} is inactive")
    if _is_expired(coupon, today):
        raise CouponError(f"coupon {coupon.code} expired on {coupon.expires_on}")
    if coupon.exhausted:
        raise CouponError(f"coupon {coupon.code} usage limit reached")
    if order.subtotal < coupon.min_order_amount:
        raise CouponError(
            f"coupon {coupon.code} requires min order {coupon.min_order_amount}"
        )


def _percentage_total(order: Order, pct: float) -> float:
    capped = min(pct, MAX_DISCOUNT_PCT)
    original = order.discount_pct
    order.discount_pct = min(original + capped, MAX_DISCOUNT_PCT)
    try:
        return compute_total(order)
    finally:
        order.discount_pct = original


def _fixed_total(order: Order, amount: float) -> float:
    base = compute_total(order)
    return round(max(base - amount, 0.0), 2)


def _free_shipping_total(order: Order) -> float:
    subtotal = order.subtotal
    # mirror compute_total but skip the shipping leg
    from ecom.pricing import apply_discount

    after_discount = apply_discount(subtotal, order.discount_pct)
    after_tax = apply_tax(after_discount)
    return round(after_tax, 2)


def apply_coupon(
    order: Order,
    coupon: Coupon,
    today: Optional[date] = None,
) -> float:
    validate_coupon(order=order, coupon=coupon, today=today)
    if coupon.coupon_type == CouponType.PERCENTAGE:
        new_total = _percentage_total(order, coupon.value)
    elif coupon.coupon_type == CouponType.FIXED:
        new_total = _fixed_total(order, coupon.value)
    elif coupon.coupon_type == CouponType.FREE_SHIPPING:
        new_total = _free_shipping_total(order)
    else:  # pragma: no cover - defensive
        raise CouponError(f"unsupported coupon type: {coupon.coupon_type}")
    coupon.uses += 1
    order.notes.append(f"coupon={coupon.code} total={new_total}")
    return new_total


_coupons: dict[str, Coupon] = {}


def register_coupon(coupon: Coupon) -> None:
    _coupons[coupon.code] = coupon


def get_coupon(code: str) -> Coupon:
    if code not in _coupons:
        raise CouponError(f"unknown coupon: {code}")
    return _coupons[code]


def clear_coupons() -> None:
    _coupons.clear()


def estimate_discount(order: Order, coupon: Coupon) -> float:
    """How much does this coupon save vs. the un-couponed total."""
    base = compute_total(order)
    new_total = apply_coupon(order, coupon)
    # apply_coupon mutates `uses`; undo so estimation is side-effect free on usage
    coupon.uses = max(coupon.uses - 1, 0)
    if order.notes and order.notes[-1].startswith(f"coupon={coupon.code}"):
        order.notes.pop()
    return round(base - new_total, 2)


# `apply_shipping` is re-exported so callers can reason about shipping in tests
__all__ = [
    "Coupon",
    "CouponError",
    "CouponType",
    "apply_coupon",
    "apply_shipping",
    "clear_coupons",
    "estimate_discount",
    "get_coupon",
    "register_coupon",
    "validate_coupon",
]
