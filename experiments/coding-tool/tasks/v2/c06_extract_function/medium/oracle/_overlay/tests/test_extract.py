"""Oracle for c06_extract_function / medium — extract `_build_payload`."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


SUPPORT_EMAIL = "support@example.com"


def _make_order():
    from ecom.models import Order, OrderLine, Product, User

    user = User(user_id=42, email="a@b.com", name="Alice")
    product = Product(product_id=1, name="Widget", unit_price=10.0, weight_kg=1.0)
    return Order(
        order_id=7,
        user=user,
        lines=[OrderLine(product=product, quantity=3)],
    )


def _function_statement_count(func_name: str) -> int:
    src = (ROOT / "ecom" / "notifications.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return len(node.body)
    raise AssertionError(f"{func_name} not found in ecom/notifications.py")


def test_helper_exists_and_callable() -> None:
    from ecom import notifications

    assert hasattr(notifications, "_build_payload")
    assert callable(notifications._build_payload)


def test_confirmation_payload_byte_for_byte_preserved() -> None:
    from ecom.notifications import send_order_confirmation

    payload = send_order_confirmation(_make_order())
    assert payload == {
        "to": "a@b.com",
        "subject": "Order #7 confirmed",
        "body": "Thanks Alice, your order is on its way.",
        "reply_to": SUPPORT_EMAIL,
    }


def test_shipping_payload_byte_for_byte_preserved() -> None:
    from ecom.notifications import send_shipping_update

    payload = send_shipping_update(_make_order())
    assert payload == {
        "to": "a@b.com",
        "subject": "Order #7 shipped",
        "body": "Hi Alice, your order is on the way.",
        "reply_to": SUPPORT_EMAIL,
    }


def test_cancellation_payload_byte_for_byte_preserved() -> None:
    from ecom.notifications import send_cancellation

    payload = send_cancellation(_make_order())
    assert payload == {
        "to": "a@b.com",
        "subject": "Order #7 cancelled",
        "body": "Hi Alice, your order has been cancelled.",
        "reply_to": SUPPORT_EMAIL,
    }


def test_each_send_function_is_short() -> None:
    for name in ("send_order_confirmation", "send_shipping_update", "send_cancellation"):
        count = _function_statement_count(name)
        assert count <= 3, (
            f"{name} should be ≤ 3 statements after extraction, got {count}"
        )


def test_helper_called_from_each_sender() -> None:
    src = (ROOT / "ecom" / "notifications.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for name in ("send_order_confirmation", "send_shipping_update", "send_cancellation"):
        func = next(
            n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name
        )
        names = {
            node.func.id
            for node in ast.walk(func)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "_build_payload" in names, (
            f"{name} must delegate payload construction to _build_payload"
        )
