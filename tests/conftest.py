"""Shared pytest setup for DocQABot Studio (TESTER, task T2).

Order matters: the environment below is set at import time of this file, i.e.
before any test module (and therefore before ``studio`` or ``app``) is imported.

Guarantees:
- No real OpenAI key is ever used: OPENAI_API_KEY is the fixed stub key and
  OPENAI_BASE_URL points at the in-process stub on a free loopback port.
- Every STUDIO_* variable is set explicitly, so a developer ``.env`` cannot change
  the mode (``load_dotenv`` never overrides existing variables).
- Loopback guard: the session aborts if OPENAI_BASE_URL or the test database is
  not on a loopback address, and any Python socket connect to a non-loopback
  address raises inside the pytest process.
- The test database name must contain "test" because tables are truncated.
"""

from __future__ import annotations

import importlib
import ipaddress
import os
import pathlib
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
FIXTURES = TESTS / "fixtures"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


STUB_PORT = int(os.environ.get("TEST_STUB_PORT") or _free_port())
STUB_URL = f"http://127.0.0.1:{STUB_PORT}/v1"
DEFAULT_TEST_DB = (
    "postgresql://docqabot:docqabot_test@127.0.0.1:5434/docqabot_test"
    "?options=-c%20ivfflat.probes%3D100"
)
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or DEFAULT_TEST_DB
MAX_UPLOAD_MB = 2
REQUIRE_APP = os.environ.get("STUDIO_TESTS_REQUIRE_APP") == "1"

TEST_ENV = {
    "OPENAI_API_KEY": "sk-stub-test",
    "OPENAI_BASE_URL": STUB_URL,
    "DATABASE_URL": TEST_DATABASE_URL,
    "STUDIO_DEMO_MODE": "false",
    "STUDIO_STUB_URL": STUB_URL,
    "STUDIO_BIND_ADDR": "127.0.0.1",
    "STUDIO_PORT": "8000",
    "STUDIO_AUTH_USER": "",
    "STUDIO_AUTH_PASSWORD": "",
    "STUDIO_MAX_UPLOAD_MB": str(MAX_UPLOAD_MB),
    "STUDIO_OPENAI_TIMEOUT_S": "10",
    "STUDIO_OPENAI_MAX_RETRIES": "1",
    "STUDIO_DB_STARTUP_RETRIES": "1",
    "STUDIO_WEB_DIST": str(FIXTURES / "web_dist"),
    "STUDIO_LOG_LEVEL": "INFO",
}
os.environ.update(TEST_ENV)


# --------------------------------------------------------------------------- guard
LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1", "[::1]"}


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    host = host.strip("[]")
    if host.lower() in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _url_host(url: str) -> str | None:
    return urllib.parse.urlsplit(url).hostname


def _guard_problems() -> list[str]:
    problems = []
    if not is_loopback_host(_url_host(os.environ.get("OPENAI_BASE_URL", ""))):
        problems.append(f"OPENAI_BASE_URL is not loopback: {os.environ.get('OPENAI_BASE_URL')!r}")
    if not os.environ.get("OPENAI_API_KEY", "").startswith("sk-stub"):
        problems.append("OPENAI_API_KEY is not a stub key")
    if not is_loopback_host(_url_host(TEST_DATABASE_URL)):
        problems.append("test database is not on a loopback address")
    dbname = urllib.parse.urlsplit(TEST_DATABASE_URL).path.lstrip("/")
    if "test" not in dbname:
        problems.append(f"test database name {dbname!r} does not contain 'test' (tables are truncated)")
    return problems


_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex


def _check_address(sock: socket.socket, address) -> None:
    if sock.family in (socket.AF_INET, socket.AF_INET6) and isinstance(address, tuple):
        host = address[0]
        if not is_loopback_host(str(host)):
            raise OSError(f"loopback guard: connection to non-loopback address {host!r} blocked in tests")


def _guarded_connect(self, address):
    _check_address(self, address)
    return _original_connect(self, address)


def _guarded_connect_ex(self, address):
    _check_address(self, address)
    return _original_connect_ex(self, address)


def pytest_configure(config):
    problems = _guard_problems()
    if problems:
        pytest.exit("Loopback guard failed: " + "; ".join(problems), returncode=3)
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex


def pytest_unconfigure(config):
    socket.socket.connect = _original_connect
    socket.socket.connect_ex = _original_connect_ex


# --------------------------------------------------------------------- availability
def need_module(name: str):
    """Import a Studio module, or skip while the backend has not delivered it.

    With STUDIO_TESTS_REQUIRE_APP=1 (CI, sign-off runs) a missing module fails instead.
    """
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if not REQUIRE_APP and (name == missing or name.startswith(missing + ".")):
            pytest.skip(f"{name} not delivered yet ({exc})")
        raise


# ------------------------------------------------------------------------- stub
class _ThreadedServer:
    def __init__(self, app, port: int):
        import uvicorn

        self.config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self, health_url: str, timeout: float = 15.0) -> None:
        self.thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(health_url, timeout=1) as r:
                    if r.status == 200:
                        return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError(f"stub did not become healthy at {health_url}")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


@pytest.fixture(scope="session")
def stub_url():
    """The OpenAI stub, in-process on STUB_PORT. Returns the base URL ending in /v1."""
    stub = need_module("studio.stub")
    server = _ThreadedServer(stub.app, STUB_PORT)
    server.start(f"http://127.0.0.1:{STUB_PORT}/health")
    yield STUB_URL
    server.stop()


# --------------------------------------------------------------------- database
CLEAN_TABLES = [
    "studio_citations",
    "studio_messages",
    "studio_conversations",
    "studio_document_meta",
    "chunks",
    "documents",
]


def db_connect():
    import psycopg2
    from psycopg2.extras import RealDictCursor

    return psycopg2.connect(TEST_DATABASE_URL, cursor_factory=RealDictCursor, connect_timeout=5)


@pytest.fixture(scope="session")
def test_db():
    try:
        conn = db_connect()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"test database not reachable at {_url_host(TEST_DATABASE_URL)}: {exc}")
    conn.close()
    return TEST_DATABASE_URL


def truncate_all() -> None:
    conn = db_connect()
    try:
        with conn.cursor() as cur:
            existing = []
            for t in CLEAN_TABLES:
                cur.execute("SELECT to_regclass(%s) AS r", (t,))
                if cur.fetchone()["r"] is not None:
                    existing.append(t)
            if existing:
                cur.execute(f"TRUNCATE {', '.join(existing)} RESTART IDENTITY CASCADE")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def clean_db(test_db):
    truncate_all()
    yield test_db


@pytest.fixture
def db(clean_db):
    """A RealDictCursor connection to the (cleaned) test database, autocommit."""
    conn = db_connect()
    conn.autocommit = True
    yield conn
    conn.close()


# ------------------------------------------------------------------------- app
@pytest.fixture(scope="session")
def studio_app(stub_url, test_db):
    main = need_module("studio.main")
    return main.app


@pytest.fixture
def client(studio_app, clean_db):
    """TestClient on studio.main:app with lifespan, clean database, stub running."""
    from fastapi.testclient import TestClient

    with TestClient(studio_app, raise_server_exceptions=False) as c:
        yield c
