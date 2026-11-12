"""Serving the built frontend with SPA fallback (DESIGN 2.4, B9)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from studio.errors import StudioError, envelope_response, is_api_path

# First path segments the SPA router must not use.
RESERVED = frozenset({"api", "upload", "documents", "ask", "docs", "redoc", "openapi.json", "assets"})
CORE_POST_ONLY = frozenset({"upload", "ask"})

NO_FRONTEND_NOTICE = (
    "DocQABot Studio API is running, but the web interface has not been built.\n"
    "Build it with `npm --prefix web ci && npm --prefix web run build`, or use the container image.\n"
    "API documentation: /docs\n"
)


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def mount_frontend(app: FastAPI, dist: Path) -> None:
    dist = dist.resolve()
    index = dist / "index.html"
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
                   include_in_schema=False)
    async def api_not_found(rest: str, request: Request):
        return envelope_response(request, StudioError("not_found", 404, "This API path does not exist."))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str, request: Request):
        first = full_path.split("/", 1)[0]
        if is_api_path("/" + full_path):
            return envelope_response(request, StudioError("not_found", 404, "This API path does not exist."))
        if first in CORE_POST_ONLY and "/" not in full_path:
            return JSONResponse({"detail": "Method Not Allowed"}, status_code=405, headers={"Allow": "POST"})
        if first in RESERVED:
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        if index.is_file():
            # Top-level files of the build (favicon, robots.txt, ...)
            if full_path and "/" not in full_path:
                candidate = (dist / full_path).resolve()
                if candidate.parent == dist and candidate.is_file() and candidate.name != "index.html":
                    return FileResponse(candidate)
            if _wants_html(request) or full_path == "":
                return FileResponse(index, headers={"Cache-Control": "no-cache"})
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        if _wants_html(request) or full_path == "":
            return PlainTextResponse(NO_FRONTEND_NOTICE, status_code=200 if full_path == "" else 404)
        return JSONResponse({"detail": "Not Found"}, status_code=404)
