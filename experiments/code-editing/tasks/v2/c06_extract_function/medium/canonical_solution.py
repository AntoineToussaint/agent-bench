"""Canonical solution for c06_extract_function / medium."""

from __future__ import annotations

from pathlib import Path


NEW_NOTIFICATIONS = '''"""Customer notifications.

Intentional shape: three near-identical handlers (`send_order_confirmation`,
`send_shipping_update`, `send_cancellation`). Naive find-and-replace can't
target one of them without disambiguation context — they share the same
boilerplate.
"""

from __future__ import annotations

from ecom.models import Order


SUPPORT_EMAIL = "support@example.com"


def _build_payload(order: Order, subject_template: str, body_template: str) -> dict:
    return {
        "to": order.user.email,
        "subject": subject_template.format(order_id=order.order_id),
        "body": body_template.format(name=order.user.name),
        "reply_to": SUPPORT_EMAIL,
    }


def send_order_confirmation(order: Order) -> dict:
    print(f"sending order confirmation to {order.user.email}")
    return _build_payload(
        order,
        "Order #{order_id} confirmed",
        "Thanks {name}, your order is on its way.",
    )


def send_shipping_update(order: Order) -> dict:
    print(f"sending shipping update to {order.user.email}")
    return _build_payload(
        order,
        "Order #{order_id} shipped",
        "Hi {name}, your order is on the way.",
    )


def send_cancellation(order: Order) -> dict:
    print(f"sending cancellation to {order.user.email}")
    return _build_payload(
        order,
        "Order #{order_id} cancelled",
        "Hi {name}, your order has been cancelled.",
    )
'''


def apply(workdir: Path) -> None:
    (workdir / "ecom" / "notifications.py").write_text(
        NEW_NOTIFICATIONS, encoding="utf-8"
    )
