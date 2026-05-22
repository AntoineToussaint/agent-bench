"""Oracle tests for c09_remove_sweep / large — inventory module removed."""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


INVENTORY_REF = re.compile(r"\binventory\.")


def test_inventory_module_file_deleted() -> None:
    assert not (ROOT / "ecom" / "inventory.py").exists()


def test_inventory_test_file_deleted() -> None:
    assert not (ROOT / "tests" / "test_inventory.py").exists()


def test_inventory_not_importable() -> None:
    # Ensure no stale .pyc/module ends up resolvable
    sys.modules.pop("ecom.inventory", None)
    with pytest.raises(ImportError):
        import ecom.inventory  # noqa: F401


def test_no_inventory_references_under_ecom() -> None:
    for path in (ROOT / "ecom").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        assert not INVENTORY_REF.search(src), (
            f"{path.relative_to(ROOT)} still references inventory."
        )


def test_orders_no_ensure_capacity_helper() -> None:
    src = (ROOT / "ecom" / "orders.py").read_text(encoding="utf-8")
    assert "_ensure_capacity" not in src
    assert "DEFAULT_STOCK_BUFFER" not in src


def test_create_and_cancel_order_still_work() -> None:
    from ecom.models import Order, OrderLine, Product, User
    from ecom.orders import cancel_order, create_order
    from ecom.repository import repo

    repo.users.clear()
    repo.products.clear()
    repo.orders.clear()
    user = User(user_id=1, email="a@b.com", name="A")
    product = Product(product_id=1, name="Widget", unit_price=10.0, weight_kg=1.0)
    repo.users[1] = user
    repo.products[1] = product
    order = Order(
        order_id=1,
        user=user,
        lines=[OrderLine(product=product, quantity=3)],
    )
    total = create_order(order)
    assert total > 0
    assert order.order_id in repo.orders
    cancel_order(order.order_id)
    assert repo.get_order(order.order_id).status == "cancelled"
