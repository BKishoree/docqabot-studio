"""OpenAI-compatible stub used by demo mode and every automated test (DESIGN 4.7).

``studio.stub:app`` is the ASGI app. Importing this package is side-effect free:
no ``studio.bootstrap``, no ``app.*``, no environment changes, no network, no DB.
"""

from studio.stub.server import (
    CHAT_MODEL,
    DIMENSIONS,
    EMBEDDING_MODEL,
    INVALID_KEY,
    app,
    embed_text,
    simulated_answer,
    tokenize,
)

__all__ = [
    "CHAT_MODEL",
    "DIMENSIONS",
    "EMBEDDING_MODEL",
    "INVALID_KEY",
    "app",
    "embed_text",
    "simulated_answer",
    "tokenize",
]
