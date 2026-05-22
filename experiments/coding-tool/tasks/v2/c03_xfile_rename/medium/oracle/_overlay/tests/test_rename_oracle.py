"""Oracle for c03_xfile_rename / medium — `compute_total` → `calculate_order_total`."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]  # workdir root
OLD = re.compile(r"\bcompute_total\b")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _no_old(rel: str) -> None:
    assert not OLD.search(_read(rel)), f"{rel} still references compute_total as an identifier"


def test_new_name_imported_in_pricing() -> None:
    from ecom import pricing  # noqa: F401
    from ecom.pricing import calculate_order_total

    assert callable(calculate_order_total)


def test_old_name_gone_from_pricing() -> None:
    from ecom import pricing

    assert not hasattr(pricing, "compute_total")


def test_old_name_text_gone_in_source() -> None:
    for rel in ("ecom/pricing.py", "ecom/orders.py", "ecom/app.py"):
        _no_old(rel)


def test_old_name_text_gone_in_existing_tests() -> None:
    _no_old("tests/test_pricing.py")


def test_behavior_preserved() -> None:
    from ecom.models import Order, OrderLine, Product, User
    from ecom.pricing import calculate_order_total

    user = User(user_id=1, email="a@b.com", name="A")
    p = Product(product_id=1, name="W", unit_price=50.0, weight_kg=1.0)
    order = Order(order_id=1, user=user, lines=[OrderLine(product=p, quantity=2)])
    # subtotal=100, tax=108, free shipping -> 108
    assert calculate_order_total(order) == 108.0


def test_unrelated_functions_untouched() -> None:
    src = _read("ecom/pricing.py")
    assert "def apply_discount" in src
    assert "def apply_tax" in src
    assert "def apply_shipping" in src
    assert "def estimate_savings" in src
