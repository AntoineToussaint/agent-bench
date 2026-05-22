"""Oracle for c02_multi_site / large — support@ -> help@ across all sites."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))

OLD = "support@example.com"
NEW = "help@example.com"

SITES = (
    "ecom/notifications.py",
    "ecom/app.py",
    "tests/test_orders.py",
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_old_email_gone_from_every_site() -> None:
    for rel in SITES:
        assert OLD not in _read(rel), f"old email still present in {rel}"


def test_new_email_present_at_every_site() -> None:
    for rel in SITES:
        assert NEW in _read(rel), f"new email missing from {rel}"


def test_old_email_gone_from_entire_project() -> None:
    leftovers = []
    for p in ROOT.rglob("*.py"):
        if "__pycache__" in p.parts or "_overlay" in p.parts:
            continue
        if OLD in p.read_text(encoding="utf-8"):
            leftovers.append(str(p.relative_to(ROOT)))
    assert not leftovers, f"old email still referenced in: {leftovers}"


def test_support_email_constant_uses_new_value() -> None:
    from ecom.notifications import SUPPORT_EMAIL

    assert SUPPORT_EMAIL == NEW


def test_route_support_contact_returns_new_email() -> None:
    from ecom.app import route_support_contact

    assert route_support_contact() == {"email": NEW}


def test_notification_payload_uses_new_reply_to() -> None:
    from ecom.models import Order, OrderLine, Product, User
    from ecom.notifications import (
        send_cancellation,
        send_order_confirmation,
        send_shipping_update,
    )

    user = User(user_id=1, email="a@b.com", name="A")
    product = Product(product_id=1, name="W", unit_price=10.0, weight_kg=1.0)
    order = Order(order_id=1, user=user, lines=[OrderLine(product=product, quantity=1)])
    for fn in (send_order_confirmation, send_shipping_update, send_cancellation):
        assert fn(order)["reply_to"] == NEW
