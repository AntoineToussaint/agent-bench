"""Oracle for c12_hygiene / large."""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _reload():
    for name in list(sys.modules):
        if name.startswith("ecom"):
            del sys.modules[name]
    from ecom import orders, inventory  # noqa: WPS433
    return orders, inventory


def test_order_error_defined() -> None:
    orders, _ = _reload()
    assert hasattr(orders, "OrderError"), "OrderError must be defined in ecom.orders"
    assert issubclass(orders.OrderError, Exception)


def test_logger_defined() -> None:
    orders, _ = _reload()
    import logging
    assert hasattr(orders, "logger")
    assert isinstance(orders.logger, logging.Logger)


def test_create_order_insufficient_stock_raises_order_error() -> None:
    orders, inventory = _reload()
    from ecom.models import Order, OrderLine, Product, User
    from ecom.repository import repo

    repo.users.clear()
    repo.products.clear()
    repo.orders.clear()
    inventory.clear_stock()

    user = User(user_id=1, email="a@b.com", name="A")
    product = Product(product_id=42, name="Gadget", unit_price=5.0, weight_kg=0.5)
    repo.users[1] = user
    repo.products[42] = product
    # qty=0 will trigger inventory.reserve to raise InventoryError ("must be positive")
    order = Order(
        order_id=1,
        user=user,
        lines=[OrderLine(product=product, quantity=0)],
    )
    with pytest.raises(orders.OrderError):
        orders.create_order(order)


def test_create_order_does_not_raise_inventory_error_directly() -> None:
    orders, inventory = _reload()
    from ecom.models import Order, OrderLine, Product, User
    from ecom.repository import repo

    repo.users.clear()
    repo.products.clear()
    repo.orders.clear()
    inventory.clear_stock()

    user = User(user_id=1, email="a@b.com", name="A")
    product = Product(product_id=42, name="Gadget", unit_price=5.0, weight_kg=0.5)
    repo.users[1] = user
    repo.products[42] = product
    order = Order(
        order_id=1,
        user=user,
        lines=[OrderLine(product=product, quantity=0)],
    )
    try:
        orders.create_order(order)
    except orders.OrderError:
        pass
    except inventory.InventoryError:
        pytest.fail("create_order leaked InventoryError instead of OrderError")


def test_orders_source_references_inventory_error() -> None:
    src = (ROOT / "ecom" / "orders.py").read_text()
    # The model must catch InventoryError somewhere in orders.py
    assert re.search(r"\bInventoryError\b", src), (
        "ecom/orders.py must catch inventory.InventoryError"
    )
