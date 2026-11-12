"""The served FastAPI app: ``uvicorn studio.main:app``."""

from __future__ import annotations

import studio.bootstrap  # noqa: F401  (first: environment handling before any app.* import)

import asyncio  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402

from studio import __version__, bootstrap, core_adapter, db, openai_health  # noqa: E402
from studio.auth import BasicAuthMiddleware  # noqa: E402
from studio.errors import install_handlers  # noqa: E402
from studio.middleware import BodySizeLimitMiddleware, RequestIdMiddleware  # noqa: E402
from studio.routes import config, conversations, documents, health  # noqa: E402
from studio.settings import load_settings  # noqa: E402
from studio.web import mount_frontend  # noqa: E402

log = logging.getLogger("studio")

DB_RETRY_INTERVAL_S = 2.0


def _configure_logging(level: str) -> None:
    root = logging.getLogger("studio")
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
        root.propagate = False
    root.setLevel(getattr(logging, level, logging.INFO))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    s = load_settings()
    _configure_logging(s.log_level)
    log.info("DocQABot Studio %s starting in %s mode (OpenAI %s, auth %s)", __version__, s.mode,
             "configured" if bootstrap.state.openai_configured else "NOT configured",
             "on" if s.auth_enabled else "off")
    if not s.bind_is_loopback and not s.auth_enabled:
        log.warning("STUDIO_BIND_ADDR=%s is not a loopback address and the login is off: anyone who can "
                    "reach this port can use the app. Set STUDIO_AUTH_USER and STUDIO_AUTH_PASSWORD.",
                    s.bind_addr)
    if bootstrap.state.database_url_defaulted:
        log.info("DATABASE_URL not set; using the local default on 127.0.0.1:5433.")

    db.reset_for_startup()
    openai_health.invalidate()
    await run_in_threadpool(core_adapter.warm_up)
    for attempt in range(1, s.db_startup_retries + 1):
        if await run_in_threadpool(db.ensure_schema):
            log.info("Database ready.")
            break
        if attempt < s.db_startup_retries:
            await asyncio.sleep(DB_RETRY_INTERVAL_S)
    else:
        log.warning("Database not reachable after %d attempt(s); starting degraded. "
                    "Health checks keep retrying.", s.db_startup_retries)
    yield


def create_app() -> FastAPI:
    s = load_settings()
    application = FastAPI(title="DocQABot Studio", version=__version__, lifespan=lifespan)
    install_handlers(application, on_openai_error=openai_health.invalidate)

    application.include_router(health.router)
    application.include_router(config.router)
    application.include_router(documents.router)
    application.include_router(conversations.router)
    # Core routes, unchanged: POST /upload, GET /documents, POST /ask
    for route in core_adapter.core_routes():
        application.router.routes.append(route)
    mount_frontend(application, s.web_dist)  # catch-all, must stay last

    # Last added = outermost: request id -> auth -> size limit -> app
    application.add_middleware(BodySizeLimitMiddleware)
    application.add_middleware(BasicAuthMiddleware)
    application.add_middleware(RequestIdMiddleware)
    return application


app = create_app()
