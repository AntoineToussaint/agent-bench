"""Customer notifications.

Intentional shape: three near-identical handlers (`send_order_confirmation`,
`send_shipping_update`, `send_cancellation`). Naive find-and-replace can't
target one of them without disambiguation context — they share the same
boilerplate.
"""

from __future__ import annotations

from ecom.models import Order


SUPPORT_EMAIL = "support@example.com"


def send_order_confirmation(order: Order) -> dict:
    print(f"sending order confirmation to {order.user.email}")
    return {
        "to": order.user.email,
        "subject": f"Order #{order.order_id} confirmed",
        "body": f"Thanks {order.user.name}, your order is on its way.",
        "reply_to": SUPPORT_EMAIL,
    }


def send_shipping_update(order: Order) -> dict:
    print(f"sending shipping update to {order.user.email}")
    return {
        "to": order.user.email,
        "subject": f"Order #{order.order_id} shipped",
        "body": f"Hi {order.user.name}, your order is on the way.",
        "reply_to": SUPPORT_EMAIL,
    }


def send_cancellation(order: Order) -> dict:
    print(f"sending cancellation to {order.user.email}")
    return {
        "to": order.user.email,
        "subject": f"Order #{order.order_id} cancelled",
        "body": f"Hi {order.user.name}, your order has been cancelled.",
        "reply_to": SUPPORT_EMAIL,
    }
