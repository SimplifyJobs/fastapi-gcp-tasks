"""Helpers shared by tests that replay a built task request into a FastAPI app."""

# Standard Library Imports
import asyncio
import json
from typing import Any
from urllib.parse import unquote, urlsplit

# Third Party Imports
from fastapi import FastAPI


def replay(app: FastAPI, http_request: Any, *, extra_headers: dict[str, str] | None = None) -> tuple[int, Any]:
    """
    Send a built task request straight into the ASGI app and return (status, json body).

    Works for Cloud Tasks requests (``url``) and Cloud Scheduler targets (``uri``). The path is
    percent-decoded the way an ASGI server does it before routing.
    """
    target = getattr(http_request, "url", None) or http_request.uri
    parts = urlsplit(target)
    request_headers = {**dict(http_request.headers), **(extra_headers or {})}
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": parts.scheme,
        "path": unquote(parts.path),
        "raw_path": parts.path.encode(),
        "query_string": parts.query.encode(),
        "headers": [(k.lower().encode(), v.encode()) for k, v in request_headers.items()],
        "server": (parts.hostname, 443),
        "client": ("127.0.0.1", 1234),
    }
    sent: list[dict[str, Any]] = []
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": bytes(http_request.body), "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))  # type: ignore[arg-type]
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    payload = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(payload) if payload else None
