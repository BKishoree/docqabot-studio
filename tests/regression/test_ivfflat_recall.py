"""T-R3: retrieval still finds a known chunk after 300+ chunks are stored (IVFFlat probes, K2)."""

from __future__ import annotations

import pytest

from tests.helpers import API, ask, new_conversation, upload_ready

pytestmark = [pytest.mark.app, pytest.mark.db]

NEEDLE = "The xylophone calibration constant for the orbital greenhouse is forty-two."


def test_TR3_probes_setting_on_core_connections(client):
    from tests.conftest import need_module

    need_module("studio.core_adapter")  # make sure bootstrap ran before app.* in this process
    from app.database import get_connection

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW ivfflat.probes")
            row = cur.fetchone()
    finally:
        conn.close()
    assert str(list(row.values())[0]) == "100", row


def test_TR3_needle_found_among_300_plus_chunks(client, db):
    # 320 filler documents' chunks with random unit-ish vectors, inserted directly (fast)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO documents (filename, status) SELECT 'filler-' || g || '.txt', 'ready' "
            "FROM generate_series(1, 320) g"
        )
        cur.execute(
            """
            INSERT INTO chunks (document_id, content, embedding, chunk_index)
            SELECT d.id, 'filler chunk ' || d.id,
                   (SELECT array_agg(random() - 0.5) FROM generate_series(1, 1536) WHERE d.id > 0)::vector,
                   0
            FROM documents d WHERE d.filename LIKE 'filler-%%'
            """
        )
        cur.execute("ANALYZE chunks")
        cur.execute("SELECT count(*) AS n FROM chunks")
        assert cur.fetchone()["n"] >= 320
    doc = upload_ready(client, "needle.txt", NEEDLE)
    c = new_conversation(client)
    r = ask(client, c["id"], "What is the xylophone calibration constant for the orbital greenhouse?")
    assert r.status_code == 201, r.text
    cits = r.json()["assistant_message"]["citations"]
    assert cits and cits[0]["document_id"] == doc["id"], cits
    assert cits[0]["text"] == NEEDLE
    # same through the core route
    core = client.post("/ask", json={"question": "xylophone calibration constant orbital greenhouse"}).json()
    assert core["sources"] == ["needle.txt"]
    assert client.get(f"{API}/documents").json()["total"] == 321
