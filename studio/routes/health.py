"""GET /api/v1/health/live and GET /api/v1/health (DESIGN 4.3)."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from studio import __version__, db, openai_health
from studio.errors import StudioError
from studio.schemas import Health, Live
from studio.settings import load_settings

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health/live", response_model=Live)
async def live() -> dict:
    return {"status": "ok"}


def _database_component() -> dict:
    try:
        if not db.ensure_schema():
            return {"status": "unavailable", "detail": "The database cannot be reached or its schema could not be set up."}
        db.ping()
        return {"status": "ok", "detail": None}
    except StudioError:
        return {"status": "unavailable", "detail": "The database cannot be reached."}


@router.get("/health", response_model=Health)
async def health(refresh: bool = False) -> dict:
    s = load_settings()
    database = await run_in_threadpool(_database_component)
    probe = await run_in_threadpool(openai_health.check, refresh)
    ok = database["status"] == "ok" and probe.status == "ok"
    return {
        "status": "ok" if ok else "degraded",
        "version": __version__,
        "mode": s.mode,
        "auth_enabled": s.auth_enabled,
        "components": {
            "database": database,
            "openai": {
                "status": probe.status,
                "detail": probe.detail,
                "checked_at": db.iso_utc(probe.checked_at),
            },
        },
    }
