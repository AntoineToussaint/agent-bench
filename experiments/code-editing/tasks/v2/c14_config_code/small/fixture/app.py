"""Tiny app module with inline magic numbers — pre-config-extraction."""

from __future__ import annotations


def request_url(path):
    return "https://api.example.com" + path


def fetch(path, retries):
    # naive retry loop — pretend this calls out over HTTP
    attempts = 0
    while attempts < 3:
        attempts += 1
        ok = _simulate_call(path, timeout=30)
        if ok:
            return {"url": request_url(path), "attempts": attempts, "timeout": 30}
    return None


def list_endpoints():
    return [
        "https://api.example.com/users",
        "https://api.example.com/orders",
    ]


def default_settings():
    return {
        "timeout": 30,
        "retries": 3,
        "base_url": "https://api.example.com",
    }


def _simulate_call(path, timeout):
    # First attempt always succeeds in this toy version
    return True
