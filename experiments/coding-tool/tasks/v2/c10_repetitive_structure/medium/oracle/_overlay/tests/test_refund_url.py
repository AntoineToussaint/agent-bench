"""Oracle for c10_repetitive_structure / medium — add refund_url to send_cancellation only."""

from ecom.models import Order, OrderLine, Product, User
from ecom.notifications import (
    send_cancellation,
    send_order_confirmation,
    send_shipping_update,
)


def _order(order_id: int = 42) -> Order:
    user = User(user_id=1, email="a@b.com", name="A")
    product = Product(product_id=1, name="Widget", unit_price=10.0, weight_kg=1.0)
    return Order(
        order_id=order_id,
        user=user,
        lines=[OrderLine(product=product, quantity=2)],
    )


EXPECTED_KEYS = {"to", "subject", "body", "reply_to"}


def test_cancellation_includes_refund_url() -> None:
    payload = send_cancellation(_order(order_id=42))
    assert "refund_url" in payload
    assert payload["refund_url"] == "https://example.com/refund/42"


def test_cancellation_keeps_other_keys() -> None:
    payload = send_cancellation(_order())
    assert EXPECTED_KEYS.issubset(payload.keys())


def test_confirmation_unchanged() -> None:
    payload = send_order_confirmation(_order())
    assert "refund_url" not in payload
    assert set(payload.keys()) == EXPECTED_KEYS


def test_shipping_unchanged() -> None:
    payload = send_shipping_update(_order())
    assert "refund_url" not in payload
    assert set(payload.keys()) == EXPECTED_KEYS


def test_cancellation_refund_url_uses_order_id() -> None:
    payload = send_cancellation(_order(order_id=999))
    assert payload["refund_url"].endswith("/999")
