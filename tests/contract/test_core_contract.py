"""C-CORE-1..4: the three core endpoints keep their shapes under Studio (DESIGN 4.6, AC14)."""

from __future__ import annotations

import re

import pytest

from tests.conftest import MAX_UPLOAD_MB
from tests.helpers import HANDBOOK_TXT, NOT_FOUND_ANSWER, wait_for_document

pytestmark = [pytest.mark.app, pytest.mark.db]
NAIVE_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$")


def test_CCORE1_upload_shape(client):
    r = client.post("/upload", files={"file": ("h.txt", HANDBOOK_TXT.encode(), "text/plain")})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"message", "document_id", "status"}
    assert body["message"] == "Document uploaded" and body["status"] == "processing"
    assert isinstance(body["document_id"], int)


@pytest.mark.parametrize(
    "name,data,detail",
    [
        ("x.docx", b"abc", "File type not supported. Use: ['.txt', '.md', '.pdf']"),
        ("x.txt", "café".encode("latin-1"), "File must be UTF-8 encoded text"),
        ("x.txt", b"   \n", "No text could be extracted from the file"),
    ],
)
def test_CCORE1_upload_errors_are_fastapi_detail(client, name, data, detail):
    r = client.post("/upload", files={"file": (name, data, "text/plain")})
    assert r.status_code == 400
    assert r.json() == {"detail": detail}


def test_CCORE1_upload_validation_is_fastapi_default(client):
    r = client.post("/upload")
    assert r.status_code == 422
    assert set(r.json()) == {"detail"} and isinstance(r.json()["detail"], list)


def test_CCORE2_documents_shape(client):
    doc_id = client.post("/upload", files={"file": ("h.txt", HANDBOOK_TXT.encode(), "text/plain")}).json()[
        "document_id"
    ]
    wait_for_document(client, doc_id)
    r = client.get("/documents")
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list) and len(items) == 1
    d = items[0]
    assert set(d) == {"id", "filename", "status", "created_at"}
    assert d["id"] == doc_id and d["filename"] == "h.txt" and d["status"] == "ready"
    assert NAIVE_TS.match(d["created_at"]), d["created_at"]


def test_CCORE3_ask_shape(client):
    doc_id = client.post("/upload", files={"file": ("h.txt", HANDBOOK_TXT.encode(), "text/plain")}).json()[
        "document_id"
    ]
    wait_for_document(client, doc_id)
    r = client.post("/ask", json={"question": "How many paid vacation days do employees accrue?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"answer", "sources"}
    assert body["sources"] == ["h.txt"]
    assert body["answer"].startswith("[Simulated answer] Based on h.txt:")
    r2 = client.post(
        "/ask",
        json={"question": "zebra quantum saxophone", "chat_history": [{"role": "user", "content": "hi"}]},
    )
    assert r2.status_code == 200 and r2.json() == {"answer": NOT_FOUND_ANSWER, "sources": []}


def test_CCORE3_ask_validation_is_fastapi_default(client):
    r = client.post("/ask", json={})
    assert r.status_code == 422 and set(r.json()) == {"detail"}


def test_CCORE4_global_size_limit_applies_to_core_upload(client):
    big = b"a" * (MAX_UPLOAD_MB * 1024 * 1024 + 4096)
    r = client.post("/upload", files={"file": ("big.txt", big, "text/plain")})
    assert r.status_code == 413
    assert client.get("/documents").json() == []
