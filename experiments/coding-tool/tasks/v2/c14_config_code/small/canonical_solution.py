"""Canonical solution for c14_config_code / small."""

from __future__ import annotations

from pathlib import Path


CONFIG_PY = '''"""Configuration constants for the toy app."""

from __future__ import annotations


TIMEOUT = 30
RETRIES = 3
BASE_URL = "https://api.example.com"
'''


NEW_APP_PY = '''"""Tiny app module — post-config-extraction."""

from __future__ import annotations

from config import BASE_URL, RETRIES, TIMEOUT


def request_url(path):
    return BASE_URL + path


def fetch(path, retries):
    attempts = 0
    while attempts < RETRIES:
        attempts += 1
        ok = _simulate_call(path, timeout=TIMEOUT)
        if ok:
            return {"url": request_url(path), "attempts": attempts, "timeout": TIMEOUT}
    return None


def list_endpoints():
    return [
        BASE_URL + "/users",
        BASE_URL + "/orders",
    ]


def default_settings():
    return {
        "timeout": TIMEOUT,
        "retries": RETRIES,
        "base_url": BASE_URL,
    }


def _simulate_call(path, timeout):
    return True
'''


def apply(workdir: Path) -> None:
    (workdir / "config.py").write_text(CONFIG_PY, encoding="utf-8")
    (workdir / "app.py").write_text(NEW_APP_PY, encoding="utf-8")
