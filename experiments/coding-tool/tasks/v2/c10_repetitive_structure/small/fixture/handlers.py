"""HTTP status handlers.

Intentional shape: ten near-identical handler functions, one per status code.
Their bodies group into four categories ("ok", "ok", "bad request",
"not found", "server error"). The repetition is the point — naive
find-and-replace cannot target a single handler without context.
"""

from __future__ import annotations


def handle_200():
    status = 200
    body = "ok"
    return {"status": status, "body": body}


def handle_201():
    status = 201
    body = "ok"
    return {"status": status, "body": body}


def handle_204():
    status = 204
    body = "ok"
    return {"status": status, "body": body}


def handle_301():
    status = 301
    body = "ok"
    return {"status": status, "body": body}


def handle_302():
    status = 302
    body = "ok"
    return {"status": status, "body": body}


def handle_400():
    status = 400
    body = "bad request"
    return {"status": status, "body": body}


def handle_401():
    status = 401
    body = "bad request"
    return {"status": status, "body": body}


def handle_403():
    status = 403
    body = "bad request"
    return {"status": status, "body": body}


def handle_404():
    status = 404
    body = "not found"
    return {"status": status, "body": body}


def handle_500():
    status = 500
    body = "server error"
    return {"status": status, "body": body}
