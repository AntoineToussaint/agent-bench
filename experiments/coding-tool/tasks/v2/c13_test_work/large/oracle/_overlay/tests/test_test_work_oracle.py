"""Oracle for c13_test_work / large."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _src() -> str:
    return (ROOT / "tests" / "test_coupons.py").read_text(encoding="utf-8")


def test_test_min_order_amount_blocks_below_defined() -> None:
    assert re.search(r"\bdef test_coupon_min_order_amount_blocks_below\b", _src())


def test_test_usage_cap_exhausted_defined() -> None:
    assert re.search(r"\bdef test_coupon_usage_cap_exhausted\b", _src())


def test_test_free_shipping_combines_defined() -> None:
    assert re.search(
        r"\bdef test_apply_coupon_free_shipping_combines_with_subtotal\b", _src()
    )


def test_test_register_coupon_roundtrip_defined() -> None:
    assert re.search(r"\bdef test_register_coupon_roundtrip\b", _src())


def test_pytest_collects_at_least_ten_tests() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/test_coupons.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"pytest --collect-only failed:\n{proc.stdout}\n{proc.stderr}"
    )
    test_lines = [
        line for line in proc.stdout.splitlines()
        if "test_coupons.py::" in line
    ]
    # Base file has 6 tests; oracle requires 4 more = 10 minimum.
    assert len(test_lines) >= 10, (
        f"expected at least 10 tests in test_coupons.py, got {len(test_lines)}:\n"
        + "\n".join(test_lines)
    )


def test_existing_tests_unchanged() -> None:
    src = _src()
    for name in (
        "test_percentage_coupon_reduces_total",
        "test_fixed_coupon_subtracts_amount",
        "test_free_shipping_coupon_zeroes_shipping",
        "test_expired_coupon_raises",
        "test_min_order_amount_enforced",
        "test_register_and_get_coupon_roundtrip",
    ):
        assert re.search(rf"\bdef {name}\b", src), f"original {name} was removed"
