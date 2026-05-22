"""Oracle for c12_hygiene / medium."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def _reload_orders():
    for name in list(sys.modules):
        if name.startswith("ecom"):
            del sys.modules[name]
    from ecom import orders  # noqa: WPS433
    return orders


def test_order_not_found_error_defined() -> None:
    orders = _reload_orders()
    assert hasattr(orders, "OrderNotFoundError"), (
        "OrderNotFoundError must be defined in ecom.orders"
    )
    assert issubclass(orders.OrderNotFoundError, Exception)


def test_logger_defined_at_module_level() -> None:
    orders = _reload_orders()
    import logging
    assert hasattr(orders, "logger")
    assert isinstance(orders.logger, logging.Logger)


def test_ship_order_missing_raises_order_not_found() -> None:
    orders = _reload_orders()
    from ecom.repository import repo
    repo.orders.clear()
    with pytest.raises(orders.OrderNotFoundError):
        orders.ship_order(999)


def test_cancel_order_missing_raises_order_not_found() -> None:
    orders = _reload_orders()
    from ecom.repository import repo
    repo.orders.clear()
    with pytest.raises(orders.OrderNotFoundError):
        orders.cancel_order(999)


def test_add_line_missing_raises_order_not_found() -> None:
    orders = _reload_orders()
    from ecom.models import OrderLine, Product
    from ecom.repository import repo
    repo.orders.clear()
    product = Product(product_id=1, name="X", unit_price=1.0, weight_kg=1.0)
    with pytest.raises(orders.OrderNotFoundError):
        orders.add_line(999, OrderLine(product=product, quantity=1))


def test_missing_raises_not_bare_keyerror() -> None:
    orders = _reload_orders()
    from ecom.repository import repo
    repo.orders.clear()
    try:
        orders.ship_order(12345)
    except orders.OrderNotFoundError:
        pass
    except KeyError:
        pytest.fail("ship_order raised KeyError instead of OrderNotFoundError")
