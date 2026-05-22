"""Canonical solution for c08_add_feature / large."""

from __future__ import annotations

from pathlib import Path


LOYALTY_MODEL = '''

@dataclass
class LoyaltyAccount:
    user_id: int
    points: int = 0
'''


LOYALTY_MODULE = '''"""Customer loyalty-point accounts."""

from __future__ import annotations

from ecom.models import LoyaltyAccount


_loyalty: dict[int, LoyaltyAccount] = {}


def _get_or_create(user_id: int) -> LoyaltyAccount:
    if user_id not in _loyalty:
        _loyalty[user_id] = LoyaltyAccount(user_id=user_id)
    return _loyalty[user_id]


def get_balance(user_id: int) -> int:
    return _get_or_create(user_id).points


def add_points(user_id: int, n: int) -> int:
    account = _get_or_create(user_id)
    account.points += n
    return account.points


def redeem(user_id: int, n: int) -> int:
    if user_id not in _loyalty or _loyalty[user_id].points < n:
        raise ValueError(
            f"insufficient points for user {user_id}: requested {n}"
        )
    _loyalty[user_id].points -= n
    return n
'''


ROUTE_FN = '''

def route_redeem_points(user_id: int, points: int) -> dict:
    loyalty.redeem(user_id, points)
    return {
        "user_id": user_id,
        "redeemed": points,
        "balance": loyalty.get_balance(user_id),
    }
'''


def apply(workdir: Path) -> None:
    # 1. Add LoyaltyAccount dataclass to models.py
    models_path = workdir / "ecom" / "models.py"
    text = models_path.read_text(encoding="utf-8")
    if "class LoyaltyAccount" not in text:
        if not text.endswith("\n"):
            text += "\n"
        models_path.write_text(text + LOYALTY_MODEL, encoding="utf-8")

    # 2. Create ecom/loyalty.py
    loyalty_path = workdir / "ecom" / "loyalty.py"
    if not loyalty_path.exists():
        loyalty_path.write_text(LOYALTY_MODULE, encoding="utf-8")

    # 3. Wire route_redeem_points into app.py
    app_path = workdir / "ecom" / "app.py"
    app_text = app_path.read_text(encoding="utf-8")
    if "from ecom import loyalty" not in app_text:
        app_text = app_text.replace(
            "from ecom.coupons import apply_coupon, get_coupon",
            "from ecom import loyalty\nfrom ecom.coupons import apply_coupon, get_coupon",
        )
    if "def route_redeem_points(" not in app_text:
        if not app_text.endswith("\n"):
            app_text += "\n"
        app_text += ROUTE_FN
    app_path.write_text(app_text, encoding="utf-8")
