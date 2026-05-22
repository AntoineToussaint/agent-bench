"""Oracle for c05_api_migration / large — migrate ecom prints to logger."""

import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))

PRINT_RE = re.compile(r"\bprint\(")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_no_print_calls_anywhere_in_ecom() -> None:
    for p in (ROOT / "ecom").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(ROOT)
        assert not PRINT_RE.search(p.read_text(encoding="utf-8")), (
            f"{rel} still uses print()"
        )


def test_notifications_has_module_logger() -> None:
    src = _read("ecom/notifications.py")
    assert "import logging" in src
    assert re.search(r"logger\s*=\s*logging\.getLogger\(__name__\)", src)


def test_setup_logging_is_callable() -> None:
    import importlib

    import ecom

    importlib.reload(ecom)
    assert hasattr(ecom, "setup_logging"), "ecom.setup_logging must exist"
    assert callable(ecom.setup_logging)
    # Calling it must not raise
    ecom.setup_logging()


def test_send_order_confirmation_payload_unchanged() -> None:
    from ecom.models import Order, OrderLine, Product, User
    from ecom.notifications import send_order_confirmation

    user = User(user_id=1, email="a@b.com", name="A")
    p = Product(product_id=1, name="Widget", unit_price=10.0, weight_kg=1.0)
    order = Order(order_id=7, user=user, lines=[OrderLine(product=p, quantity=2)])

    payload = send_order_confirmation(order)
    assert payload["to"] == "a@b.com"
    assert "confirmed" in payload["subject"]
    assert "7" in payload["subject"]
    assert payload["reply_to"] == "support@example.com"


def test_log_records_emitted_when_sending(caplog) -> None:
    import importlib

    import ecom.notifications as notifications

    importlib.reload(notifications)
    caplog.set_level(logging.INFO, logger="ecom.notifications")

    from ecom.models import Order, OrderLine, Product, User

    user = User(user_id=1, email="caplog@example.com", name="C")
    p = Product(product_id=1, name="X", unit_price=1.0, weight_kg=0.1)
    order = Order(order_id=1, user=user, lines=[OrderLine(product=p, quantity=1)])

    notifications.send_order_confirmation(order)
    notifications.send_shipping_update(order)
    notifications.send_cancellation(order)
    messages = [r.getMessage() for r in caplog.records]
    assert any("caplog@example.com" in m for m in messages)
    # one record per send_ call
    relevant = [m for m in messages if "caplog@example.com" in m]
    assert len(relevant) >= 3
