"""Oracle tests for c03_xfile_rename / small."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


def test_new_name_exists() -> None:
    import utils

    assert hasattr(utils, "double_value"), "utils.double_value must exist"
    assert utils.double_value(5) == 10


def test_old_name_removed() -> None:
    import utils

    assert not hasattr(utils, "helper"), "old `helper` must be removed"


def test_main_uses_new_name() -> None:
    src = (ROOT / "main.py").read_text()
    assert not re.search(r"\bhelper\b", src), "main.py must not reference old name"
    assert "double_value" in src, "main.py must reference new name"


def test_quadruple_still_works() -> None:
    import utils

    assert utils.quadruple(3) == 12
