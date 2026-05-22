"""Oracle tests for c08_add_feature / medium — refund feature."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


def _setup_order():
    from ecom.models import Order, OrderLine, Product, User
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
        lines=[OrderLine(product=product, quantity=2)],
    )
    repo.save_order(order)
    return order


def test_refund_order_sets_status_and_note() -> None:
    from ecom import orders as orders_mod
    from ecom.repository import repo

    order = _setup_order()
    orders_mod.refund_order(order.order_id, "damaged")
    refreshed = repo.get_order(order.order_id)
    assert refreshed.status == "refunded"
    assert any(n == "refund_reason=damaged" for n in refreshed.notes)


def test_refund_order_keeps_order_in_repo() -> None:
    from ecom import orders as orders_mod
    from ecom.repository import repo

    order = _setup_order()
    orders_mod.refund_order(order.order_id, "lost")
    assert order.order_id in repo.orders


def test_route_refund_returns_expected_dict() -> None:
    from ecom import app

    order = _setup_order()
    result = app.route_refund(order.order_id, "damaged")
    assert result == {
        "order_id": order.order_id,
        "status": "refunded",
        "reason": "damaged",
    }


def test_route_refund_persists_status() -> None:
    from ecom import app
    from ecom.repository import repo

    order = _setup_order()
    app.route_refund(order.order_id, "wrong size")
    assert repo.get_order(order.order_id).status == "refunded"


def test_refund_order_is_importable_directly() -> None:
    from ecom.orders import refund_order  # noqa: F401

    assert callable(refund_order)
