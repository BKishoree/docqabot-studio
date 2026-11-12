"""Error envelope (DESIGN 4.2) and mapping of library exceptions to it."""

from __future__ import annotations

import logging
from typing import Any

import openai
import psycopg2
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("studio.errors")

API_PREFIX = "/api/v1"

_DB_ERRORS = (psycopg2.OperationalError, psycopg2.InterfaceError)


class StudioError(Exception):
    def __init__(self, code: str, status: int, message: str, details: dict | None = None,
                 headers: dict | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message
        self.details = details
        self.headers = headers


class StudioHTTPException(StarletteHTTPException):
    """An HTTPException carrying a StudioError; raised where FastAPI would otherwise
    swallow a plain exception (e.g. while it reads the request body)."""

    def __init__(self, err: StudioError):
        super().__init__(status_code=err.status, detail=err.message, headers=err.headers)
        self.studio_error = err


def is_api_path(path: str) -> bool:
    return path == API_PREFIX or path.startswith(API_PREFIX + "/")


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", None) or "-"


def envelope(code: str, message: str, details: dict | None, request_id: str) -> dict:
    return {"error": {"code": code, "message": message, "details": details, "request_id": request_id}}


def envelope_response(request: Request, err: StudioError) -> JSONResponse:
    return JSONResponse(
        status_code=err.status,
        content=envelope(err.code, err.message, err.details, request_id_of(request)),
        headers=err.headers,
    )


# ---- reusable errors -------------------------------------------------------------

def database_unavailable() -> StudioError:
    return StudioError("database_unavailable", 503,
                       "The database cannot be reached. The app will recover by itself when it is back.")


def openai_not_configured() -> StudioError:
    return StudioError("openai_not_configured", 503,
                       "No OpenAI API key is configured. Set OPENAI_API_KEY (or start demo mode) and restart the app.")


def not_found(what: str) -> StudioError:
    return StudioError("not_found", 404, f"{what} was not found. It may have been deleted.")


def validation_error(fields: list[dict]) -> StudioError:
    first = fields[0]["message"] if fields else "The request is invalid."
    return StudioError("validation_error", 422, f"The request is invalid: {first}", {"fields": fields})


def map_openai_error(exc: Exception) -> StudioError:
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return StudioError("openai_auth_failed", 502,
                           "OpenAI rejected the API key. Check OPENAI_API_KEY and restart the app.")
    if isinstance(exc, openai.RateLimitError):
        return StudioError("openai_rate_limited", 503,
                           "OpenAI is rate limiting requests or the account quota is used up. Try again in a moment.")
    if isinstance(exc, openai.APIConnectionError):  # includes APITimeoutError
        return StudioError("openai_unreachable", 502,
                           "OpenAI could not be reached or did not answer in time. Try again in a moment.")
    return StudioError("openai_error", 502, "OpenAI returned an error. Try again; if it persists, check the status page.")


# ---- handlers --------------------------------------------------------------------

def _field_name(loc: tuple) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    return ".".join(parts) if parts else (str(loc[0]) if loc else "request")


def install_handlers(app: FastAPI, on_openai_error=None) -> None:
    from fastapi.exception_handlers import (
        http_exception_handler,
        request_validation_exception_handler,
    )

    @app.exception_handler(StudioError)
    async def _studio_error(request: Request, exc: StudioError):
        return envelope_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        if not is_api_path(request.url.path):
            return await request_validation_exception_handler(request, exc)
        fields = [{"field": _field_name(tuple(e.get("loc", ()))), "message": e.get("msg", "invalid")}
                  for e in exc.errors()]
        return envelope_response(request, validation_error(fields))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        studio_err = getattr(exc, "studio_error", None)
        if not is_api_path(request.url.path):
            return await http_exception_handler(request, exc)
        if studio_err is not None:
            return envelope_response(request, studio_err)
        codes = {404: "not_found", 401: "unauthorized", 413: "file_too_large", 405: "method_not_allowed"}
        code = codes.get(exc.status_code, "internal_error" if exc.status_code >= 500 else "validation_error")
        message = {
            404: "This API path does not exist.",
            405: "This method is not allowed on this API path.",
        }.get(exc.status_code, str(exc.detail))
        return envelope_response(request, StudioError(code, exc.status_code, message, None,
                                                      getattr(exc, "headers", None)))

    @app.exception_handler(openai.OpenAIError)
    async def _openai(request: Request, exc: openai.OpenAIError):
        log.warning("OpenAI error on %s: %s", request.url.path, type(exc).__name__)
        if on_openai_error is not None:
            on_openai_error()
        if not is_api_path(request.url.path):
            return PlainTextResponse("Internal Server Error", status_code=500)
        return envelope_response(request, map_openai_error(exc))

    for cls in _DB_ERRORS:
        @app.exception_handler(cls)
        async def _db(request: Request, exc: Exception):
            log.warning("Database unavailable on %s: %s", request.url.path, type(exc).__name__)
            if not is_api_path(request.url.path):
                return PlainTextResponse("Internal Server Error", status_code=500)
            return envelope_response(request, database_unavailable())


def internal_error_body(request_id: str) -> dict[str, Any]:
    return envelope("internal_error", "Something went wrong on the server. Try again.", None, request_id)
