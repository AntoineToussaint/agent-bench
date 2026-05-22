"""Oracle for c07_inline_function / medium — inline `_percent`."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


def _read() -> str:
    return (ROOT / "ecom" / "pricing.py").read_text(encoding="utf-8")


def test_percent_helper_is_gone() -> None:
    from ecom import pricing

    assert not hasattr(pricing, "_percent"), "_percent must be removed from the module"


def test_no_percent_def_remains() -> None:
    src = _read()
    assert not re.search(r"^def _percent\b", src, re.MULTILINE), (
        "_percent definition must be deleted"
    )


def test_no_percent_call_remains() -> None:
    src = _read()
    assert not re.search(r"\b_percent\s*\(", src), (
        "no call to _percent should remain in pricing.py"
    )


def test_apply_discount_behavior_preserved() -> None:
    from ecom.pricing import apply_discount

    assert apply_discount(100.0, 10.0) == 90.0
    assert apply_discount(200.0, 25.0) == 150.0
    assert apply_discount(50.0, 0.0) == 50.0


def test_apply_discount_still_validates() -> None:
    import pytest

    from ecom.pricing import apply_discount

    with pytest.raises(ValueError):
        apply_discount(100.0, -1.0)
    with pytest.raises(ValueError):
        apply_discount(100.0, 999.0)


def test_other_pricing_helpers_untouched() -> None:
    src = _read()
    assert "def apply_tax" in src
    assert "def apply_shipping" in src
    assert "def compute_total" in src
    assert "def estimate_savings" in src
