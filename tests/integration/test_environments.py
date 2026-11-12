"""Environment-specific behaviour, app in a child process (uvicorn studio.main:app).

I-S8-* (OpenAI missing/invalid/unreachable/slow), I-S9-* (database down, degraded
start, recovery), I-AUTH-* (Basic gate), I-WARN (non-loopback warning),
I-DEMO (demo mode overrides), I-SPA-* (frontend serving).
"""

from __future__ import annotations

import base64
import time
import urllib.parse

import httpx
import pytest

from tests.conftest import STUB_PORT, TEST_DATABASE_URL, _free_port
from tests.helpers import (
    API,
    HANDBOOK_TXT,
    TcpProxy,
    assert_error,
    db_url_via,
    run_app,
    upload_ready,
)

pytestmark = [pytest.mark.app, pytest.mark.db, pytest.mark.subprocess]
VACATION_Q = "How many paid vacation days do full-time employees accrue per calendar year?"


def h(app, timeout=30.0, **kw):
    return httpx.Client(base_url=app.base_url, timeout=timeout, **kw)


@pytest.fixture
def ready_doc(client):
    """One ready document in the shared test DB, created through the in-process app."""
    return upload_ready(client, "handbook.txt", HANDBOOK_TXT)


# ------------------------------------------------------------------- S8
def test_IS8_no_key_app_starts_and_blocks_upload_and_ask(stub_url, clean_db):
    with run_app({"OPENAI_API_KEY": ""}) as app, h(app) as c:
        health = c.get(f"{API}/health", params={"refresh": "true"}).json()
        assert health["status"] == "degraded"
        assert health["components"]["openai"]["status"] == "not_configured"
        assert health["components"]["database"]["status"] == "ok"
        # validation order: OpenAI configured comes first, even for a bad file
        for files in (
            {"file": ("a.txt", b"hello", "text/plain")},
            {"file": ("a.docx", b"", "application/octet-stream")},
        ):
            assert_error(c.post(f"{API}/documents", files=files), 503, "openai_not_configured")
        conv = c.post(f"{API}/conversations", json={}).json()
        assert_error(c.post(f"{API}/conversations/{conv['id']}/messages", json={"question": "q"}), 503,
                     "openai_not_configured")
        # every other endpoint works
        assert c.get(f"{API}/config").status_code == 200
        assert c.get(f"{API}/documents").json() == {"items": [], "total": 0}
        assert c.get(f"{API}/conversations").json()["total"] == 1
        assert c.patch(f"{API}/conversations/{conv['id']}", json={"title": "t"}).status_code == 200
        assert c.delete(f"{API}/conversations/{conv['id']}").status_code == 204
        assert c.get("/").status_code == 200
        log = app.log()
    assert "Traceback" not in log, log


def test_IS8_invalid_key_health_and_ask(stub_url, ready_doc):
    with run_app({"OPENAI_API_KEY": "sk-stub-invalid"}) as app, h(app) as c:
        r = c.get(f"{API}/health", params={"refresh": "true"})
        assert r.json()["components"]["openai"]["status"] == "invalid_key", r.text
        assert "sk-stub-invalid" not in r.text
        conv = c.post(f"{API}/conversations", json={}).json()
        assert_error(c.post(f"{API}/conversations/{conv['id']}/messages", json={"question": VACATION_Q}), 502,
                     "openai_auth_failed")
        assert c.get(f"{API}/conversations/{conv['id']}").json()["message_count"] == 0
        # a document processed with the invalid key fails with openai_auth
        up = c.post(f"{API}/documents", files={"file": ("x.txt", b"some words to embed", "text/plain")})
        assert up.status_code == 202, up.text
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            d = c.get(f"{API}/documents/{up.json()['id']}").json()
            if d["status"] != "processing":
                break
            time.sleep(0.3)
        assert d["status"] == "failed" and d["error"]["code"] == "openai_auth", d
        log = app.log()
    # The stub's own 401 text names the key and the frozen core prints exceptions; ignore those lines.
    leaked = [ln for ln in log.splitlines() if "sk-stub-invalid" in ln and "(stub:" not in ln]
    assert not leaked, leaked


def test_IS8_unreachable_openai(ready_doc):
    dead = f"http://127.0.0.1:{_free_port()}/v1"
    env = {"OPENAI_BASE_URL": dead, "STUDIO_OPENAI_TIMEOUT_S": "2", "STUDIO_OPENAI_MAX_RETRIES": "0"}
    with run_app(env) as app, h(app) as c:
        t0 = time.monotonic()
        r = c.get(f"{API}/health", params={"refresh": "true"})
        assert r.json()["components"]["openai"]["status"] == "unreachable", r.text
        conv = c.post(f"{API}/conversations", json={}).json()
        assert_error(c.post(f"{API}/conversations/{conv['id']}/messages", json={"question": VACATION_Q}), 502,
                     "openai_unreachable")
        assert time.monotonic() - t0 < 20


@pytest.mark.slow
def test_IS8_slow_openai_times_out_within_configured_timeout(stub_url, ready_doc):
    env = {"STUDIO_OPENAI_TIMEOUT_S": "1", "STUDIO_OPENAI_MAX_RETRIES": "0"}
    with run_app(env) as app, h(app) as c:
        conv = c.post(f"{API}/conversations", json={}).json()
        t0 = time.monotonic()
        r = c.post(f"{API}/conversations/{conv['id']}/messages", json={"question": "vacation __STUB_SLOW__"})
        elapsed = time.monotonic() - t0
        assert_error(r, 502, "openai_unreachable")
        assert elapsed < 2.9, f"request waited {elapsed:.1f}s, timeout is 1s"


# ------------------------------------------------------------------- S9
def _db_port() -> tuple[str, int]:
    p = urllib.parse.urlsplit(TEST_DATABASE_URL)
    return p.hostname, p.port or 5432


def test_IS9_database_down_degraded_start_and_recovery(stub_url, clean_db):
    host, port = _db_port()
    proxy = TcpProxy(host, port)
    url = db_url_via(proxy.port, TEST_DATABASE_URL)
    with run_app({"DATABASE_URL": url, "STUDIO_DB_STARTUP_RETRIES": "1"}) as app, h(app) as c:
        # degraded start: no database at all
        assert c.get(f"{API}/health/live").json() == {"status": "ok"}
        health = c.get(f"{API}/health").json()
        assert health["components"]["database"]["status"] == "unavailable" and health["status"] == "degraded"
        assert_error(c.get(f"{API}/documents"), 503, "database_unavailable")
        assert_error(c.get(f"{API}/conversations"), 503, "database_unavailable")
        assert_error(c.post(f"{API}/conversations", json={}), 503, "database_unavailable")
        assert c.get(f"{API}/config").status_code == 200

        # database comes back: health re-initialises the schema, API works
        proxy.start()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if c.get(f"{API}/health").json()["components"]["database"]["status"] == "ok":
                break
            time.sleep(0.5)
        assert c.get(f"{API}/health").json()["components"]["database"]["status"] == "ok"
        assert c.get(f"{API}/documents").status_code == 200
        conv = c.post(f"{API}/conversations", json={"title": "after recovery"})
        assert conv.status_code == 201, conv.text

        # database disappears while running
        proxy.stop()
        assert_error(c.get(f"{API}/conversations"), 503, "database_unavailable")
        assert c.get(f"{API}/health/live").status_code == 200
        assert c.get(f"{API}/health").json()["components"]["database"]["status"] == "unavailable"

        # and comes back again
        proxy = TcpProxy(host, port, listen_port=proxy.port).start()
        deadline = time.monotonic() + 20
        ok = False
        while time.monotonic() < deadline and not ok:
            ok = c.get(f"{API}/conversations").status_code == 200
            time.sleep(0.5)
        assert ok, "API did not recover after the database returned"
        assert c.get(f"{API}/conversations").json()["total"] == 1
        log = app.log()
    proxy.stop()
    assert app.proc.returncode is not None  # stopped by us, did not crash earlier


# ------------------------------------------------------------------- auth (AC25)
AUTH_USER, AUTH_PASS = "tester", "test-only-pw"


@pytest.fixture(scope="module")
def auth_app(stub_url, test_db):
    with run_app({"STUDIO_AUTH_USER": AUTH_USER, "STUDIO_AUTH_PASSWORD": AUTH_PASS}) as app:
        yield app


GATED = [
    ("GET", f"{API}/health"), ("GET", f"{API}/config"), ("GET", f"{API}/documents"),
    ("POST", f"{API}/documents"), ("GET", f"{API}/documents/1"), ("DELETE", f"{API}/documents/1"),
    ("GET", f"{API}/conversations"), ("POST", f"{API}/conversations"),
    ("GET", "/documents"), ("POST", "/upload"), ("POST", "/ask"),
    ("GET", "/"), ("GET", "/library"), ("GET", "/assets/app.js"), ("GET", "/docs"), ("GET", "/openapi.json"),
]


@pytest.mark.parametrize("method,path", GATED)
def test_IAUTH1_every_route_needs_credentials(auth_app, method, path):
    with h(auth_app) as c:
        r = c.request(method, path, headers={"Accept": "text/html"} if path in ("/", "/library") else {})
        assert r.status_code == 401, (path, r.status_code)
        assert r.headers.get("www-authenticate", "").lower().startswith("basic"), r.headers
        if path.startswith(API):
            assert_error(r, 401, "unauthorized")


def test_IAUTH2_live_is_open(auth_app):
    with h(auth_app) as c:
        assert c.get(f"{API}/health/live").status_code == 200


def test_IAUTH3_correct_credentials_work_wrong_do_not(auth_app):
    with h(auth_app, auth=(AUTH_USER, AUTH_PASS)) as c:
        assert c.get(f"{API}/health").json()["auth_enabled"] is True
        assert c.get(f"{API}/documents").status_code == 200
        assert c.get("/documents").status_code == 200
        assert c.get("/", headers={"Accept": "text/html"}).status_code == 200
    for creds in ((AUTH_USER, "wrong"), ("wrong", AUTH_PASS), ("", "")):
        with h(auth_app, auth=creds) as c:
            assert c.get(f"{API}/documents").status_code == 401
    with h(auth_app) as c:
        bad = base64.b64encode(b"no-colon").decode()
        assert c.get(f"{API}/documents", headers={"Authorization": f"Basic {bad}"}).status_code == 401
        assert c.get(f"{API}/documents", headers={"Authorization": "Bearer x"}).status_code == 401


def test_IAUTH4_password_not_logged(auth_app):
    assert AUTH_PASS not in auth_app.log()


def test_IAUTH5_only_one_variable_set_means_no_gate(stub_url, test_db):
    with run_app({"STUDIO_AUTH_USER": AUTH_USER, "STUDIO_AUTH_PASSWORD": ""}) as app, h(app) as c:
        assert c.get(f"{API}/documents").status_code == 200
        assert c.get(f"{API}/health").json()["auth_enabled"] is False


def test_IWARN_non_loopback_without_auth_logs_warning(stub_url, test_db):
    with run_app({"STUDIO_BIND_ADDR": "0.0.0.0"}) as app:
        time.sleep(0.5)
        log = app.log().lower()
    assert "warn" in log and "auth" in log, log[-2000:]
    with run_app({"STUDIO_BIND_ADDR": "0.0.0.0", "STUDIO_AUTH_USER": "u", "STUDIO_AUTH_PASSWORD": "p"}) as app2:
        time.sleep(0.5)
        log2 = app2.log().lower()
    with run_app({}) as app3:
        time.sleep(0.5)
        log3 = app3.log().lower()
    for other in (log2, log3):
        assert not ("warn" in other and "0.0.0.0" in other and "auth" in other), other[-2000:]


# ------------------------------------------------------------------- demo mode (S13)
def test_IDEMO_demo_mode_overrides_key_and_base_url(stub_url, clean_db):
    dead = f"http://127.0.0.1:{_free_port()}/v1"
    env = {
        "STUDIO_DEMO_MODE": "true",
        "STUDIO_STUB_URL": stub_url,
        "OPENAI_BASE_URL": dead,  # must be replaced by STUDIO_STUB_URL
        "OPENAI_API_KEY": "sk-stub-invalid",  # must be replaced by sk-demo-stub (stub would 401 otherwise)
    }
    with run_app(env) as app, h(app) as c:
        health = c.get(f"{API}/health", params={"refresh": "true"}).json()
        assert health["mode"] == "demo" and health["components"]["openai"]["status"] == "ok", health
        assert c.get(f"{API}/config").json()["mode"] == "demo"
        up = c.post(f"{API}/documents", files={"file": ("h.txt", HANDBOOK_TXT.encode(), "text/plain")})
        assert up.status_code == 202
        deadline = time.monotonic() + 30
        while c.get(f"{API}/documents/{up.json()['id']}").json()["status"] == "processing":
            assert time.monotonic() < deadline
            time.sleep(0.3)
        conv = c.post(f"{API}/conversations", json={}).json()
        r = c.post(f"{API}/conversations/{conv['id']}/messages", json={"question": VACATION_Q})
        assert r.status_code == 201, r.text
        assert r.json()["assistant_message"]["content"].startswith("[Simulated answer]")


def test_IDEMO_demo_mode_without_any_key(stub_url, clean_db):
    with run_app({"STUDIO_DEMO_MODE": "true", "STUDIO_STUB_URL": stub_url}, unset=("OPENAI_API_KEY",)) as app:
        with h(app) as c:
            health = c.get(f"{API}/health", params={"refresh": "true"}).json()
            assert health["components"]["openai"]["status"] == "ok", health


# ------------------------------------------------------------------- SPA serving
SPA_PATHS = ["/", "/library", "/status", "/c/5b0a3c1e-7c59-4d0e-9a55-0c9d5f3a2b11", "/some/unknown/page"]


@pytest.mark.parametrize("path", SPA_PATHS)
def test_ISPA1_fallback_serves_index(client, path):
    r = client.get(path, headers={"Accept": "text/html,application/xhtml+xml"})
    assert r.status_code == 200 and "SPA-FIXTURE-INDEX" in r.text, (path, r.status_code)


def test_ISPA2_assets_served(client):
    r = client.get("/assets/app.js")
    assert r.status_code == 200 and "SPA-FIXTURE-ASSET" in r.text


@pytest.mark.parametrize("path", ["/api/v1/nope", "/assets/missing.js", "/api"])
def test_ISPA3_reserved_paths_not_swallowed(client, path):
    r = client.get(path, headers={"Accept": "text/html"})
    assert "SPA-FIXTURE-INDEX" not in r.text, path
    assert r.status_code == 404, (path, r.status_code)


def test_ISPA4_core_and_docs_paths_keep_their_responses(client):
    r = client.get("/documents", headers={"Accept": "text/html"})
    assert r.status_code == 200 and r.json() == []
    assert "SPA-FIXTURE-INDEX" not in client.get("/docs", headers={"Accept": "text/html"}).text
    assert client.get("/openapi.json").json()["openapi"]


def test_ISPA5_no_fallback_without_html_accept_or_for_post(client):
    assert "SPA-FIXTURE-INDEX" not in client.get("/library", headers={"Accept": "application/json"}).text
    assert "SPA-FIXTURE-INDEX" not in client.post("/library").text


def test_ISPA6_missing_dist_api_still_runs(stub_url, test_db):
    with run_app({"STUDIO_WEB_DIST": "/nonexistent/web/dist"}) as app, h(app) as c:
        r = c.get("/", headers={"Accept": "text/html"})
        assert r.status_code == 200 and r.text.strip(), r.status_code  # DESIGN 5.3: plain notice
        assert c.get(f"{API}/config").status_code == 200


def test_stub_port_matches_env():
    assert str(STUB_PORT) in __import__("os").environ["OPENAI_BASE_URL"]
