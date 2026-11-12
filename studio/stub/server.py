"""Deterministic OpenAI-compatible stub (DESIGN 4.7).

Only FastAPI/Starlette/pydantic and the standard library are used here.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import math
import re
import struct
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

EMBEDDING_MODEL = "text-embedding-3-small"
CHAT_MODEL = "gpt-4o-mini"
DIMENSIONS = 1536
INVALID_KEY = "sk-stub-invalid"

MARKER_FAIL = "__STUB_FAIL__"
MARKER_SLOW = "__STUB_SLOW__"
MARKER_RATE_LIMIT = "__STUB_RATE_LIMIT__"
SLOW_SECONDS = 3.0

# Fixed English stop-word list. Changing it changes every stub vector.
STOP_WORDS = frozenset(
    """
    a about above after again against all am an and any are as at be because been
    before being below between both but by can could did do does doing down during
    each few for from further had has have having he her here hers herself him
    himself his how i if in into is it its itself just me more most my myself no nor
    not now of off on once only or other our ours ourselves out over own same she
    should so some such than that the their theirs them themselves then there these
    they this those through to too under until up very was we were what when where
    which while who whom why will with would you your yours yourself yourselves
    """.split()
)

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_SOURCE_RE = re.compile(r"\[Source: (.*?)\]")
_SOURCE_SEPARATOR = "\n\n---\n\n"


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, drop stop words."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOP_WORDS]


def _bucket(token: str) -> int:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return int.from_bytes(digest, "big") % DIMENSIONS


def embed_text(text: str) -> list[float]:
    """1536-dim hashed bag of words, L2-normalised. No tokens -> fixed unit vector e0."""
    vec = [0.0] * DIMENSIONS
    tokens = tokenize(text)
    if not tokens:
        vec[0] = 1.0
        return vec
    for token in tokens:
        vec[_bucket(token)] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec]


def _encode_base64(vec: list[float]) -> str:
    return base64.b64encode(struct.pack(f"<{len(vec)}f", *vec)).decode("ascii")


def _error(status: int, message: str, err_type: str, code: str | None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": err_type, "param": None, "code": code}},
    )


def _unauthorized() -> JSONResponse:
    return _error(
        401,
        "Incorrect API key provided. (stub: the key sk-stub-invalid is always rejected)",
        "invalid_request_error",
        "invalid_api_key",
    )


async def _injected_failure(texts: list[str]) -> JSONResponse | None:
    """Apply the failure markers. Returns an error response, or None to continue."""
    joined = "\n".join(texts)
    if MARKER_RATE_LIMIT in joined:
        return _error(
            429,
            "Rate limit reached (stub: input contained __STUB_RATE_LIMIT__).",
            "requests",
            "rate_limit_exceeded",
        )
    if MARKER_FAIL in joined:
        return _error(
            400,
            "Invalid request (stub: input contained __STUB_FAIL__).",
            "invalid_request_error",
            None,
        )
    if MARKER_SLOW in joined:
        await asyncio.sleep(SLOW_SECONDS)
    return None


def _message_text(content: Any) -> str:
    """Chat message content may be a string or a list of content parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return str(content)


def simulated_answer(messages: list[dict]) -> str:
    """Deterministic answer text from the chat messages (DESIGN 4.7)."""
    last_user_index = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            last_user_index = i
            break
    final = _message_text(messages[last_user_index].get("content")) if last_user_index is not None else ""

    filenames: list[str] = []
    for name in _SOURCE_RE.findall(final):
        if name not in filenames:
            filenames.append(name)

    passage = ""
    match = _SOURCE_RE.search(final)
    if match:
        rest = final[match.end():]
        if rest.startswith("\n"):
            rest = rest[1:]
        passage = rest.split(_SOURCE_SEPARATOR, 1)[0]
        # The last passage is followed by the core's "---\n\nQuestion:" block.
        passage = re.split(r"\n\s*---\s*\n\s*Question:", passage, maxsplit=1)[0]
        passage = passage.strip()[:200]

    text = f"[Simulated answer] Based on {', '.join(filenames)}: {passage}"

    earlier = [
        m
        for i, m in enumerate(messages)
        if m.get("role") in ("user", "assistant") and i != last_user_index
    ]
    if earlier:
        text += f" (follow-up, {len(earlier)} earlier messages)"
    return text


def _approx_tokens(texts: list[str]) -> int:
    return sum(len(t.split()) for t in texts)


def _authorized(request: Request) -> bool:
    return request.headers.get("authorization", "").strip() != f"Bearer {INVALID_KEY}"


app = FastAPI(title="DocQABot OpenAI stub", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models(request: Request):
    if not _authorized(request):
        return _unauthorized()
    created = 1700000000
    return {
        "object": "list",
        "data": [
            {"id": EMBEDDING_MODEL, "object": "model", "created": created, "owned_by": "stub"},
            {"id": CHAT_MODEL, "object": "model", "created": created, "owned_by": "stub"},
        ],
    }


@app.post("/v1/embeddings")
async def embeddings(request: Request):
    if not _authorized(request):
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return _error(400, "Request body is not valid JSON.", "invalid_request_error", None)
    raw = body.get("input") if isinstance(body, dict) else None
    if isinstance(raw, str):
        texts = [raw]
    elif isinstance(raw, list) and raw and all(isinstance(x, str) for x in raw):
        texts = list(raw)
    else:
        return _error(
            400,
            "'input' must be a non-empty string or a non-empty list of strings.",
            "invalid_request_error",
            None,
        )
    if any(t == "" for t in texts):
        return _error(400, "'input' must not contain empty strings.", "invalid_request_error", None)

    failure = await _injected_failure(texts)
    if failure is not None:
        return failure

    as_base64 = body.get("encoding_format") == "base64"
    data = []
    for i, text in enumerate(texts):
        vec = embed_text(text)
        data.append(
            {
                "object": "embedding",
                "index": i,
                "embedding": _encode_base64(vec) if as_base64 else vec,
            }
        )
    tokens = _approx_tokens(texts)
    return {
        "object": "list",
        "data": data,
        "model": body.get("model") or EMBEDDING_MODEL,
        "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    if not _authorized(request):
        return _unauthorized()
    try:
        body = await request.json()
    except Exception:
        return _error(400, "Request body is not valid JSON.", "invalid_request_error", None)
    messages = body.get("messages") if isinstance(body, dict) else None
    if not isinstance(messages, list) or not messages or not all(isinstance(m, dict) for m in messages):
        return _error(400, "'messages' must be a non-empty list.", "invalid_request_error", None)

    texts = [_message_text(m.get("content")) for m in messages]
    failure = await _injected_failure(texts)
    if failure is not None:
        return failure

    content = simulated_answer(messages)
    prompt_tokens = _approx_tokens(texts)
    completion_tokens = len(content.split())
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:24]
    return {
        "id": f"chatcmpl-stub-{digest}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model") or CHAT_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content, "refusal": None},
                "finish_reason": "stop",
                "logprobs": None,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
