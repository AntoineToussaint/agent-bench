"""Canonical solution for c08_add_feature / medium."""

from __future__ import annotations

from pathlib import Path


REFUND_FN = '''

def refund_order(order_id: int, reason: str) -> None:
    order = repo.get_order(order_id)
    order.status = "refunded"
    order.notes.append(f"refund_reason={reason}")
    send_cancellation(order)
'''


ROUTE_FN = '''

def route_refund(order_id: int, reason: str) -> dict:
    refund_order(order_id, reason)
    return {"order_id": order_id, "status": "refunded", "reason": reason}
'''


def apply(workdir: Path) -> None:
    orders_path = workdir / "ecom" / "orders.py"
    text = orders_path.read_text(encoding="utf-8")
    if "def refund_order(" not in text:
        if not text.endswith("\n"):
            text += "\n"
        orders_path.write_text(text + REFUND_FN, encoding="utf-8")

    app_path = workdir / "ecom" / "app.py"
    app_text = app_path.read_text(encoding="utf-8")
    # Extend the existing import line so refund_order is in scope.
    old_import = (
        "from ecom.orders import add_line, cancel_order, create_order, ship_order"
    )
    new_import = (
        "from ecom.orders import "
        "add_line, cancel_order, create_order, refund_order, ship_order"
    )
    if old_import in app_text:
        app_text = app_text.replace(old_import, new_import)
    if "def route_refund(" not in app_text:
        if not app_text.endswith("\n"):
            app_text += "\n"
        app_text += ROUTE_FN
    app_path.write_text(app_text, encoding="utf-8")
