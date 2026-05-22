"""Oracle for c10_repetitive_structure / large — add REDEEM_LOYALTY to customer role only."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_redeem_loyalty_enum_value_exists() -> None:
    from ecom.auth import Permission

    assert hasattr(Permission, "REDEEM_LOYALTY")
    # It must be a real Permission member (str-Enum), with a sensible value.
    perm = Permission.REDEEM_LOYALTY
    assert isinstance(perm, Permission)
    assert perm.value == "redeem_loyalty"


def test_customer_has_redeem_loyalty() -> None:
    from ecom.auth import Permission, ROLE_PERMISSIONS

    assert Permission.REDEEM_LOYALTY in ROLE_PERMISSIONS["customer"]


def test_staff_does_not_have_redeem_loyalty() -> None:
    from ecom.auth import Permission, ROLE_PERMISSIONS

    assert Permission.REDEEM_LOYALTY not in ROLE_PERMISSIONS["staff"]


def test_staff_explicit_listing_does_not_mention_redeem_loyalty() -> None:
    # The staff entry in auth.py must not explicitly mention REDEEM_LOYALTY in
    # its set literal. We isolate the "staff": frozenset({...}) block and grep
    # within it.
    src = (ROOT / "ecom" / "auth.py").read_text(encoding="utf-8")
    m = re.search(
        r'"staff"\s*:\s*frozenset\s*\(\s*\{([^}]*)\}\s*\)',
        src,
        re.DOTALL,
    )
    assert m, "expected to find the staff role's explicit permission set"
    staff_block = m.group(1)
    assert "REDEEM_LOYALTY" not in staff_block, (
        "REDEEM_LOYALTY must not be added to the staff role's explicit permissions"
    )


def test_customer_still_has_original_permissions() -> None:
    # Don't accidentally drop the customer's existing perms.
    from ecom.auth import Permission, ROLE_PERMISSIONS

    cust = ROLE_PERMISSIONS["customer"]
    assert Permission.VIEW_ORDER in cust
    assert Permission.CREATE_ORDER in cust
    assert Permission.APPLY_COUPON in cust
