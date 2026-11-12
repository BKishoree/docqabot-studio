"""Contract tests C-H, C-D, C-C, C-E, C-X for /api/v1 (DESIGN section 4).

Field names, types, nullability and status codes are checked exactly as written in
section 4. Error codes that need a different process environment (no key, invalid
key, unreachable OpenAI, database down, auth on) are covered in tests/integration.
"""

from __future__ import annotations

import time
import uuid

import pytest

from tests.conftest import MAX_UPLOAD_MB
from tests.helpers import (
    API,
    CORRUPT_PDF,
    HANDBOOK_TXT,
    ISO_Z,
    NOT_FOUND_ANSWER,
    PDF_TEXT,
    UNRELATED_QUESTION,
    UUID_RE,
    ask,
    assert_error,
    make_pdf,
    new_conversation,
    upload,
    upload_ready,
    wait_for_document,
)

pytestmark = [pytest.mark.app, pytest.mark.db]

DOC_KEYS = {"id", "filename", "status", "created_at", "processed_at", "size_bytes", "chunk_count", "error"}
CONV_KEYS = {"id", "title", "created_at", "updated_at", "message_count"}
MSG_KEYS = {"id", "role", "content", "created_at", "grounded", "citations"}
CIT_KEYS = {"rank", "document_id", "document_available", "filename", "chunk_index", "similarity", "text"}
LIMIT = MAX_UPLOAD_MB * 1024 * 1024


def raw_multipart(filename_header: bytes, data: bytes, field: bytes = b"file"):
    boundary = b"docqabotboundary7d1"
    body = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="' + field + b'"; filename="' + filename_header + b'"\r\n'
        b"Content-Type: text/plain\r\n\r\n" + data + b"\r\n--" + boundary + b"--\r\n"
    )
    return body, {"Content-Type": "multipart/form-data; boundary=" + boundary.decode()}


def assert_document(doc: dict) -> None:
    assert set(doc) == DOC_KEYS, doc
    assert isinstance(doc["id"], int) and not isinstance(doc["id"], bool)
    assert isinstance(doc["filename"], str)
    assert doc["status"] in {"processing", "ready", "failed"}
    assert ISO_Z.match(doc["created_at"]), doc["created_at"]
    assert doc["processed_at"] is None or ISO_Z.match(doc["processed_at"]), doc["processed_at"]
    assert doc["size_bytes"] is None or isinstance(doc["size_bytes"], int)
    assert isinstance(doc["chunk_count"], int)
    if doc["status"] == "failed":
        assert set(doc["error"]) == {"code", "message"}, doc["error"]
        assert doc["error"]["code"] in {"processing_failed", "openai_auth", "openai_unreachable", "interrupted"}
        assert isinstance(doc["error"]["message"], str) and doc["error"]["message"]
    else:
        assert doc["error"] is None
    if doc["status"] != "ready":
        assert doc["chunk_count"] == 0


def assert_conversation(c: dict, extra: set = frozenset()) -> None:
    assert set(c) == CONV_KEYS | set(extra), c
    assert UUID_RE.match(c["id"]), c["id"]
    assert isinstance(c["title"], str) and 1 <= len(c["title"]) <= 120
    assert ISO_Z.match(c["created_at"]) and ISO_Z.match(c["updated_at"]), c
    assert isinstance(c["message_count"], int)


def assert_message(m: dict) -> None:
    assert set(m) == MSG_KEYS, m
    assert isinstance(m["id"], int)
    assert m["role"] in {"user", "assistant"}
    assert isinstance(m["content"], str)
    assert ISO_Z.match(m["created_at"])
    assert isinstance(m["citations"], list)
    if m["role"] == "user":
        assert m["grounded"] is None and m["citations"] == []
    else:
        assert isinstance(m["grounded"], bool)
        if not m["grounded"]:
            assert m["citations"] == []
        assert len(m["citations"]) <= 5
        assert [c["rank"] for c in m["citations"]] == list(range(1, len(m["citations"]) + 1))
        for c in m["citations"]:
            assert set(c) == CIT_KEYS, c
            assert c["document_id"] is None or isinstance(c["document_id"], int)
            assert isinstance(c["document_available"], bool)
            assert c["document_available"] == (c["document_id"] is not None)
            assert isinstance(c["filename"], str)
            assert c["chunk_index"] is None or isinstance(c["chunk_index"], int)
            assert isinstance(c["similarity"], float | int) and 0 <= c["similarity"] <= 1
            assert round(c["similarity"], 4) == c["similarity"]
            assert isinstance(c["text"], str) and c["text"]


def doc_total(client) -> int:
    return client.get(f"{API}/documents").json()["total"]


# ------------------------------------------------------------------ health/config
def test_CH1_live(client):
    r = client.get(f"{API}/health/live")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert r.headers.get("x-request-id")


def test_CH2_health_shape(client):
    r = client.get(f"{API}/health", params={"refresh": "true"})
    assert r.status_code == 200
    h = r.json()
    assert set(h) == {"status", "version", "mode", "auth_enabled", "components"}
    assert h["status"] == "ok", h
    assert h["mode"] == "live" and h["auth_enabled"] is False and isinstance(h["version"], str)
    assert set(h["components"]) == {"database", "openai"}
    assert h["components"]["database"] == {"status": "ok", "detail": None}
    oai = h["components"]["openai"]
    assert set(oai) == {"status", "detail", "checked_at"}
    assert oai["status"] == "ok"
    assert ISO_Z.match(oai["checked_at"])
    assert "sk-stub-test" not in r.text


def test_CH3_health_probe_cached_and_refresh(client):
    first = client.get(f"{API}/health", params={"refresh": "true"}).json()["components"]["openai"]["checked_at"]
    time.sleep(1.1)
    cached = client.get(f"{API}/health").json()["components"]["openai"]["checked_at"]
    assert cached == first, "probe not cached"
    refreshed = client.get(f"{API}/health", params={"refresh": "true"}).json()["components"]["openai"]["checked_at"]
    assert refreshed > first, "refresh=true did not re-probe"


def test_CH4_config_exact(client):
    r = client.get(f"{API}/config")
    assert r.status_code == 200
    cfg = r.json()
    assert cfg == {
        "version": cfg["version"],
        "mode": "live",
        "max_upload_bytes": LIMIT,
        "allowed_extensions": [".pdf", ".md", ".txt"],
        "max_question_chars": 2000,
        "embedding_model": "text-embedding-3-small",
        "chat_model": "gpt-4o-mini",
        "retrieval": {"top_k": 5, "min_similarity": 0.3},
    }
    assert cfg["version"] == client.get(f"{API}/health").json()["version"]


# ------------------------------------------------------------------ documents
def test_CD1_upload_returns_202_processing_document(client):
    data = HANDBOOK_TXT.encode()
    r = upload(client, "handbook.txt", data, "text/plain")
    assert r.status_code == 202, r.text
    doc = r.json()
    assert_document(doc)
    assert doc["status"] == "processing"
    assert doc["filename"] == "handbook.txt"
    assert doc["size_bytes"] == len(data)
    assert doc["processed_at"] is None and doc["chunk_count"] == 0 and doc["error"] is None


def test_CD2_list_envelope_newest_first(client):
    a = upload_ready(client, "a.txt", HANDBOOK_TXT)
    time.sleep(0.05)
    b = upload_ready(client, "b.md", "# B\n\nBeta content about gardens.")
    r = client.get(f"{API}/documents")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total"} and body["total"] == 2
    assert [d["id"] for d in body["items"]] == [b["id"], a["id"]]
    for d in body["items"]:
        assert_document(d)


def test_CD3_get_ready_document(client):
    data = HANDBOOK_TXT.encode()
    doc = upload_ready(client, "handbook.txt", data)
    r = client.get(f"{API}/documents/{doc['id']}")
    assert r.status_code == 200
    d = r.json()
    assert_document(d)
    assert d["status"] == "ready" and d["chunk_count"] >= 1 and d["size_bytes"] == len(data)
    assert ISO_Z.match(d["processed_at"])
    assert d["processed_at"] >= d["created_at"]


def test_CD4_unknown_document_404(client):
    assert_error(client.get(f"{API}/documents/999999"), 404, "not_found")
    assert_error(client.delete(f"{API}/documents/999999"), 404, "not_found")


def test_CD5_non_integer_document_id_is_validation_error(client):
    err = assert_error(client.get(f"{API}/documents/abc"), 422, "validation_error")
    assert isinstance(err["details"]["fields"], list) and err["details"]["fields"]


def test_CD6_delete_204_then_gone(client):
    doc = upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    r = client.delete(f"{API}/documents/{doc['id']}")
    assert r.status_code == 204 and r.content == b""
    assert_error(client.get(f"{API}/documents/{doc['id']}"), 404, "not_found")


def test_CD7_core_uploaded_document_has_null_meta(client):
    r = client.post("/upload", files={"file": ("core.txt", HANDBOOK_TXT.encode(), "text/plain")})
    assert r.status_code == 200, r.text
    doc = wait_for_document(client, r.json()["document_id"])
    assert_document(doc)
    assert doc["size_bytes"] is None
    assert doc["processed_at"] is None


def test_CD8_failed_document_carries_error_object(client):
    r = upload(client, "boom.txt", "This file makes the stub fail __STUB_FAIL__ during embedding.")
    assert r.status_code == 202
    doc = wait_for_document(client, r.json()["id"])
    assert_document(doc)
    assert doc["status"] == "failed" and doc["error"]["code"] == "processing_failed", doc
    assert doc["chunk_count"] == 0
    assert ISO_Z.match(doc["processed_at"] or "")


@pytest.mark.parametrize(
    "name,data,ctype",
    [
        ("notes.md", "# Notes\n\nMarkdown body text.", "text/markdown"),
        ("REPORT.PDF", make_pdf([PDF_TEXT]), "application/pdf"),
        ("Mixed.Txt", "case insensitive extension", "text/plain"),
    ],
)
def test_CD9_accepted_types_case_insensitive(client, name, data, ctype):
    r = upload(client, name, data, ctype)
    assert r.status_code == 202, r.text
    assert wait_for_document(client, r.json()["id"])["status"] == "ready"


# ------------------------------------------------------------------ upload errors
def test_CE_empty_file(client):
    err = assert_error(upload(client, "empty.txt", b""), 400, "empty_file")
    assert doc_total(client) == 0, err


def test_CE_invalid_filename_too_long(client):
    assert_error(upload(client, "a" * 197 + ".txt", "text"), 400, "invalid_filename")
    assert doc_total(client) == 0


def test_CE_invalid_filename_200_chars_is_ok(client):
    assert upload(client, "a" * 196 + ".txt", "text body").status_code == 202


def test_CE_invalid_filename_control_character(client):
    body, headers = raw_multipart(b"bad\x01name.txt", b"some text")
    assert_error(client.post(f"{API}/documents", content=body, headers=headers), 400, "invalid_filename")
    assert doc_total(client) == 0


def test_CE_invalid_filename_missing(client):
    body, headers = raw_multipart(b"", b"some text")
    r = client.post(f"{API}/documents", content=body, headers=headers)
    # Starlette may treat a part with filename="" as a plain form field; both are a rejected name.
    assert r.status_code in (400, 422), r.text
    assert_error(r, r.status_code, "invalid_filename" if r.status_code == 400 else "validation_error")
    assert doc_total(client) == 0


def test_CE_unsupported_file_type(client):
    err = assert_error(upload(client, "report.docx", b"PK\x03\x04data"), 415, "unsupported_file_type")
    assert doc_total(client) == 0, err


def test_CE_order_extension_before_empty(client):
    assert_error(upload(client, "empty.docx", b""), 415, "unsupported_file_type")


def test_CE_file_too_large(client):
    err = assert_error(upload(client, "big.txt", b"a" * (LIMIT + 1)), 413, "file_too_large")
    assert err["details"]["limit_bytes"] == LIMIT
    assert err["details"]["size_bytes"] == LIMIT + 1
    assert doc_total(client) == 0


@pytest.mark.slow
def test_CE_file_exactly_at_limit_is_accepted(client):
    line = b"limit boundary text line number filler words\n"
    data = (line * (LIMIT // len(line) + 1))[:LIMIT]
    r = upload(client, "atlimit.txt", data)
    assert r.status_code == 202, r.text[:300]


def test_CE_invalid_encoding(client):
    assert_error(upload(client, "latin.txt", "café crème".encode("latin-1")), 400, "invalid_encoding")
    assert_error(upload(client, "utf16.md", "hello".encode("utf-16")), 400, "invalid_encoding")
    assert doc_total(client) == 0


def test_CE_no_extractable_text_pdf(client):
    assert_error(upload(client, "scan.pdf", make_pdf([""]), "application/pdf"), 422, "no_extractable_text")
    assert doc_total(client) == 0


def test_CE_no_extractable_text_whitespace_txt(client):
    assert_error(upload(client, "blank.txt", b"  \n\n\t \n"), 422, "no_extractable_text")
    assert doc_total(client) == 0


def test_CE_unreadable_file(client):
    assert_error(upload(client, "corrupt.pdf", CORRUPT_PDF, "application/pdf"), 422, "unreadable_file")
    assert doc_total(client) == 0


def test_CE_validation_error_missing_file_field(client):
    err = assert_error(client.post(f"{API}/documents", data={"other": "x"}), 422, "validation_error")
    assert isinstance(err["details"]["fields"], list)


# ------------------------------------------------------------------ conversations
def test_CC1_create_default_title(client):
    r = client.post(f"{API}/conversations", json={})
    assert r.status_code == 201
    c = r.json()
    assert_conversation(c)
    assert c["title"] == "New conversation" and c["message_count"] == 0


def test_CC2_create_with_title_and_bounds(client):
    c = new_conversation(client, "Quarterly review")
    assert c["title"] == "Quarterly review"
    assert new_conversation(client, "x" * 120)["title"] == "x" * 120
    for bad in ("", "x" * 121):
        err = assert_error(client.post(f"{API}/conversations", json={"title": bad}), 422, "validation_error")
        assert any(f["field"] == "title" for f in err["details"]["fields"]), err


def test_CC3_list_paging_and_order(client):
    ids = []
    for i in range(3):
        ids.append(new_conversation(client, f"c{i}")["id"])
        time.sleep(0.02)
    r = client.get(f"{API}/conversations", params={"limit": 2, "offset": 0})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total"} and body["total"] == 3
    assert [c["id"] for c in body["items"]] == [ids[2], ids[1]]
    for c in body["items"]:
        assert_conversation(c)
    page2 = client.get(f"{API}/conversations", params={"limit": 2, "offset": 2}).json()
    assert [c["id"] for c in page2["items"]] == [ids[0]] and page2["total"] == 3
    default = client.get(f"{API}/conversations").json()
    assert len(default["items"]) == 3


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"limit": "abc"}])
def test_CC4_list_limit_bounds(client, params):
    assert_error(client.get(f"{API}/conversations", params=params), 422, "validation_error")


def test_CC4_list_limit_200_ok(client):
    assert client.get(f"{API}/conversations", params={"limit": 200}).status_code == 200


def test_CC5_get_detail(client):
    c = new_conversation(client)
    r = client.get(f"{API}/conversations/{c['id']}")
    assert r.status_code == 200
    d = r.json()
    assert_conversation(d, {"messages"})
    assert d["messages"] == []


def test_CC6_patch_title(client):
    c = new_conversation(client)
    r = client.patch(f"{API}/conversations/{c['id']}", json={"title": "Renamed"})
    assert r.status_code == 200
    s = r.json()
    assert_conversation(s)
    assert s["title"] == "Renamed"
    assert client.get(f"{API}/conversations/{c['id']}").json()["title"] == "Renamed"
    assert_error(client.patch(f"{API}/conversations/{c['id']}", json={"title": ""}), 422, "validation_error")
    assert_error(client.patch(f"{API}/conversations/{c['id']}", json={}), 422, "validation_error")
    assert_error(client.patch(f"{API}/conversations/{uuid.uuid4()}", json={"title": "x"}), 404, "not_found")


def test_CC7_delete(client):
    c = new_conversation(client)
    r = client.delete(f"{API}/conversations/{c['id']}")
    assert r.status_code == 204 and r.content == b""
    assert_error(client.get(f"{API}/conversations/{c['id']}"), 404, "not_found")
    assert_error(client.delete(f"{API}/conversations/{c['id']}"), 404, "not_found")


def test_CC8_unknown_and_malformed_conversation_ids(client):
    assert_error(client.get(f"{API}/conversations/{uuid.uuid4()}"), 404, "not_found")
    r = client.get(f"{API}/conversations/not-a-uuid")
    assert r.status_code in (404, 422), r.text
    assert_error(r, r.status_code, "not_found" if r.status_code == 404 else "validation_error")
    assert_error(ask(client, str(uuid.uuid4()), "anything"), 404, "not_found")


def test_CC9_ask_response_shape(client):
    upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    c = new_conversation(client)
    q = "How many paid vacation days do full-time employees accrue per calendar year?"
    r = ask(client, c["id"], q)
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"conversation", "user_message", "assistant_message"}
    assert_conversation(body["conversation"])
    assert body["conversation"]["message_count"] == 2
    assert body["conversation"]["title"] == q[:60]
    assert_message(body["user_message"])
    assert_message(body["assistant_message"])
    assert body["user_message"]["content"] == q
    a = body["assistant_message"]
    assert a["role"] == "assistant" and a["grounded"] is True and a["citations"]
    assert a["citations"][0]["filename"] == "handbook.txt"
    assert body["user_message"]["id"] < a["id"]
    detail = client.get(f"{API}/conversations/{c['id']}").json()
    assert [m["id"] for m in detail["messages"]] == [body["user_message"]["id"], a["id"]]
    for m in detail["messages"]:
        assert_message(m)


def test_CC10_not_grounded_answer_shape(client):
    upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    c = new_conversation(client)
    r = ask(client, c["id"], UNRELATED_QUESTION)
    assert r.status_code == 201, r.text
    a = r.json()["assistant_message"]
    assert_message(a)
    assert a["grounded"] is False and a["citations"] == [] and a["content"] == NOT_FOUND_ANSWER


@pytest.mark.parametrize(
    "payload", [{}, {"question": ""}, {"question": "   \n "}, {"question": "x" * 2001}, {"question": 42}]
)
def test_CE_question_validation(client, payload):
    upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    c = new_conversation(client)
    err = assert_error(client.post(f"{API}/conversations/{c['id']}/messages", json=payload), 422, "validation_error")
    assert any(f["field"] == "question" for f in err["details"]["fields"]), err
    assert client.get(f"{API}/conversations/{c['id']}").json()["message_count"] == 0


def test_CE_question_2000_chars_after_trim_ok(client):
    upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    c = new_conversation(client)
    q = "  " + ("vacation " * 300)[:2000] + "  "
    assert len(q.strip()) <= 2000
    r = ask(client, c["id"], q)
    assert r.status_code == 201, r.text


def test_CE_no_ready_documents(client):
    c = new_conversation(client)
    assert_error(ask(client, c["id"], "What is the vacation policy?"), 409, "no_ready_documents")
    assert client.get(f"{API}/conversations/{c['id']}").json()["message_count"] == 0


def test_CE_openai_error_from_stub_400(client):
    upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    c = new_conversation(client)
    assert_error(ask(client, c["id"], "vacation __STUB_FAIL__"), 502, "openai_error")
    assert client.get(f"{API}/conversations/{c['id']}").json()["message_count"] == 0


def test_CE_openai_rate_limited(client):
    upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    c = new_conversation(client)
    assert_error(ask(client, c["id"], "vacation __STUB_RATE_LIMIT__"), 503, "openai_rate_limited")
    assert client.get(f"{API}/conversations/{c['id']}").json()["message_count"] == 0


def test_CE_internal_error_envelope_hides_internals(client, studio_app):
    """internal_error via a test-only route added to the app for this test only (DESIGN 4.7)."""
    secret = "TOPSECRET-internal-detail"

    def boom():
        raise RuntimeError(secret)

    path = f"{API}/__tester_internal_error__"
    studio_app.add_api_route(path, boom, methods=["POST"])
    try:
        r = client.post(path)
        err = assert_error(r, 500, "internal_error")
        assert secret not in r.text and "Traceback" not in r.text, err
    finally:
        studio_app.router.routes[:] = [rt for rt in studio_app.router.routes if getattr(rt, "path", None) != path]


# ------------------------------------------------------------------ cross-cutting
def test_CX1_every_response_has_request_id(client):
    c = new_conversation(client)
    responses = [
        client.get(f"{API}/health/live"),
        client.get(f"{API}/health"),
        client.get(f"{API}/config"),
        client.get(f"{API}/documents"),
        client.get(f"{API}/conversations"),
        client.get(f"{API}/conversations/{c['id']}"),
        client.get(f"{API}/documents/424242"),
        client.get(f"{API}/no-such-route"),
        client.get("/documents"),
        client.get("/openapi.json"),
    ]
    ids = [r.headers.get("x-request-id") for r in responses]
    assert all(ids), list(zip([r.request.url.path for r in responses], ids))
    assert len(set(ids)) == len(ids), "request ids are not unique"


def test_CX2_unknown_api_route_is_404(client):
    r = client.get(f"{API}/no-such-route")
    assert r.status_code == 404
