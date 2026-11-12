"""Pydantic models for the /api/v1 contract (DESIGN 4). Field names are the contract."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[dict] = None
    request_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class Live(BaseModel):
    status: Literal["ok"]


class DatabaseComponent(BaseModel):
    status: Literal["ok", "unavailable"]
    detail: Optional[str]


class OpenAIComponent(BaseModel):
    status: Literal["ok", "not_configured", "invalid_key", "unreachable", "error"]
    detail: Optional[str]
    checked_at: str


class Components(BaseModel):
    database: DatabaseComponent
    openai: OpenAIComponent


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    mode: Literal["live", "demo"]
    auth_enabled: bool
    components: Components


class Retrieval(BaseModel):
    top_k: int
    min_similarity: float


class Config(BaseModel):
    version: str
    mode: Literal["live", "demo"]
    max_upload_bytes: int
    allowed_extensions: list[str]
    max_question_chars: int
    embedding_model: str
    chat_model: str
    retrieval: Retrieval


class DocumentError(BaseModel):
    code: Literal["processing_failed", "openai_auth", "openai_unreachable", "interrupted"]
    message: str


class Document(BaseModel):
    id: int
    filename: str
    status: Literal["processing", "ready", "failed"]
    created_at: str
    processed_at: Optional[str]
    size_bytes: Optional[int]
    chunk_count: int
    error: Optional[DocumentError]


class DocumentList(BaseModel):
    items: list[Document]
    total: int


class Citation(BaseModel):
    rank: int
    document_id: Optional[int]
    document_available: bool
    filename: str
    chunk_index: Optional[int]
    similarity: float
    text: str


class Message(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    grounded: Optional[bool]
    citations: list[Citation]


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class ConversationDetail(ConversationSummary):
    messages: list[Message]


class ConversationList(BaseModel):
    items: list[ConversationSummary]
    total: int


class AskResult(BaseModel):
    conversation: ConversationSummary
    user_message: Message
    assistant_message: Message


# ---- requests --------------------------------------------------------------------

class CreateConversation(BaseModel):
    title: Optional[str] = None


class RenameConversation(BaseModel):
    title: str


class AskRequest(BaseModel):
    question: str
