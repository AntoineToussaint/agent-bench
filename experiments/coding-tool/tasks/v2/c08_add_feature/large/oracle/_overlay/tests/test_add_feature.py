"""Oracle tests for c08_add_feature / large — loyalty-points feature."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _reset_loyalty():
    from ecom import loyalty

    loyalty._loyalty.clear()
    yield
    loyalty._loyalty.clear()


def test_loyalty_account_dataclass_exists() -> None:
    from ecom.models import LoyaltyAccount

    account = LoyaltyAccount(user_id=7)
    assert account.user_id == 7
    assert account.points == 0


def test_add_and_get_balance() -> None:
    from ecom import loyalty

    assert loyalty.get_balance(1) == 0
    loyalty.add_points(1, 50)
    assert loyalty.get_balance(1) == 50
    loyalty.add_points(1, 25)
    assert loyalty.get_balance(1) == 75


def test_redeem_subtracts_and_returns() -> None:
    from ecom import loyalty

    loyalty.add_points(1, 100)
    redeemed = loyalty.redeem(1, 30)
    assert redeemed == 30
    assert loyalty.get_balance(1) == 70


def test_redeem_insufficient_raises() -> None:
    from ecom import loyalty

    loyalty.add_points(1, 10)
    with pytest.raises(ValueError):
        loyalty.redeem(1, 100)


def test_redeem_unknown_user_raises() -> None:
    from ecom import loyalty

    with pytest.raises(ValueError):
        loyalty.redeem(999, 5)


def test_route_redeem_points_end_to_end() -> None:
    from ecom import app, loyalty

    loyalty.add_points(42, 200)
    result = app.route_redeem_points(42, 75)
    assert result == {"user_id": 42, "redeemed": 75, "balance": 125}
    assert loyalty.get_balance(42) == 125
