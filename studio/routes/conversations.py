"""Conversations API and the ask flow (DESIGN 2.2, 4.5)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import psycopg2
from fastapi import APIRouter, Body, Depends, Query, Response

from studio import bootstrap, core_adapter, db
from studio.errors import StudioError, not_found, openai_not_configured, validation_error
from studio.schemas import (
    AskRequest,
    AskResult,
    ConversationDetail,
    ConversationList,
    ConversationSummary,
    CreateConversation,
    RenameConversation,
)
from studio.settings import MAX_QUESTION_CHARS, MAX_TITLE_CHARS

log = logging.getLogger("studio.conversations")

router = APIRouter(prefix="/api/v1", tags=["conversations"], dependencies=[Depends(db.require_db)])

DEFAULT_TITLE = "New conversation"
AUTO_TITLE_CHARS = 60

_SUMMARY = """
    SELECT c.id, c.title, c.created_at, c.updated_at,
           (SELECT count(*) FROM studio_messages m WHERE m.conversation_id = c.id) AS message_count
    FROM studio_conversations c
"""


def _parse_id(conversation_id: str) -> str:
    try:
        return str(uuid.UUID(conversation_id))
    except (ValueError, AttributeError, TypeError):
        raise not_found("The conversation")


def _summary(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "created_at": db.iso_utc(row["created_at"]),
        "updated_at": db.iso_utc(row["updated_at"]),
        "message_count": int(row["message_count"]),
    }


def _clean_title(title: str | None, field: str = "title") -> str:
    value = (title or "").strip()
    if not value:
        raise validation_error([{"field": field, "message": "Title must not be empty."}])
    if len(value) > MAX_TITLE_CHARS:
        raise validation_error([{"field": field,
                                 "message": f"Title must be at most {MAX_TITLE_CHARS} characters."}])
    return value


def _fetch_summary(cur, conv_id: str) -> dict | None:
    cur.execute(_SUMMARY + " WHERE c.id = %s", (conv_id,))
    row = cur.fetchone()
    return _summary(row) if row else None


def _citation(row: dict) -> dict:
    return {
        "rank": int(row["rank"]),
        "document_id": row["document_id"],
        "document_available": row["document_id"] is not None,
        "filename": row["filename"],
        "chunk_index": row["chunk_index"],
        "similarity": round(float(row["similarity"]), 4),
        "text": row["content"],
    }


def _message(row: dict, citations: list[dict]) -> dict:
    return {
        "id": int(row["id"]),
        "role": row["role"],
        "content": row["content"],
        "created_at": db.iso_utc(row["created_at"]),
        "grounded": row["grounded"] if row["role"] == "assistant" else None,
        "citations": citations if row["role"] == "assistant" else [],
    }


def _load_messages(cur, conv_id: str, message_ids: list[int] | None = None) -> list[dict]:
    if message_ids is None:
        cur.execute(
            "SELECT id, role, content, grounded, created_at FROM studio_messages "
            "WHERE conversation_id = %s ORDER BY id",
            (conv_id,),
        )
    else:
        cur.execute(
            "SELECT id, role, content, grounded, created_at FROM studio_messages "
            "WHERE id = ANY(%s) ORDER BY id",
            (message_ids,),
        )
    rows = cur.fetchall()
    ids = [r["id"] for r in rows]
    by_message: dict[int, list[dict]] = {i: [] for i in ids}
    if ids:
        cur.execute(
            "SELECT message_id, rank, document_id, filename, chunk_index, similarity, content "
            "FROM studio_citations WHERE message_id = ANY(%s) ORDER BY message_id, rank",
            (ids,),
        )
        for c in cur.fetchall():
            by_message[c["message_id"]].append(_citation(c))
    return [_message(r, by_message[r["id"]]) for r in rows]


# ---- CRUD --------------------------------------------------------------------------

@router.get("/conversations", response_model=ConversationList)
def list_conversations(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict:
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM studio_conversations")
        total = int(cur.fetchone()["n"])
        cur.execute(_SUMMARY + " ORDER BY c.updated_at DESC, c.created_at DESC LIMIT %s OFFSET %s",
                    (limit, offset))
        items = [_summary(r) for r in cur.fetchall()]
    return {"items": items, "total": total}


@router.post("/conversations", status_code=201, response_model=ConversationSummary)
def create_conversation(body: CreateConversation | None = Body(default=None)) -> dict:
    title = DEFAULT_TITLE if body is None or body.title is None else _clean_title(body.title)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO studio_conversations (title) VALUES (%s) RETURNING id", (title,))
        conv_id = str(cur.fetchone()["id"])
        summary = _fetch_summary(cur, conv_id)
    return summary


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: str) -> dict:
    conv_id = _parse_id(conversation_id)
    with db.connection() as conn, conn.cursor() as cur:
        summary = _fetch_summary(cur, conv_id)
        if summary is None:
            raise not_found("The conversation")
        messages = _load_messages(cur, conv_id)
    return {**summary, "messages": messages}


@router.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
def rename_conversation(conversation_id: str, body: RenameConversation) -> dict:
    conv_id = _parse_id(conversation_id)
    title = _clean_title(body.title)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE studio_conversations SET title = %s WHERE id = %s RETURNING id", (title, conv_id))
        if cur.fetchone() is None:
            raise not_found("The conversation")
        summary = _fetch_summary(cur, conv_id)
    return summary


@router.delete("/conversations/{conversation_id}", status_code=204, response_class=Response)
def delete_conversation(conversation_id: str) -> Response:
    conv_id = _parse_id(conversation_id)
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM studio_conversations WHERE id = %s RETURNING id", (conv_id,))
        if cur.fetchone() is None:
            raise not_found("The conversation")
    return Response(status_code=204)


# ---- ask ---------------------------------------------------------------------------

def _resolve_citation(cur, chunk: dict) -> tuple[int | None, int | None]:
    cur.execute(
        """SELECT c.document_id, c.chunk_index
           FROM chunks c JOIN documents d ON d.id = c.document_id
           WHERE d.status = 'ready' AND d.filename = %s AND md5(c.content) = md5(%s)
           ORDER BY c.id LIMIT 1""",
        (chunk["source"], chunk["content"]),
    )
    row = cur.fetchone()
    return (row["document_id"], row["chunk_index"]) if row else (None, None)


@router.post("/conversations/{conversation_id}/messages", status_code=201, response_model=AskResult,
             responses={404: {}, 409: {}, 422: {}, 502: {}, 503: {}})
def ask(conversation_id: str, body: AskRequest) -> dict:
    question = body.question.strip()
    if not question:
        raise validation_error([{"field": "question", "message": "The question must not be empty."}])
    if len(question) > MAX_QUESTION_CHARS:
        raise validation_error([{"field": "question",
                                 "message": f"The question must be at most {MAX_QUESTION_CHARS} characters."}])
    conv_id = _parse_id(conversation_id)
    received_at = datetime.now(timezone.utc)

    with db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, title FROM studio_conversations WHERE id = %s", (conv_id,))
        conv = cur.fetchone()
        if conv is None:
            raise not_found("The conversation")
        if not bootstrap.state.openai_configured:
            raise openai_not_configured()
        cur.execute("SELECT EXISTS (SELECT 1 FROM documents WHERE status = 'ready') AS any_ready")
        if not cur.fetchone()["any_ready"]:
            raise StudioError("no_ready_documents", 409,
                              "No document is ready yet. Upload a document and wait until it is ready, then ask.")
        cur.execute(
            "SELECT role, content FROM studio_messages WHERE conversation_id = %s ORDER BY id",
            (conv_id,),
        )
        history = [{"role": r["role"], "content": r["content"]} for r in cur.fetchall()]

    # OpenAI / stub calls; their errors propagate to the handlers (nothing stored yet).
    chunks = core_adapter.retrieve(question)
    answer_text = core_adapter.answer(question, chunks, history)

    try:
        with db.connection() as conn, conn.cursor() as cur:
            resolved = [_resolve_citation(cur, ch) for ch in chunks]
            cur.execute(
                "INSERT INTO studio_messages (conversation_id, role, content, grounded, created_at) "
                "VALUES (%s, 'user', %s, NULL, %s) RETURNING id",
                (conv_id, question, received_at),
            )
            user_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO studio_messages (conversation_id, role, content, grounded, created_at) "
                "VALUES (%s, 'assistant', %s, %s, clock_timestamp()) RETURNING id",
                (conv_id, answer_text, bool(chunks)),
            )
            assistant_id = cur.fetchone()["id"]
            for rank, (chunk, (doc_id, chunk_index)) in enumerate(zip(chunks, resolved), start=1):
                similarity = min(1.0, max(0.0, round(float(chunk["similarity"]), 4)))
                cur.execute(
                    "INSERT INTO studio_citations "
                    "(message_id, rank, document_id, filename, chunk_index, similarity, content) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (assistant_id, rank, doc_id, chunk["source"], chunk_index, similarity, chunk["content"]),
                )
            new_title = conv["title"]
            if new_title == "New conversation":
                new_title = question[:AUTO_TITLE_CHARS]
            cur.execute(
                "UPDATE studio_conversations SET updated_at = clock_timestamp(), title = %s WHERE id = %s",
                (new_title, conv_id),
            )
            summary = _fetch_summary(cur, conv_id)
            user_msg, assistant_msg = _load_messages(cur, conv_id, [user_id, assistant_id])
    except psycopg2.errors.ForeignKeyViolation as exc:
        log.warning("Ask could not be stored (%s): %s", type(exc).__name__,
                    (exc.diag.constraint_name if exc.diag else None))
        raise not_found("The conversation")  # deleted while the answer was generated

    return {"conversation": summary, "user_message": user_msg, "assistant_message": assistant_msg}
