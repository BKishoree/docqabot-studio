"""T-RB-*: one regression test per product bug fixed during the build (see vault 07 Failures and Fixes/Bugs.md)."""

from __future__ import annotations

import time

import httpx
import pytest

from tests.conftest import MAX_UPLOAD_MB
from tests.helpers import API, HANDBOOK_TXT, assert_error, run_app, upload_ready

pytestmark = [pytest.mark.app, pytest.mark.db]


def test_TRB_001_core_upload_over_limit_is_413_and_stores_nothing(client):
    """BUG-001: the global request-size limit did not apply to core POST /upload."""
    limit = MAX_UPLOAD_MB * 1024 * 1024
    r = client.post("/upload", files={"file": ("big.txt", b"a" * (limit + 4096), "text/plain")})
    assert r.status_code == 413
    assert client.get("/documents").json() == []
    # just under the limit (file + small multipart framing) is still accepted by the core route
    ok = client.post("/upload", files={"file": ("ok.txt", b"word " * ((limit - 4096) // 5), "text/plain")})
    assert ok.status_code == 200, ok.status_code


@pytest.mark.subprocess
@pytest.mark.slow
def test_TRB_003_first_ask_respects_timeout(stub_url, client):
    """BUG-003: the first OpenAI call in a fresh process took ~3 s extra (lazy SDK import), beating the timeout."""
    upload_ready(client, "handbook.txt", HANDBOOK_TXT)
    with run_app({"STUDIO_OPENAI_TIMEOUT_S": "1", "STUDIO_OPENAI_MAX_RETRIES": "0"}) as app:
        with httpx.Client(base_url=app.base_url, timeout=30) as c:
            conv = c.post(f"{API}/conversations", json={}).json()
            t0 = time.monotonic()
            r = c.post(f"{API}/conversations/{conv['id']}/messages", json={"question": "vacation __STUB_SLOW__"})
            elapsed = time.monotonic() - t0
    assert_error(r, 502, "openai_unreachable")
    assert elapsed < 2.5, f"first ask took {elapsed:.2f}s with a 1 s timeout"


@pytest.mark.subprocess
def test_TRB_004_failed_document_never_shown_without_reason(stub_url, clean_db):
    """BUG-004: with an invalid key the core committed 'failed' before Studio stored the error code,
    so clients could see failed/processing_failed (or no error) instead of openai_auth."""
    with run_app({"OPENAI_API_KEY": "sk-stub-invalid"}) as app, httpx.Client(base_url=app.base_url, timeout=30) as c:
        up = c.post(f"{API}/documents", files={"file": ("x.txt", b"words to embed here", "text/plain")})
        assert up.status_code == 202
        seen = []
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            d = c.get(f"{API}/documents/{up.json()['id']}").json()
            seen.append((d["status"], (d["error"] or {}).get("code")))
            if d["status"] != "processing":
                break
            time.sleep(0.01)  # poll fast to catch the window between the two commits
    observed = {s for s in seen if s[0] != "processing"}
    assert observed == {("failed", "openai_auth")}, seen[-5:]
