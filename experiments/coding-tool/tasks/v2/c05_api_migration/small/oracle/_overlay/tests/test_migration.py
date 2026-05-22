"""Oracle tests for c05_api_migration / small."""

import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))

PRINT_RE = re.compile(r"\bprint\(")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_no_print_calls_remain() -> None:
    for rel in ("logging_helpers.py", "main.py"):
        assert not PRINT_RE.search(_read(rel)), f"{rel} still uses print()"


def test_logger_defined_in_each_file() -> None:
    for rel in ("logging_helpers.py", "main.py"):
        src = _read(rel)
        assert "import logging" in src, f"{rel} must import logging"
        assert re.search(
            r"logger\s*=\s*logging\.getLogger\(__name__\)", src
        ), f"{rel} must define module-level logger"


def test_helpers_still_callable_without_error() -> None:
    import importlib

    import logging_helpers as lh

    importlib.reload(lh)
    lh.log_request("GET", "/x")
    lh.log_response(200, "/x")
    lh.log_error(RuntimeError("boom"))
    lh.log_audit(42, "do-thing")
    lh.log_metric("latency_ms", 12.5)


def test_handle_still_returns_dict() -> None:
    import importlib

    import main

    importlib.reload(main)
    assert main.handle("GET", "/x", 7) == {"method": "GET", "path": "/x"}


def test_log_records_emitted(caplog) -> None:
    import importlib

    import logging_helpers as lh

    importlib.reload(lh)
    caplog.set_level(logging.INFO, logger="logging_helpers")
    lh.log_request("POST", "/y")
    assert any("POST" in r.getMessage() for r in caplog.records)
