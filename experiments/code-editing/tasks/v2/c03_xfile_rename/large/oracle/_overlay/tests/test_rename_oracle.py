"""Oracle for c03_xfile_rename / large — `compute_total` → `calculate_order_total`."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]  # workdir root
OLD = re.compile(r"\bcompute_total\b")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _no_old(rel: str) -> None:
    assert not OLD.search(_read(rel)), f"{rel} still references compute_total as an identifier"


def test_new_name_callable() -> None:
    from ecom.pricing import calculate_order_total

    assert callable(calculate_order_total)


def test_old_name_gone_from_pricing_module() -> None:
    from ecom import pricing

    assert not hasattr(pricing, "compute_total")


def test_old_name_text_gone_in_all_source_files() -> None:
    for rel in ("ecom/pricing.py", "ecom/orders.py", "ecom/app.py", "ecom/coupons.py"):
        _no_old(rel)


def test_old_name_text_gone_in_tests() -> None:
    for rel in ("tests/test_pricing.py", "tests/test_coupons.py"):
        _no_old(rel)


def test_behavior_preserved() -> None:
    from ecom.models import Order, OrderLine, Product, User
    from ecom.pricing import calculate_order_total

    user = User(user_id=1, email="a@b.com", name="A")
    p = Product(product_id=1, name="W", unit_price=50.0, weight_kg=1.0)
    order = Order(order_id=1, user=user, lines=[OrderLine(product=p, quantity=2)])
    assert calculate_order_total(order) == 108.0


def test_unrelated_functions_untouched() -> None:
    src = _read("ecom/pricing.py")
    for name in ("apply_discount", "apply_tax", "apply_shipping", "estimate_savings"):
        assert f"def {name}" in src, f"unrelated function {name} was removed"
