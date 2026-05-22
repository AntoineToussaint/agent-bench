"""Oracle tests for c09_remove_sweep / medium — shipping sweep."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


SHIPPING_TOKENS = (
    re.compile(r"\bapply_shipping\b"),
    re.compile(r"\bSHIPPING_PER_KG\b"),
    re.compile(r"\bFREE_SHIPPING_THRESHOLD\b"),
)


def test_apply_shipping_removed() -> None:
    from ecom import pricing

    assert not hasattr(pricing, "apply_shipping")
    assert not hasattr(pricing, "SHIPPING_PER_KG")
    assert not hasattr(pricing, "FREE_SHIPPING_THRESHOLD")


def test_no_shipping_tokens_in_sources() -> None:
    targets = list((ROOT / "ecom").glob("*.py")) + list(
        (ROOT / "tests").glob("*.py")
    )
    for path in targets:
        src = path.read_text(encoding="utf-8")
        for pat in SHIPPING_TOKENS:
            assert not pat.search(src), (
                f"{path.relative_to(ROOT)} still references {pat.pattern}"
            )


def test_surviving_functions_still_defined() -> None:
    from ecom import pricing

    for name in ("apply_discount", "apply_tax", "compute_total", "estimate_savings"):
        assert hasattr(pricing, name), f"pricing.{name} missing"


def test_compute_total_no_discount_no_shipping() -> None:
    from ecom.models import Order, OrderLine, Product, User
    from ecom.pricing import compute_total

    p = Product(product_id=1, name="W", unit_price=50.0, weight_kg=1.0)
    order = Order(
        order_id=1,
        user=User(user_id=1, email="a@b.com", name="A"),
        lines=[OrderLine(product=p, quantity=2)],
    )
    # subtotal 100, tax 108, no shipping
    assert compute_total(order) == 108.0


def test_compute_total_low_subtotal_no_shipping_added() -> None:
    from ecom.models import Order, OrderLine, Product, User
    from ecom.pricing import compute_total

    # Subtotal $20, weight 1kg — previously this would have added shipping.
    p = Product(product_id=1, name="W", unit_price=20.0, weight_kg=1.0)
    order = Order(
        order_id=1,
        user=User(user_id=1, email="a@b.com", name="A"),
        lines=[OrderLine(product=p, quantity=1)],
    )
    # subtotal 20, tax 21.6, no shipping
    assert compute_total(order) == 21.60


def test_estimate_savings_uses_tax_only_baseline() -> None:
    from ecom.models import Order, OrderLine, Product, User
    from ecom.pricing import estimate_savings

    p = Product(product_id=1, name="W", unit_price=50.0, weight_kg=1.0)
    order = Order(
        order_id=1,
        user=User(user_id=1, email="a@b.com", name="A"),
        lines=[OrderLine(product=p, quantity=2)],
        discount_pct=10.0,
    )
    # no-disc tax-only total = 108. With disc = 97.20. Saved = 10.80
    assert estimate_savings(order) == 10.80
