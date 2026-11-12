"""Request id (+ last-resort 500) and request-size limit, as pure ASGI middleware."""

from __future__ import annotations

import json
import logging
import re
import secrets
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from studio.errors import StudioHTTPException, envelope, internal_error_body, is_api_path
from studio.settings import load_settings

log = logging.getLogger("studio.http")

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# Multipart framing around the file (boundaries, part headers). Kept small so the
# limit also holds for the core's POST /upload, which has no per-file check of its own.
# One file part's framing is a few hundred bytes (boundaries + headers + a name of
# at most a few hundred characters), so 2 KiB is enough and keeps the core path tight.
BODY_OVERHEAD_BYTES = 2 * 1024


def _new_request_id() -> str:
    return secrets.token_hex(5)


async def _send_json(send: Send, status: int, body: dict, headers: list[tuple[bytes, bytes]] | None = None) -> None:
    payload = json.dumps(body).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode())] + (headers or []),
    })
    await send({"type": "http.response.body", "body": payload})


class RequestIdMiddleware:
    """Every response carries X-Request-ID; unhandled errors become a 500 without internals."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        request_id = incoming if incoming and _SAFE_ID.match(incoming) else _new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id
        rid_header = (b"x-request-id", request_id.encode("ascii"))
        started = False
        status_code = 500
        t0 = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal started, status_code
            if message["type"] == "http.response.start":
                started = True
                status_code = message["status"]
                headers = [h for h in message.get("headers", []) if h[0].lower() != b"x-request-id"]
                message = {**message, "headers": headers + [rid_header]}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            log.exception("Unhandled error [%s] %s %s", request_id, scope.get("method"), scope.get("path"))
            if started:
                raise
            path = scope.get("path", "")
            if is_api_path(path):
                await _send_json(send, 500, internal_error_body(request_id), [rid_header])
            else:
                payload = b"Internal Server Error"
                await send({"type": "http.response.start", "status": 500,
                            "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                        (b"content-length", str(len(payload)).encode()), rid_header]})
                await send({"type": "http.response.body", "body": payload})
            status_code = 500
        finally:
            path = scope.get("path", "")
            if path != "/api/v1/health/live":
                log.info("[%s] %s %s -> %s (%.0f ms)", request_id, scope.get("method"), path, status_code,
                         (time.perf_counter() - t0) * 1000)


DRAIN_CAP_BYTES = 256 * 1024 * 1024


async def _drain(receive: Receive, already: int = 0) -> None:
    """Read and discard the rest of an oversized body so the client can read the 413
    instead of getting a connection reset. Stops after DRAIN_CAP_BYTES."""
    total = 0
    while total < DRAIN_CAP_BYTES:
        message = await receive()
        if message["type"] != "http.request":
            return
        total += len(message.get("body", b""))
        if not message.get("more_body", False):
            return


class _BodyTooLarge(StudioHTTPException):
    """Raised from receive(); FastAPI re-raises HTTPExceptions met while reading the body."""


class BodySizeLimitMiddleware:
    """Global request-size limit (413) for every path, core paths included (DESIGN 4.6)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit_file = load_settings().max_upload_bytes
        limit = limit_file + BODY_OVERHEAD_BYTES
        path = scope.get("path", "")
        request_id = (scope.get("state") or {}).get("request_id", "-")

        declared = None
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
                break
        if declared is not None and declared > limit:
            await _drain(receive, declared)
            await self._reject(send, path, request_id, limit_file, declared)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    from studio.routes.documents import file_too_large

                    if message.get("more_body", False):
                        await _drain(receive, received)
                    raise _BodyTooLarge(file_too_large(None, limit_file))
            return message

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, send_wrapper)
        except _BodyTooLarge:
            if started:
                raise
            await self._reject(send, path, request_id, limit_file, None)

    @staticmethod
    async def _reject(send: Send, path: str, request_id: str, limit_file: int, size: int | None) -> None:
        from studio.routes.documents import file_too_large

        err = file_too_large(size, limit_file)
        if is_api_path(path):
            body = envelope(err.code, err.message, err.details, request_id)
        else:
            body = {"detail": err.message}
        await _send_json(send, 413, body, [(b"connection", b"close")])
