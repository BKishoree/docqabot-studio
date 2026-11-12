"""GET /api/v1/config (DESIGN 4.3)."""

from __future__ import annotations

from fastapi import APIRouter

from studio import __version__
from studio.schemas import Config
from studio.settings import (
    ALLOWED_EXTENSIONS,
    CHAT_MODEL,
    EMBEDDING_MODEL,
    MAX_QUESTION_CHARS,
    RETRIEVAL_MIN_SIMILARITY,
    RETRIEVAL_TOP_K,
    load_settings,
)

router = APIRouter(prefix="/api/v1", tags=["config"])


@router.get("/config", response_model=Config)
async def config() -> dict:
    s = load_settings()
    return {
        "version": __version__,
        "mode": s.mode,
        "max_upload_bytes": s.max_upload_bytes,
        "allowed_extensions": list(ALLOWED_EXTENSIONS),
        "max_question_chars": MAX_QUESTION_CHARS,
        "embedding_model": EMBEDDING_MODEL,
        "chat_model": CHAT_MODEL,
        "retrieval": {"top_k": RETRIEVAL_TOP_K, "min_similarity": RETRIEVAL_MIN_SIMILARITY},
    }
