"""Regression tests for orders + notifications + repository wiring."""

from ecom.models import Order, OrderLine, Product, User
from ecom.notifications import send_order_confirmation
from ecom.orders import cancel_order, create_order, ship_order
from ecom.repository import repo


def _setup() -> Order:
    repo.users.clear()
    repo.products.clear()
    repo.orders.clear()
    user = User(user_id=1, email="a@b.com", name="A")
    product = Product(product_id=1, name="Widget", unit_price=10.0, weight_kg=1.0)
    repo.users[1] = user
    repo.products[1] = product
    return Order(
        order_id=1,
        user=user,
        lines=[OrderLine(product=product, quantity=3)],
    )


def test_create_order_persists_and_returns_total() -> None:
    order = _setup()
    total = create_order(order)
    assert order.order_id in repo.orders
    assert total > 0
    assert any(n.startswith("total=") for n in order.notes)


def test_ship_order_sets_status() -> None:
    order = _setup()
    create_order(order)
    ship_order(order.order_id)
    assert repo.get_order(order.order_id).status == "shipped"


def test_cancel_order_sets_status() -> None:
    order = _setup()
    create_order(order)
    cancel_order(order.order_id)
    assert repo.get_order(order.order_id).status == "cancelled"


def test_notification_payload_shape() -> None:
    order = _setup()
    payload = send_order_confirmation(order)
    assert payload["to"] == "a@b.com"
    assert "confirmed" in payload["subject"]
    assert payload["reply_to"] == "support@example.com"
