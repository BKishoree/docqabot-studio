"""Documents API (DESIGN 4.4) and the processing tracking wrapper (DESIGN 2.3)."""

from __future__ import annotations

import logging
import time
import unicodedata
from typing import Callable

import openai
from fastapi import APIRouter, BackgroundTasks, Depends, Response, UploadFile
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from studio import bootstrap, core_adapter, db, openai_health
from studio.errors import StudioError, not_found, openai_not_configured
from studio.schemas import Document, DocumentList
from studio.settings import ALLOWED_EXTENSIONS, MAX_FILENAME_CHARS, load_settings

log = logging.getLogger("studio.documents")

router = APIRouter(prefix="/api/v1", tags=["documents"])

PG_INT_MAX = 2_147_483_647

ERROR_MESSAGES = {
    "processing_failed": "Processing failed. Remove the document and upload it again.",
    "openai_auth": "OpenAI rejected the API key while this document was processed. "
                   "Fix the key, then remove the document and upload it again.",
    "openai_unreachable": "OpenAI could not be reached while this document was processed. "
                          "Remove the document and upload it again when the connection works.",
    "interrupted": "Processing was interrupted because the app restarted. "
                   "Remove the document and upload it again.",
}

_SELECT = """
    SELECT d.id, d.filename, d.status, d.created_at,
           m.size_bytes, m.processed_at, m.error_code,
           (SELECT count(*) FROM chunks c WHERE c.document_id = d.id) AS chunk_count
    FROM documents d
    LEFT JOIN studio_document_meta m ON m.document_id = d.id
"""


def to_document(row: dict) -> dict:
    status = row["status"] if row["status"] in ("processing", "ready", "failed") else "failed"
    # Studio uploads (meta row present) stay "processing" until run_tracked has recorded the
    # outcome: the core commits ready/failed a moment before Studio writes processed_at and
    # error_code, and a poll in between must not see a failure without its reason.
    if row.get("size_bytes") is not None and row.get("processed_at") is None:
        status = "processing"
    error = None
    if status == "failed":
        code = row.get("error_code") if row.get("error_code") in ERROR_MESSAGES else "processing_failed"
        error = {"code": code, "message": ERROR_MESSAGES[code]}
    return {
        "id": row["id"],
        "filename": row["filename"],
        "status": status,
        "created_at": db.iso_utc(row["created_at"]),
        "processed_at": db.iso_utc(row.get("processed_at")) if status != "processing" else None,
        "size_bytes": row.get("size_bytes"),
        "chunk_count": int(row.get("chunk_count") or 0) if status == "ready" else 0,
        "error": error,
    }


def fetch_document(doc_id: int) -> dict | None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(_SELECT + " WHERE d.id = %s", (doc_id,))
        row = cur.fetchone()
    return to_document(row) if row else None


# ---- validation --------------------------------------------------------------------

def _format_mb(n_bytes: float) -> str:
    mb = n_bytes / (1024 * 1024)
    return f"{mb:.0f} MB" if abs(mb - round(mb)) < 1e-9 else f"{mb:.1f} MB"


def file_too_large(size_bytes: int | None, limit_bytes: int) -> StudioError:
    if size_bytes is None:
        message = f"The file is too large. The limit is {_format_mb(limit_bytes)}."
    else:
        message = f"The file is {_format_mb(size_bytes)}. The limit is {_format_mb(limit_bytes)}."
    return StudioError("file_too_large", 413, message,
                       {"limit_bytes": limit_bytes, "size_bytes": size_bytes})


def validate_filename(filename: str | None) -> str:
    name = filename or ""
    if not name.strip():
        raise StudioError("invalid_filename", 400, "The file has no name. Rename it and upload it again.")
    if len(name) > MAX_FILENAME_CHARS:
        raise StudioError("invalid_filename", 400,
                          f"The file name is {len(name)} characters long. The limit is {MAX_FILENAME_CHARS}.",
                          {"max_chars": MAX_FILENAME_CHARS, "length": len(name)})
    if any(unicodedata.category(ch) == "Cc" for ch in name):
        raise StudioError("invalid_filename", 400,
                          "The file name contains control characters. Rename it and upload it again.")
    return name


def validate_extension(filename: str) -> None:
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise StudioError("unsupported_file_type", 415,
                          "This file type is not supported. Upload a PDF, Markdown (.md) or text (.txt) file.",
                          {"allowed_extensions": list(ALLOWED_EXTENSIONS)})


def map_core_upload_error(exc: HTTPException) -> StudioError:
    detail = str(exc.detail)
    if detail == core_adapter.CORE_DETAIL_ENCODING:
        return StudioError("invalid_encoding", 400,
                           "The file is not UTF-8 text. Save it as UTF-8 and upload it again.")
    if detail == core_adapter.CORE_DETAIL_NO_TEXT:
        return StudioError("no_extractable_text", 422,
                           "No text could be extracted from the file. Scanned PDFs (images of text) "
                           "are not supported; upload a file that contains selectable text.")
    return StudioError("upload_rejected", 400, detail)


# ---- background tracking -----------------------------------------------------------

def _classify_failure() -> str:
    try:
        core_adapter.probe_openai()
        return "processing_failed"
    except (openai.AuthenticationError, openai.PermissionDeniedError):
        return "openai_auth"
    except openai.APIConnectionError:
        return "openai_unreachable"
    except Exception:
        return "processing_failed"


RECORD_ATTEMPTS = 5
RECORD_RETRY_INTERVAL_S = 2.0


def run_tracked(doc_id: int, work: list[Callable[[], None]]) -> None:
    """Run the core's processing, then record processed_at / error_code. Never raises.

    Recording is retried a few times (about 8 s in total) when the database is briefly
    unavailable; after that the startup sweep records the outcome on the next start.
    """
    for job in work:
        try:
            job()
        except Exception as exc:
            log.error("Core processing raised for document %s: %s", doc_id, type(exc).__name__)
    for attempt in range(1, RECORD_ATTEMPTS + 1):
        try:
            _record_outcome(doc_id)
            return
        except StudioError as exc:  # database_unavailable
            if attempt == RECORD_ATTEMPTS:
                log.error("Could not record the outcome of document %s after %d attempts: %s",
                          doc_id, attempt, exc.code)
                return
            time.sleep(RECORD_RETRY_INTERVAL_S)
        except Exception as exc:
            log.error("Could not record the outcome of document %s: %s", doc_id, type(exc).__name__)
            return


def _record_outcome(doc_id: int) -> None:
    """Read the core's final status and store processed_at / error_code.

    Raises StudioError(database_unavailable) when the database cannot be reached.
    """
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM documents WHERE id = %s", (doc_id,))
        row = cur.fetchone()
    if row is None:
        return  # deleted while processing
    status = row["status"]
    error_code = None
    if status == "failed":
        error_code = _classify_failure()
        openai_health.invalidate()
    elif status == "processing":
        # The core could not even start (e.g. DB connection failed). Mark it failed.
        error_code = "processing_failed"
    with db.connection() as conn, conn.cursor() as cur:
        if status == "processing":
            cur.execute("UPDATE documents SET status = 'failed' WHERE id = %s AND status = 'processing'",
                        (doc_id,))
        cur.execute(
            "UPDATE studio_document_meta SET processed_at = now(), error_code = %s WHERE document_id = %s",
            (error_code, doc_id),
        )
    log.info("Document %s finished: %s%s", doc_id, "failed" if error_code else status,
             f" ({error_code})" if error_code else "")


# ---- routes ------------------------------------------------------------------------

@router.get("/documents", response_model=DocumentList, dependencies=[Depends(db.require_db)])
def list_documents() -> dict:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(_SELECT + " ORDER BY d.created_at DESC, d.id DESC")
        rows = cur.fetchall()
    items = [to_document(r) for r in rows]
    return {"items": items, "total": len(items)}


@router.post("/documents", status_code=202, response_model=Document,
             responses={400: {}, 413: {}, 415: {}, 422: {}, 503: {}})
async def upload_document(file: UploadFile, background_tasks: BackgroundTasks) -> dict:
    # Order (DESIGN 4.4): OpenAI configured -> filename -> extension -> size -> empty -> core.
    if not bootstrap.state.openai_configured:
        raise openai_not_configured()
    filename = validate_filename(file.filename)
    validate_extension(filename)
    limit = load_settings().max_upload_bytes
    content = await file.read(limit + 1)
    if len(content) > limit:
        size = file.size if file.size is not None and file.size > limit else None
        raise file_too_large(size, limit)
    if len(content) == 0:
        raise StudioError("empty_file", 400, "The file is empty.")

    if not await run_in_threadpool(db.ensure_schema):
        from studio.errors import database_unavailable
        raise database_unavailable()

    try:
        # PDF parsing in the core is synchronous; run it off the event loop.
        result, work = await run_in_threadpool(_run_core_upload, filename, content, file.headers)
    except HTTPException as exc:
        if exc.status_code == 400:
            raise map_core_upload_error(exc) from exc
        raise
    except StudioError:
        raise
    except db.DB_ERRORS:
        raise
    except Exception as exc:
        log.info("Upload of a %s file rejected as unreadable: %s", filename.rsplit(".", 1)[-1].lower(),
                 type(exc).__name__)
        raise StudioError("unreadable_file", 422,
                          "The file could not be read. It may be damaged or password-protected.") from exc

    doc_id = int(result["document_id"])
    try:
        await run_in_threadpool(_insert_meta, doc_id, len(content), file.content_type)
    except BaseException:
        await run_in_threadpool(_delete_quietly, doc_id)
        raise

    background_tasks.add_task(run_tracked, doc_id, work)
    doc = await run_in_threadpool(fetch_document, doc_id)
    if doc is None:  # deleted in between
        raise not_found("The document")
    return doc


def _run_core_upload(filename: str, content: bytes, headers):
    import asyncio

    return asyncio.run(core_adapter.upload(filename, content, headers))


def _insert_meta(doc_id: int, size_bytes: int, content_type: str | None) -> None:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO studio_document_meta (document_id, size_bytes, content_type) VALUES (%s, %s, %s)",
            (doc_id, size_bytes, content_type),
        )


def _delete_quietly(doc_id: int) -> None:
    try:
        with db.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
    except Exception:
        log.error("Could not remove document %s after a failed upload", doc_id)


def _valid_id(doc_id: int) -> None:
    if doc_id < 1 or doc_id > PG_INT_MAX:
        raise not_found("The document")


@router.get("/documents/{doc_id}", response_model=Document, dependencies=[Depends(db.require_db)])
def get_document(doc_id: int) -> dict:
    _valid_id(doc_id)
    doc = fetch_document(doc_id)
    if doc is None:
        raise not_found("The document")
    return doc


@router.delete("/documents/{doc_id}", status_code=204, response_class=Response,
               dependencies=[Depends(db.require_db)])
def delete_document(doc_id: int) -> Response:
    _valid_id(doc_id)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM documents WHERE id = %s RETURNING id", (doc_id,))
        deleted = cur.fetchone()
    if deleted is None:
        raise not_found("The document")
    return Response(status_code=204)
