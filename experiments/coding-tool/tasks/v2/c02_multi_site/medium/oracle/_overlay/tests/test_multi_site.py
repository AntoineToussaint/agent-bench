"""Oracle for c02_multi_site / medium — outbox prefix on notification prints."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))

NOTIFICATIONS = ROOT / "ecom" / "notifications.py"


def _read() -> str:
    return NOTIFICATIONS.read_text(encoding="utf-8")


def test_all_three_print_calls_have_outbox_prefix() -> None:
    src = _read()
    # Expect exactly three notification prints, all carrying the [outbox] prefix.
    matches = re.findall(r'print\(f"\[outbox\] sending ([a-z ]+) to \{order\.user\.email\}"\)', src)
    assert sorted(matches) == ["cancellation", "order confirmation", "shipping update"], matches


def test_no_print_in_notifications_is_missing_the_prefix() -> None:
    src = _read()
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("print("):
            assert "[outbox] " in stripped, f"print without [outbox] prefix: {stripped!r}"


def test_function_signatures_preserved() -> None:
    src = _read()
    for sig in (
        "def send_order_confirmation(order: Order) -> dict:",
        "def send_shipping_update(order: Order) -> dict:",
        "def send_cancellation(order: Order) -> dict:",
    ):
        assert sig in src, f"missing signature: {sig}"


def test_payload_dicts_unchanged() -> None:
    from ecom.models import Order, OrderLine, Product, User
    from ecom.notifications import (
        SUPPORT_EMAIL,
        send_cancellation,
        send_order_confirmation,
        send_shipping_update,
    )

    user = User(user_id=1, email="a@b.com", name="A")
    product = Product(product_id=1, name="Widget", unit_price=10.0, weight_kg=1.0)
    order = Order(order_id=7, user=user, lines=[OrderLine(product=product, quantity=1)])

    payload = send_order_confirmation(order)
    assert payload == {
        "to": "a@b.com",
        "subject": "Order #7 confirmed",
        "body": "Thanks A, your order is on its way.",
        "reply_to": SUPPORT_EMAIL,
    }
    payload = send_shipping_update(order)
    assert payload == {
        "to": "a@b.com",
        "subject": "Order #7 shipped",
        "body": "Hi A, your order is on the way.",
        "reply_to": SUPPORT_EMAIL,
    }
    payload = send_cancellation(order)
    assert payload == {
        "to": "a@b.com",
        "subject": "Order #7 cancelled",
        "body": "Hi A, your order has been cancelled.",
        "reply_to": SUPPORT_EMAIL,
    }
