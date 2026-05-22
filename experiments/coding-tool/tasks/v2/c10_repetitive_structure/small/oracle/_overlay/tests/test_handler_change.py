"""Oracle tests for c10_repetitive_structure / small."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))


def test_handle_404_body_changed() -> None:
    import handlers

    assert handlers.handle_404()["body"] == "resource missing"
    assert handlers.handle_404()["status"] == 404


def test_other_handlers_unchanged() -> None:
    import handlers

    assert handlers.handle_200()["body"] == "ok"
    assert handlers.handle_201()["body"] == "ok"
    assert handlers.handle_204()["body"] == "ok"
    assert handlers.handle_301()["body"] == "ok"
    assert handlers.handle_302()["body"] == "ok"
    assert handlers.handle_400()["body"] == "bad request"
    assert handlers.handle_401()["body"] == "bad request"
    assert handlers.handle_403()["body"] == "bad request"
    assert handlers.handle_500()["body"] == "server error"


def test_no_other_handler_uses_resource_missing() -> None:
    import handlers

    names = [
        "handle_200",
        "handle_201",
        "handle_204",
        "handle_301",
        "handle_302",
        "handle_400",
        "handle_401",
        "handle_403",
        "handle_500",
    ]
    for name in names:
        body = getattr(handlers, name)()["body"]
        assert body != "resource missing", (
            f"{name} must not have been changed to 'resource missing'"
        )


def test_status_codes_unchanged() -> None:
    import handlers

    assert handlers.handle_200()["status"] == 200
    assert handlers.handle_201()["status"] == 201
    assert handlers.handle_500()["status"] == 500
