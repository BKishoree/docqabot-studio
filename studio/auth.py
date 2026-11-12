"""Optional shared HTTP Basic gate (DESIGN 2.7). Pure ASGI middleware."""

from __future__ import annotations

import base64
import binascii
import json
import secrets

from starlette.types import ASGIApp, Receive, Scope, Send

from studio.errors import envelope, is_api_path
from studio.settings import load_settings

EXEMPT_PATHS = frozenset({"/api/v1/health/live"})
REALM = 'Basic realm="DocQABot Studio", charset="UTF-8"'


def _credentials_ok(header_value: bytes | None, user: str, password: str) -> bool:
    if not header_value:
        return False
    try:
        scheme, _, token = header_value.decode("latin-1").partition(" ")
        if scheme.lower() != "basic" or not token:
            return False
        decoded = base64.b64decode(token.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    given_user, sep, given_password = decoded.partition(":")
    if not sep:
        return False
    user_ok = secrets.compare_digest(given_user.encode("utf-8"), user.encode("utf-8"))
    password_ok = secrets.compare_digest(given_password.encode("utf-8"), password.encode("utf-8"))
    return user_ok and password_ok


class BasicAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        s = load_settings()
        path = scope.get("path", "")
        if not s.auth_enabled or path in EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return
        header = None
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                header = value
                break
        if _credentials_ok(header, s.auth_user, s.auth_password):
            await self.app(scope, receive, send)
            return

        request_id = (scope.get("state") or {}).get("request_id", "-")
        if is_api_path(path):
            body = envelope("unauthorized", "Sign-in required. Reload the page to enter the username and password.",
                            None, request_id)
        else:
            body = {"detail": "Not authenticated"}
        payload = json.dumps(body).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
                (b"www-authenticate", REALM.encode()),
            ],
        })
        await send({"type": "http.response.body", "body": payload})
