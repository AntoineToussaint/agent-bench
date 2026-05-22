"""Oracle for c07_inline_function / large — inline `_is_currently_active`."""

import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


def _read() -> str:
    return (ROOT / "ecom" / "coupons.py").read_text(encoding="utf-8")


def test_helper_is_gone() -> None:
    from ecom import coupons

    assert not hasattr(coupons, "_is_currently_active"), (
        "_is_currently_active must be removed from the module"
    )


def test_no_helper_def_remains() -> None:
    src = _read()
    assert not re.search(r"^def _is_currently_active\b", src, re.MULTILINE), (
        "_is_currently_active definition must be deleted"
    )


def test_no_helper_call_remains() -> None:
    src = _read()
    assert not re.search(r"\b_is_currently_active\s*\(", src), (
        "no call to _is_currently_active should remain in coupons.py"
    )


def test_inlined_expression_present_in_both_callers() -> None:
    """Both call sites must now contain the inlined boolean expression."""
    import ast

    src = _read()
    tree = ast.parse(src)
    for target in ("list_active_coupons", "is_coupon_currently_valid"):
        func = next(
            (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == target),
            None,
        )
        assert func is not None, f"function {target} missing"
        body_src = ast.unparse(func)
        # The inlined expression should test `.active` and `.expires_on >= ` on the same identifier.
        assert ".active" in body_src and ".expires_on" in body_src and ">=" in body_src, (
            f"{target} body does not contain the inlined predicate; got:\n{body_src}"
        )


def test_list_active_coupons_behavior() -> None:
    from ecom.coupons import (
        Coupon,
        CouponType,
        clear_coupons,
        list_active_coupons,
        register_coupon,
    )

    clear_coupons()
    today = date(2026, 5, 21)
    active = Coupon(
        code="GOOD",
        coupon_type=CouponType.PERCENTAGE,
        value=10.0,
        expires_on=today + timedelta(days=5),
    )
    expired = Coupon(
        code="OLD",
        coupon_type=CouponType.PERCENTAGE,
        value=10.0,
        expires_on=today - timedelta(days=1),
    )
    inactive = Coupon(
        code="OFF",
        coupon_type=CouponType.PERCENTAGE,
        value=10.0,
        expires_on=today + timedelta(days=5),
        active=False,
    )
    no_expiry = Coupon(code="EVERGREEN", coupon_type=CouponType.PERCENTAGE, value=10.0)
    for c in (active, expired, inactive, no_expiry):
        register_coupon(c)
    out = list_active_coupons(today)
    codes = {c.code for c in out}
    assert codes == {"GOOD"}, f"unexpected active set: {codes}"
    clear_coupons()


def test_is_coupon_currently_valid_behavior() -> None:
    from ecom.coupons import (
        Coupon,
        CouponType,
        clear_coupons,
        is_coupon_currently_valid,
        register_coupon,
    )

    clear_coupons()
    today = date(2026, 5, 21)
    register_coupon(
        Coupon(
            code="GOOD",
            coupon_type=CouponType.PERCENTAGE,
            value=10.0,
            expires_on=today + timedelta(days=5),
        )
    )
    register_coupon(
        Coupon(
            code="OLD",
            coupon_type=CouponType.PERCENTAGE,
            value=10.0,
            expires_on=today - timedelta(days=1),
        )
    )
    assert is_coupon_currently_valid("GOOD", today) is True
    assert is_coupon_currently_valid("OLD", today) is False
    assert is_coupon_currently_valid("MISSING", today) is False
    clear_coupons()
