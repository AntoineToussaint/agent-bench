"""Oracle for c14_config_code / small."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_config_module_exists() -> None:
    assert (ROOT / "config.py").exists(), "config.py must be created at the workdir root"


def test_config_module_has_constants() -> None:
    # Re-import in case earlier tests cached state
    for mod in ("config", "app"):
        if mod in sys.modules:
            del sys.modules[mod]
    import config
    assert config.TIMEOUT == 30
    assert config.RETRIES == 3
    assert config.BASE_URL == "https://api.example.com"


def test_app_imports_from_config() -> None:
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "config" in src, "app.py must reference the config module"
    assert re.search(r"\bTIMEOUT\b", src), "app.py must use TIMEOUT constant"
    assert re.search(r"\bRETRIES\b", src), "app.py must use RETRIES constant"
    assert re.search(r"\bBASE_URL\b", src), "app.py must use BASE_URL constant"


def test_app_no_magic_numbers() -> None:
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '"https://api.example.com"' not in src, (
        "the literal 'https://api.example.com' must not appear in app.py"
    )
    # Match standalone integer literals 30 and 3 (not inside identifiers)
    assert not re.search(r"(?<![\w.])30(?!\d)", src), (
        "the literal `30` must not appear in app.py"
    )
    assert not re.search(r"(?<![\w.])3(?!\d)", src), (
        "the literal `3` must not appear in app.py"
    )


def test_behavior_preserved() -> None:
    for mod in ("config", "app"):
        if mod in sys.modules:
            del sys.modules[mod]
    import app
    assert app.request_url("/users") == "https://api.example.com/users"
    res = app.fetch("/users", retries=3)
    assert res is not None
    assert res["url"] == "https://api.example.com/users"
    assert res["timeout"] == 30
    settings = app.default_settings()
    assert settings == {
        "timeout": 30,
        "retries": 3,
        "base_url": "https://api.example.com",
    }
