"""Canonical solution for c10_repetitive_structure / large."""

from __future__ import annotations

from pathlib import Path


def apply(workdir: Path) -> None:
    p = workdir / "ecom" / "auth.py"
    text = p.read_text(encoding="utf-8")

    # 1) Add REDEEM_LOYALTY to the Permission enum (after MANAGE_USERS).
    old_enum = '    MANAGE_USERS = "manage_users"\n'
    new_enum = (
        '    MANAGE_USERS = "manage_users"\n'
        '    REDEEM_LOYALTY = "redeem_loyalty"\n'
    )
    assert old_enum in text, "expected MANAGE_USERS line in Permission enum"
    text = text.replace(old_enum, new_enum)

    # 2) Add REDEEM_LOYALTY to the customer role's explicit set.
    old_customer = (
        '    "customer": frozenset(\n'
        '        {\n'
        '            Permission.VIEW_ORDER,\n'
        '            Permission.CREATE_ORDER,\n'
        '            Permission.APPLY_COUPON,\n'
        '        }\n'
        '    ),\n'
    )
    new_customer = (
        '    "customer": frozenset(\n'
        '        {\n'
        '            Permission.VIEW_ORDER,\n'
        '            Permission.CREATE_ORDER,\n'
        '            Permission.APPLY_COUPON,\n'
        '            Permission.REDEEM_LOYALTY,\n'
        '        }\n'
        '    ),\n'
    )
    assert old_customer in text, "expected customer role entry in known shape"
    text = text.replace(old_customer, new_customer)

    p.write_text(text, encoding="utf-8")
