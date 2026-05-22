"""Oracle for c04_signature_change / medium — add `include_shipping` param."""

import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))

PARAM_RE = re.compile(r"\binclude_shipping\b")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_signature_includes_new_param() -> None:
    from ecom.pricing import compute_total

    sig = inspect.signature(compute_total)
    params = list(sig.parameters)
    assert "include_shipping" in params
    p = sig.parameters["include_shipping"]
    assert p.default is True
    # must come AFTER `order`
    assert params.index("include_shipping") > params.index("order")


def test_skipping_shipping_differs_when_shipping_would_be_charged() -> None:
    from ecom.models import Order, OrderLine, Product, User
    from ecom.pricing import compute_total

    user = User(user_id=1, email="a@b.com", name="A")
    p = Product(product_id=1, name="W", unit_price=20.0, weight_kg=2.0)
    order = Order(
        order_id=1, user=user, lines=[OrderLine(product=p, quantity=2)]
    )
    # subtotal=40, below shipping threshold, weight=4kg
    full = compute_total(order)
    no_ship = compute_total(order, include_shipping=False)
    assert full != no_ship, "expected difference when shipping applies"
    # Shipping is 4kg * 2.50 = 10.0
    assert abs(full - no_ship - 10.0) < 1e-6


def test_default_behaviour_preserved() -> None:
    from ecom.models import Order, OrderLine, Product, User
    from ecom.pricing import compute_total

    user = User(user_id=1, email="a@b.com", name="A")
    p = Product(product_id=1, name="W", unit_price=50.0, weight_kg=1.0)
    order = Order(
        order_id=1, user=user, lines=[OrderLine(product=p, quantity=2)]
    )
    # Same fixture as the regression test: subtotal=100, tax=108, free shipping.
    assert compute_total(order) == 108.0


def test_estimate_savings_passes_include_shipping_false() -> None:
    src = _read("ecom/pricing.py")
    assert "def estimate_savings" in src, "estimate_savings must still exist"
    # The only legitimate site for include_shipping=False inside pricing.py
    # is the comparison call in estimate_savings.
    assert re.search(
        r"compute_total\(\s*order\s*,\s*include_shipping\s*=\s*False\s*\)",
        src,
    ), "estimate_savings must call compute_total with include_shipping=False"


def test_other_callers_unchanged() -> None:
    for rel in ("ecom/orders.py", "ecom/app.py"):
        assert not PARAM_RE.search(_read(rel)), (
            f"{rel} must not mention include_shipping"
        )


def test_unrelated_pricing_helpers_intact() -> None:
    src = _read("ecom/pricing.py")
    for name in ("apply_discount", "apply_tax", "apply_shipping"):
        assert f"def {name}" in src
