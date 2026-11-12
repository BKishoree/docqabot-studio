"""I-RETRY: recording a document's outcome is retried while the database is briefly unavailable.

White-box test (proposed by BACKEND): it patches studio internals
(`RECORD_RETRY_INTERVAL_S`, `studio.db.connection`) because a sub-second DB blip
cannot be produced reliably through the public API.
"""

from __future__ import annotations

import contextlib

import pytest

from tests.conftest import need_module
from tests.helpers import API, HANDBOOK_TXT, upload_ready

pytestmark = [pytest.mark.app, pytest.mark.db]


def _flaky_connection(monkeypatch, fail_times: int):
    db = need_module("studio.db")
    errors = need_module("studio.errors")
    real = db.connection
    calls = {"n": 0}

    @contextlib.contextmanager
    def flaky():
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise errors.database_unavailable()
        with real() as conn:
            yield conn

    monkeypatch.setattr(db, "connection", flaky)
    return calls


def _reset_to_processing(db_conn, doc_id):
    with db_conn.cursor() as cur:
        cur.execute("UPDATE studio_document_meta SET processed_at = NULL, error_code = NULL WHERE document_id = %s",
                    (doc_id,))


def test_IRETRY1_outcome_recorded_after_two_db_failures(client, db, monkeypatch):
    docs = need_module("studio.routes.documents")
    doc = upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    _reset_to_processing(db, doc["id"])
    assert client.get(f"{API}/documents/{doc['id']}").json()["status"] == "processing"

    monkeypatch.setattr(docs, "RECORD_RETRY_INTERVAL_S", 0.05)
    calls = _flaky_connection(monkeypatch, fail_times=2)
    docs.run_tracked(doc["id"], [])
    monkeypatch.undo()

    assert calls["n"] >= 3
    d = client.get(f"{API}/documents/{doc['id']}").json()
    assert d["status"] == "ready" and d["processed_at"] is not None and d["error"] is None, d


def test_IRETRY2_gives_up_after_bounded_attempts_without_raising(client, db, monkeypatch):
    docs = need_module("studio.routes.documents")
    doc = upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    _reset_to_processing(db, doc["id"])

    monkeypatch.setattr(docs, "RECORD_RETRY_INTERVAL_S", 0.01)
    calls = _flaky_connection(monkeypatch, fail_times=10_000)
    docs.run_tracked(doc["id"], [])  # must not raise
    monkeypatch.undo()

    assert calls["n"] == docs.RECORD_ATTEMPTS
    assert client.get(f"{API}/documents/{doc['id']}").json()["status"] == "processing"
