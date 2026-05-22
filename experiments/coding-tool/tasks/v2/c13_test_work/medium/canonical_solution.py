"""Canonical solution for c13_test_work / medium."""

from __future__ import annotations

from pathlib import Path


ADDITIONS = '''

def test_cancel_already_cancelled() -> None:
    order = _setup()
    create_order(order)
    cancel_order(order.order_id)
    cancel_order(order.order_id)
    assert repo.get_order(order.order_id).status == "cancelled"


def test_cancel_sends_cancellation_email() -> None:
    from ecom.notifications import send_cancellation

    order = _setup()
    create_order(order)
    cancel_order(order.order_id)
    payload = send_cancellation(repo.get_order(order.order_id))
    assert "cancelled" in payload["subject"]


def test_cancel_missing_order_raises() -> None:
    repo.orders.clear()
    import pytest

    with pytest.raises(KeyError):
        cancel_order(999)
'''


def apply(workdir: Path) -> None:
    p = workdir / "tests" / "test_orders.py"
    text = p.read_text(encoding="utf-8")
    if "def test_cancel_already_cancelled" in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    p.write_text(text + ADDITIONS, encoding="utf-8")
