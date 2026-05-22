"""Canonical solution for c10_repetitive_structure / medium."""

from __future__ import annotations

from pathlib import Path


def apply(workdir: Path) -> None:
    p = workdir / "ecom" / "notifications.py"
    text = p.read_text(encoding="utf-8")

    old = (
        'def send_cancellation(order: Order) -> dict:\n'
        '    print(f"sending cancellation to {order.user.email}")\n'
        '    return {\n'
        '        "to": order.user.email,\n'
        '        "subject": f"Order #{order.order_id} cancelled",\n'
        '        "body": f"Hi {order.user.name}, your order has been cancelled.",\n'
        '        "reply_to": SUPPORT_EMAIL,\n'
        '    }\n'
    )
    new = (
        'def send_cancellation(order: Order) -> dict:\n'
        '    print(f"sending cancellation to {order.user.email}")\n'
        '    return {\n'
        '        "to": order.user.email,\n'
        '        "subject": f"Order #{order.order_id} cancelled",\n'
        '        "body": f"Hi {order.user.name}, your order has been cancelled.",\n'
        '        "reply_to": SUPPORT_EMAIL,\n'
        '        "refund_url": f"https://example.com/refund/{order.order_id}",\n'
        '    }\n'
    )
    assert old in text, "expected send_cancellation in known shape"
    p.write_text(text.replace(old, new), encoding="utf-8")
