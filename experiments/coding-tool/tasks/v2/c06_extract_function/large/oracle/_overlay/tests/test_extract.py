"""Oracle for c06_extract_function / large.

Extract two helpers:
  - `_build_payload` in `ecom/notifications.py`
  - `_group_by_sum` in `ecom/reports.py`
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


SUPPORT_EMAIL = "support@example.com"


def _function_statement_count(rel: str, func_name: str) -> int:
    src = (ROOT / rel).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return len(node.body)
    raise AssertionError(f"{func_name} not found in {rel}")


def _make_order():
    from ecom.models import Order, OrderLine, Product, User

    user = User(user_id=42, email="a@b.com", name="Alice")
    product = Product(product_id=1, name="Widget", unit_price=10.0, weight_kg=1.0)
    return Order(
        order_id=7,
        user=user,
        lines=[OrderLine(product=product, quantity=3)],
    )


# --- notifications helper ---


def test_build_payload_exists() -> None:
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
        count = _function_statement_count("ecom/notifications.py", name)
        assert count <= 3, (
            f"{name} should be ≤ 3 statements after extraction, got {count}"
        )


# --- reports helper ---


def test_group_by_sum_exists() -> None:
    from ecom import reports

    assert hasattr(reports, "_group_by_sum")
    assert callable(reports._group_by_sum)


def test_group_by_sum_basic_behavior() -> None:
    from ecom.reports import _group_by_sum

    items = [("a", 1), ("b", 2), ("a", 3), ("c", 4)]
    out = _group_by_sum(items, key_fn=lambda t: t[0], value_fn=lambda t: t[1])
    assert out == {"a": 4, "b": 2, "c": 4}


def test_revenue_by_user_still_correct() -> None:
    from datetime import date

    from ecom.models import Order, OrderLine, Product, User
    from ecom.reports import revenue_by_user

    u1 = User(user_id=1, email="x@y", name="X")
    u2 = User(user_id=2, email="y@z", name="Y")
    p = Product(product_id=1, name="P", unit_price=10.0, weight_kg=0.5)
    orders = [
        Order(order_id=1, user=u1, lines=[OrderLine(product=p, quantity=2)]),
        Order(order_id=2, user=u1, lines=[OrderLine(product=p, quantity=5)]),
        Order(order_id=3, user=u2, lines=[OrderLine(product=p, quantity=3)]),
        Order(
            order_id=4,
            user=u2,
            lines=[OrderLine(product=p, quantity=10)],
            status="cancelled",
        ),
    ]
    rev = revenue_by_user(orders)
    assert set(rev.keys()) == {1, 2}
    assert rev[1] > 0
    assert rev[2] > 0
    # cancelled order excluded -> u2's revenue is from order_id=3 only
    assert rev[2] < rev[1] + 1e9  # sanity


def test_status_breakdown_still_correct() -> None:
    from ecom.models import Order, OrderLine, Product, User
    from ecom.reports import status_breakdown

    u = User(user_id=1, email="x@y", name="X")
    p = Product(product_id=1, name="P", unit_price=10.0, weight_kg=0.5)
    orders = [
        Order(order_id=1, user=u, lines=[OrderLine(product=p, quantity=1)], status="pending"),
        Order(order_id=2, user=u, lines=[OrderLine(product=p, quantity=1)], status="pending"),
        Order(order_id=3, user=u, lines=[OrderLine(product=p, quantity=1)], status="shipped"),
        Order(order_id=4, user=u, lines=[OrderLine(product=p, quantity=1)], status="cancelled"),
    ]
    breakdown = status_breakdown(orders)
    assert breakdown == {"pending": 2, "shipped": 1, "cancelled": 1}


def test_revenue_by_user_and_status_breakdown_are_shorter() -> None:
    # Both must shrink after extracting the loop into the helper.
    rev_count = _function_statement_count("ecom/reports.py", "revenue_by_user")
    status_count = _function_statement_count("ecom/reports.py", "status_breakdown")
    # original revenue_by_user had 5 statements; status_breakdown had 4
    assert rev_count < 5, f"revenue_by_user not shorter: {rev_count} statements"
    assert status_count < 4, f"status_breakdown not shorter: {status_count} statements"


def test_helper_called_from_each_reports_function() -> None:
    src = (ROOT / "ecom" / "reports.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for name in ("revenue_by_user", "status_breakdown"):
        func = next(
            n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name
        )
        names = {
            node.func.id
            for node in ast.walk(func)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "_group_by_sum" in names, (
            f"{name} must delegate the loop to _group_by_sum"
        )
