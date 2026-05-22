"""Oracle for c01_localized_bug / medium — `apply_shipping` threshold inclusive."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


def test_free_shipping_at_exact_threshold() -> None:
    from ecom.pricing import FREE_SHIPPING_THRESHOLD, apply_shipping

    # At the threshold, no shipping is added (threshold is inclusive).
    assert apply_shipping(FREE_SHIPPING_THRESHOLD, 5.0) == FREE_SHIPPING_THRESHOLD


def test_shipping_charged_just_below_threshold() -> None:
    from ecom.pricing import apply_shipping

    # A penny below the threshold still pays shipping.
    result = apply_shipping(99.99, 5.0)
    assert result > 99.99


def test_shipping_still_free_above_threshold() -> None:
    from ecom.pricing import apply_shipping

    assert apply_shipping(150.0, 5.0) == 150.0


def test_only_apply_shipping_was_changed() -> None:
    src = (ROOT / "ecom" / "pricing.py").read_text(encoding="utf-8")
    # Other pricing functions must remain textually identical to the canonical form.
    assert (
        "def apply_discount(subtotal: float, discount_pct: float) -> float:\n"
        "    if discount_pct < 0 or discount_pct > MAX_DISCOUNT_PCT:\n"
        '        raise ValueError(f"discount_pct out of range: {discount_pct}")\n'
        "    adjustment = subtotal * (discount_pct / 100.0)\n"
        "    return subtotal - adjustment\n"
    ) in src
    assert (
        "def apply_tax(subtotal: float) -> float:\n"
        "    adjustment = subtotal * TAX_RATE\n"
        "    return subtotal + adjustment\n"
    ) in src
    assert (
        "def compute_total(order: Order) -> float:\n"
        "    subtotal = order.subtotal\n"
        "    after_discount = apply_discount(subtotal, order.discount_pct)\n"
        "    after_tax = apply_tax(after_discount)\n"
        "    after_shipping = apply_shipping(after_tax, order.total_weight_kg)\n"
        "    return round(after_shipping, 2)\n"
    ) in src


def test_apply_shipping_uses_inclusive_threshold() -> None:
    src = (ROOT / "ecom" / "pricing.py").read_text(encoding="utf-8")
    assert "if subtotal >= FREE_SHIPPING_THRESHOLD:" in src
    assert "if subtotal > FREE_SHIPPING_THRESHOLD:" not in src
