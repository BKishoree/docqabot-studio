"""The only Studio module that imports from ``app`` (DESIGN 2.3, AC2).

Everything else in ``studio/`` uses the functions below.
"""

from __future__ import annotations

import io
import logging
from typing import Any, Callable

import studio.bootstrap  # noqa: F401  (MUST run before any app.* import)

import app.database as core_database  # noqa: E402
import app.embeddings as core_embeddings  # noqa: E402
import app.main as core_main  # noqa: E402
import app.rag as core_rag  # noqa: E402
from fastapi import BackgroundTasks, UploadFile  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402

from studio.settings import load_settings  # noqa: E402

log = logging.getLogger("studio.core")

# Core upload detail texts at core-baseline (DESIGN 4.4)
CORE_DETAIL_ENCODING = "File must be UTF-8 encoded text"
CORE_DETAIL_NO_TEXT = "No text could be extracted from the file"


def _apply_client_options() -> None:
    """The one permitted runtime adjustment: timeout and retries of the two core clients."""
    s = load_settings()
    core_embeddings.client = core_embeddings.client.with_options(
        timeout=s.openai_timeout_s, max_retries=s.openai_max_retries
    )
    core_rag.client = core_rag.client.with_options(
        timeout=s.openai_timeout_s, max_retries=s.openai_max_retries
    )


_apply_client_options()


def core_routes() -> list[APIRoute]:
    """The core's own API routes (/upload, /documents, /ask), not its /docs or /openapi.json."""
    return [r for r in core_main.app.routes if isinstance(r, APIRoute)]


def init_db() -> None:
    core_database.init_db()


def get_connection():
    """Same connection factory as the core (RealDictCursor, DATABASE_URL)."""
    return core_database.get_connection()


async def upload(filename: str, content: bytes, headers: Any = None) -> tuple[dict, list[Callable[[], None]]]:
    """Run the core upload on already-read bytes.

    Returns the core's response dict and the core's background work as callables.
    Raises the core's HTTPException or the parser's exception unchanged.
    """
    file = UploadFile(file=io.BytesIO(content), filename=filename, headers=headers)
    collector = BackgroundTasks()
    result = await core_main.upload_document(file, collector)
    work = [
        (lambda t=task: t.func(*t.args, **t.kwargs))
        for task in collector.tasks
    ]
    return result, work


def retrieve(question: str) -> list[dict]:
    """Core retrieval with core defaults: [{content, source, similarity}]."""
    return core_rag.retrieve_context(question)


def answer(question: str, chunks: list[dict], history: list[dict]) -> str:
    return core_rag.generate_answer(question, chunks, history)


def probe_openai(timeout_s: float = 5.0) -> None:
    """Cheap reachability/key check through the core's (adjusted) client. Raises SDK errors."""
    client = core_rag.client.with_options(timeout=timeout_s, max_retries=0)
    client.models.list()
