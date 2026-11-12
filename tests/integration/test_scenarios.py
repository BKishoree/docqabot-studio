"""I-S1..S12, I-MIG-1, I-ORPH-1: scenarios through the API, in-process (TestClient)."""

from __future__ import annotations

import re

import pytest

from tests.helpers import (
    API,
    GARDEN_MD,
    HANDBOOK_TXT,
    NOT_FOUND_ANSWER,
    PDF_TEXT,
    UNRELATED_QUESTION,
    ask,
    assert_error,
    make_pdf,
    new_conversation,
    upload,
    upload_ready,
    wait_for_document,
)

pytestmark = [pytest.mark.app, pytest.mark.db]
VACATION_Q = "How many paid vacation days do full-time employees accrue per calendar year?"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def chunk_rows(db, doc_id):
    with db.cursor() as cur:
        cur.execute("SELECT chunk_index, content FROM chunks WHERE document_id = %s ORDER BY chunk_index", (doc_id,))
        return cur.fetchall()


def count(db, table, where="TRUE", args=()):
    with db.cursor() as cur:
        cur.execute(f"SELECT count(*) AS n FROM {table} WHERE {where}", args)
        return cur.fetchone()["n"]


# --------------------------------------------------------------------------- S1
@pytest.mark.parametrize(
    "name,data,ctype",
    [
        ("handbook.txt", HANDBOOK_TXT.encode(), "text/plain"),
        ("garden.md", GARDEN_MD.encode(), "text/markdown"),
        ("invoices.pdf", make_pdf([PDF_TEXT, "Second page about vendor onboarding."]), "application/pdf"),
    ],
)
def test_IS1_upload_becomes_ready_with_chunks(client, db, name, data, ctype):
    r = upload(client, name, data, ctype)
    assert r.status_code == 202, r.text
    doc = wait_for_document(client, r.json()["id"])
    assert doc["status"] == "ready", doc
    rows = chunk_rows(db, doc["id"])
    assert doc["chunk_count"] == len(rows) >= 1
    assert [row["chunk_index"] for row in rows] == list(range(len(rows)))
    assert doc["size_bytes"] == len(data)
    with db.cursor() as cur:
        cur.execute("SELECT size_bytes, processed_at FROM studio_document_meta WHERE document_id = %s", (doc["id"],))
        meta = cur.fetchone()
    assert meta["size_bytes"] == len(data) and meta["processed_at"] is not None


def test_IS1_multi_chunk_document(client, db):
    paras = [" ".join(f"topic{i}word{j}" for j in range(120)) for i in range(10)]
    doc = upload_ready(client, "long.txt", "\n\n".join(paras))
    assert doc["chunk_count"] == len(chunk_rows(db, doc["id"])) >= 3


# --------------------------------------------------------------------------- S2
def test_IS2_cited_answer_passage_exists_in_file(client, db):
    doc = upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    upload_ready(client, "garden.md", GARDEN_MD)
    c = new_conversation(client)
    r = ask(client, c["id"], VACATION_Q)
    assert r.status_code == 201, r.text
    a = r.json()["assistant_message"]
    assert a["grounded"] is True and a["citations"]
    top = a["citations"][0]
    assert top["filename"] == "handbook.txt" and top["document_id"] == doc["id"]
    assert top["document_available"] is True
    assert norm(top["text"]) in norm(HANDBOOK_TXT), "cited passage is not text from the uploaded file"
    rows = {row["chunk_index"]: row["content"] for row in chunk_rows(db, doc["id"])}
    assert rows[top["chunk_index"]] == top["text"]
    assert top["similarity"] > 0.3
    sims = [ct["similarity"] for ct in a["citations"]]
    assert sims == sorted(sims, reverse=True)
    assert a["content"].startswith("[Simulated answer] Based on handbook.txt")
    assert "garden.md" not in [ct["filename"] for ct in a["citations"]]


def test_IS2_answer_persisted_with_citations(client, db):
    upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    c = new_conversation(client)
    a = ask(client, c["id"], VACATION_Q).json()["assistant_message"]
    assert count(db, "studio_messages", "conversation_id = %s", (c["id"],)) == 2
    assert count(db, "studio_citations", "message_id = %s", (a["id"],)) == len(a["citations"])
    stored = client.get(f"{API}/conversations/{c['id']}").json()["messages"][1]
    assert stored == a


# --------------------------------------------------------------------------- S3
def test_IS3_follow_up_sends_history(client):
    upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    c = new_conversation(client)
    first = ask(client, c["id"], VACATION_Q).json()["assistant_message"]["content"]
    assert "follow-up" not in first
    second = ask(client, c["id"], "Do unused vacation days carry over?").json()
    assert second["assistant_message"]["content"].endswith(" (follow-up, 2 earlier messages)")
    third = ask(client, c["id"], "What about remote work on Tuesdays?").json()
    assert third["assistant_message"]["content"].endswith(" (follow-up, 4 earlier messages)")
    # core keeps only the last 4 history messages
    fourth = ask(client, c["id"], "Remote work approval by manager?").json()
    assert fourth["assistant_message"]["content"].endswith(" (follow-up, 4 earlier messages)")
    assert fourth["conversation"]["message_count"] == 8
    assert fourth["conversation"]["title"] == VACATION_Q[:60]


def test_IS3_history_is_per_conversation(client):
    upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    c1, c2 = new_conversation(client), new_conversation(client)
    ask(client, c1["id"], VACATION_Q)
    other = ask(client, c2["id"], VACATION_Q).json()["assistant_message"]["content"]
    assert "follow-up" not in other


# --------------------------------------------------------------------------- S4
def test_IS4_not_covered_question(client, db):
    upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    c = new_conversation(client)
    a = ask(client, c["id"], UNRELATED_QUESTION).json()["assistant_message"]
    assert a["grounded"] is False and a["citations"] == [] and a["content"] == NOT_FOUND_ANSWER
    assert count(db, "studio_citations") == 0


# --------------------------------------------------------------------------- S5
def test_IS5_processing_failure_shows_failed(client, db):
    r = upload(client, "boom.md", "# Title\n\nThe embedding call fails here __STUB_FAIL__.")
    doc = wait_for_document(client, r.json()["id"])
    assert doc["status"] == "failed" and doc["error"]["code"] == "processing_failed"
    assert doc["error"]["message"]
    assert chunk_rows(db, doc["id"]) == []
    # a failed document does not count as ready
    c = new_conversation(client)
    assert_error(ask(client, c["id"], "title embedding"), 409, "no_ready_documents")
    # and can be deleted
    assert client.delete(f"{API}/documents/{doc['id']}").status_code == 204


def test_IORPH1_processing_document_is_failed_interrupted_at_startup(studio_app, clean_db, db):
    from fastapi.testclient import TestClient

    with TestClient(studio_app) as c1:
        doc = upload_ready(c1, "handbook.txt", HANDBOOK_TXT)
    with db.cursor() as cur:
        cur.execute("DELETE FROM chunks WHERE document_id = %s", (doc["id"],))
        cur.execute("UPDATE documents SET status = 'processing' WHERE id = %s", (doc["id"],))
        cur.execute("UPDATE studio_document_meta SET processed_at = NULL WHERE document_id = %s", (doc["id"],))
    with TestClient(studio_app) as c2:
        d = c2.get(f"{API}/documents/{doc['id']}").json()
    assert d["status"] == "failed" and d["error"]["code"] == "interrupted", d


# --------------------------------------------------------------------------- S6
def test_IS6_delete_document_cascades_and_citations_survive(client, db):
    doc = upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    c = new_conversation(client)
    before = ask(client, c["id"], VACATION_Q).json()["assistant_message"]
    passage = before["citations"][0]["text"]

    assert client.delete(f"{API}/documents/{doc['id']}").status_code == 204
    assert count(db, "chunks", "document_id = %s", (doc["id"],)) == 0
    assert count(db, "studio_document_meta", "document_id = %s", (doc["id"],)) == 0
    assert count(db, "documents", "id = %s", (doc["id"],)) == 0

    old = client.get(f"{API}/conversations/{c['id']}").json()["messages"][1]
    cit = old["citations"][0]
    assert cit["document_id"] is None and cit["document_available"] is False
    assert cit["text"] == passage and cit["filename"] == "handbook.txt"

    # out of retrieval immediately: the only document is gone
    assert_error(ask(client, c["id"], VACATION_Q), 409, "no_ready_documents")
    upload_ready(client, "garden.md", GARDEN_MD)
    again = ask(client, c["id"], VACATION_Q).json()["assistant_message"]
    assert "handbook.txt" not in [x["filename"] for x in again["citations"]]


# --------------------------------------------------------------------------- S7
def test_IS7_conversations_survive_restart(studio_app, clean_db):
    from fastapi.testclient import TestClient

    with TestClient(studio_app) as c1:
        upload_ready(c1, "handbook.txt", HANDBOOK_TXT)
        conv = new_conversation(c1, "Keep me")
        ans = ask(c1, conv["id"], VACATION_Q).json()
        detail_before = c1.get(f"{API}/conversations/{conv['id']}").json()
    with TestClient(studio_app) as c2:
        listing = c2.get(f"{API}/conversations").json()
        assert [x["id"] for x in listing["items"]] == [conv["id"]]
        detail_after = c2.get(f"{API}/conversations/{conv['id']}").json()
    assert detail_after == detail_before
    assert detail_after["messages"][1]["citations"] == ans["assistant_message"]["citations"]


# --------------------------------------------------------------------------- S10
@pytest.mark.parametrize(
    "name,data,status,code",
    [
        ("a.exe", b"MZ", 415, "unsupported_file_type"),
        ("a.txt", b"", 400, "empty_file"),
        ("a.txt", b"\xff\xfe\x00bad", 400, "invalid_encoding"),
        ("a.pdf", make_pdf([""]), 422, "no_extractable_text"),
        ("a.pdf", b"%PDF-1.4 broken", 422, "unreadable_file"),
    ],
)
def test_IS10_rejections_store_nothing(client, db, name, data, status, code):
    assert_error(upload(client, name, data), status, code)
    for table in ("documents", "chunks", "studio_document_meta"):
        assert count(db, table) == 0, table


# --------------------------------------------------------------------------- S12
def test_IS12_rename_and_delete_conversation_cascades(client, db):
    upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    c = new_conversation(client)
    ask(client, c["id"], VACATION_Q)
    r = client.patch(f"{API}/conversations/{c['id']}", json={"title": "Vacation questions"})
    assert r.json()["title"] == "Vacation questions"
    # rename does not get overwritten by the next question
    ask(client, c["id"], "Do unused vacation days carry over?")
    assert client.get(f"{API}/conversations/{c['id']}").json()["title"] == "Vacation questions"
    assert client.delete(f"{API}/conversations/{c['id']}").status_code == 204
    assert count(db, "studio_messages") == 0 and count(db, "studio_citations") == 0


def test_IS12_updated_at_bumped_by_question(client):
    upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    old = new_conversation(client, "old")
    new = new_conversation(client, "new")
    ask(client, old["id"], VACATION_Q)
    items = client.get(f"{API}/conversations").json()["items"]
    assert [x["id"] for x in items] == [old["id"], new["id"]]
    assert items[0]["updated_at"] >= old["updated_at"]


# --------------------------------------------------------------------------- migrations
def test_IMIG1_migrations_idempotent(studio_app, clean_db, db):
    from fastapi.testclient import TestClient

    for _ in range(2):
        with TestClient(studio_app) as c:
            assert c.get(f"{API}/health/live").status_code == 200
    with db.cursor() as cur:
        cur.execute("SELECT version FROM studio_schema_migrations ORDER BY version")
        versions = [r["version"] for r in cur.fetchall()]
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'studio_%%' ORDER BY 1"
        )
        tables = [r["table_name"] for r in cur.fetchall()]
    assert versions and len(versions) == len(set(versions))
    assert any(v.startswith("001") for v in versions), versions
    assert set(tables) >= {
        "studio_schema_migrations", "studio_document_meta", "studio_conversations", "studio_messages", "studio_citations"
    }


def test_IMIG2_core_tables_untouched(clean_db, db, client):
    with db.cursor() as cur:
        cur.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_name IN ('documents','chunks') ORDER BY table_name, ordinal_position"
        )
        cols = [(r["table_name"], r["column_name"]) for r in cur.fetchall()]
    assert cols == [
        ("chunks", "id"), ("chunks", "document_id"), ("chunks", "content"), ("chunks", "embedding"),
        ("chunks", "chunk_index"),
        ("documents", "id"), ("documents", "filename"), ("documents", "status"), ("documents", "created_at"),
    ]


def test_IORPH2_core_uploaded_processing_document_is_processing_failed(studio_app, clean_db, db):
    """DESIGN v1.3 (d): a core-/upload document (no meta row) left in processing -> failed / processing_failed."""
    from fastapi.testclient import TestClient

    with db.cursor() as cur:
        cur.execute("INSERT INTO documents (filename, status) VALUES ('core.txt', 'processing') RETURNING id")
        doc_id = cur.fetchone()["id"]
    with TestClient(studio_app) as c:
        d = c.get(f"{API}/documents/{doc_id}").json()
    assert d["status"] == "failed" and d["error"]["code"] == "processing_failed", d
    assert d["size_bytes"] is None
