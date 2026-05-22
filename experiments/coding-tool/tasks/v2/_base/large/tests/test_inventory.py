"""Tests for the inventory module."""

import pytest

from ecom.inventory import (
    InventoryError,
    Stock,
    clear_stock,
    fulfill,
    get_stock,
    low_stock_alerts,
    register_stock,
    release,
    reserve,
    restock,
)


def setup_function() -> None:
    clear_stock()


def test_reserve_decrements_available() -> None:
    register_stock(Stock(product_id=1, on_hand=10, reorder_threshold=2))
    reserve(1, 3)
    stock = get_stock(1)
    assert stock.reserved == 3
    assert stock.available == 7


def test_reserve_insufficient_raises() -> None:
    register_stock(Stock(product_id=1, on_hand=2))
    with pytest.raises(InventoryError):
        reserve(1, 5)


def test_release_returns_units_to_available() -> None:
    register_stock(Stock(product_id=1, on_hand=10))
    reserve(1, 4)
    release(1, 4)
    stock = get_stock(1)
    assert stock.reserved == 0
    assert stock.available == 10


def test_release_more_than_reserved_raises() -> None:
    register_stock(Stock(product_id=1, on_hand=10))
    reserve(1, 2)
    with pytest.raises(InventoryError):
        release(1, 5)


def test_fulfill_consumes_reserved_and_on_hand() -> None:
    register_stock(Stock(product_id=1, on_hand=10))
    reserve(1, 3)
    fulfill(1, 3)
    stock = get_stock(1)
    assert stock.on_hand == 7
    assert stock.reserved == 0


def test_low_stock_alerts_lists_below_threshold() -> None:
    register_stock(Stock(product_id=1, on_hand=10, reorder_threshold=3))
    register_stock(Stock(product_id=2, on_hand=2, reorder_threshold=3))
    register_stock(Stock(product_id=3, on_hand=1, reorder_threshold=3))
    alerts = low_stock_alerts()
    pids = [a.product_id for a in alerts]
    assert 2 in pids and 3 in pids
    assert 1 not in pids
    # sorted by available ascending
    assert alerts[0].available <= alerts[-1].available


def test_restock_increases_on_hand() -> None:
    register_stock(Stock(product_id=1, on_hand=0))
    restock(1, 5)
    assert get_stock(1).on_hand == 5
