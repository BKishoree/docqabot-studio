"""Helpers shared by the test suites (no fixtures here; see conftest.py)."""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request

from tests.conftest import ROOT, TEST_ENV, _free_port

API = "/api/v1"
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
NOT_FOUND_ANSWER = "I couldn't find relevant information in the uploaded documents to answer your question."

# ------------------------------------------------------------------ test files
HANDBOOK_TXT = (
    "Vacation policy\n\n"
    "Full-time employees accrue twenty days of paid vacation per calendar year. "
    "Unused vacation days carry over until the end of March.\n\n"
    "Remote work\n\n"
    "Staff may work remotely on Tuesdays and Thursdays after approval by their manager."
)
GARDEN_MD = (
    "# Tomato growing guide\n\n"
    "Tomatoes need full sunlight and deep watering twice weekly. "
    "Prune suckers to improve airflow around the stems.\n"
)
PDF_TEXT = "Invoice processing manual. Approved invoices are paid within thirty business days by accounts payable."
UNRELATED_QUESTION = "zebra quantum saxophone"


def make_pdf(pages: list[str]) -> bytes:
    """A small valid PDF with Helvetica text, one entry per page ('' = page without text)."""
    n = len(pages)
    page_ids = [4 + 2 * i for i in range(n)]
    objs: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        ("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join(f"{p} 0 R" for p in page_ids), n)).encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, text in enumerate(pages):
        ops = ["BT /F1 11 Tf 14 TL 50 740 Td"]
        for para in text.split("\n"):
            for line in textwrap.wrap(para, 80) or [""]:
                esc = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                ops.append(f"({esc}) Tj T*")
        ops.append("ET")
        stream = ("\n".join(ops) if text else "").encode("latin-1")
        objs.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_ids[i] + 1} 0 R >>"
            ).encode()
        )
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


CORRUPT_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 9 0 R >>\nthis is not a pdf at all\n"


# ------------------------------------------------------------------ API helpers
def upload(client, filename: str, data: bytes | str, content_type: str = "application/octet-stream"):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return client.post(f"{API}/documents", files={"file": (filename, data, content_type)})


def wait_for_document(client, doc_id: int, statuses=("ready", "failed"), timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        r = client.get(f"{API}/documents/{doc_id}")
        if r.status_code == 200:
            last = r.json()
            if last["status"] in statuses:
                return last
        time.sleep(0.2)
    raise AssertionError(f"document {doc_id} did not reach {statuses} in {timeout}s; last={last}")


def upload_ready(client, filename: str, data, content_type="text/plain") -> dict:
    r = upload(client, filename, data, content_type)
    assert r.status_code == 202, r.text
    doc = wait_for_document(client, r.json()["id"])
    assert doc["status"] == "ready", doc
    return doc


def new_conversation(client, title: str | None = None) -> dict:
    r = client.post(f"{API}/conversations", json={} if title is None else {"title": title})
    assert r.status_code == 201, r.text
    return r.json()


def ask(client, conv_id: str, question: str):
    return client.post(f"{API}/conversations/{conv_id}/messages", json={"question": question})


def assert_error(resp, status: int, code: str) -> dict:
    assert resp.status_code == status, f"expected {status} {code}, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert set(body) == {"error"}, body
    err = body["error"]
    assert set(err) >= {"code", "message", "details", "request_id"}, err
    assert err["code"] == code, err
    assert isinstance(err["message"], str) and err["message"].strip(), err
    assert err["details"] is None or isinstance(err["details"], dict), err
    assert err["request_id"] == resp.headers.get("x-request-id"), (err, dict(resp.headers))
    return err


# ------------------------------------------------------------- subprocess app
def _http_ok(url: str, headers: dict | None = None) -> bool:
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status == 200
    except (OSError, urllib.error.HTTPError):
        return False


class AppProcess:
    def __init__(self, base_url: str, proc: subprocess.Popen, log_path: str):
        self.base_url = base_url
        self.proc = proc
        self.log_path = log_path

    def log(self) -> str:
        with open(self.log_path, encoding="utf-8", errors="replace") as fh:
            return fh.read()


@contextlib.contextmanager
def run_app(env_overrides: dict | None = None, unset: tuple[str, ...] = (), wait: bool = True, timeout: float = 40.0):
    """Run uvicorn studio.main:app in a child process with the test environment plus overrides."""
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("STUDIO_", "OPENAI_"))}
    env.update(TEST_ENV)
    env.update(env_overrides or {})
    for k in unset:
        env.pop(k, None)
    env["PYTHONUNBUFFERED"] = "1"
    fd, log_path = tempfile.mkstemp(prefix="docqabot-test-app-", suffix=".log")
    log = os.fdopen(fd, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "studio.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    app = AppProcess(base, proc, log_path)
    try:
        if wait:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise AssertionError(f"app exited with {proc.returncode}:\n{app.log()}")
                if _http_ok(base + "/api/v1/health/live"):
                    break
                time.sleep(0.25)
            else:
                raise AssertionError(f"app not live after {timeout}s:\n{app.log()}")
        yield app
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        try:
            os.unlink(log_path)
        except OSError:
            pass


# ------------------------------------------------------------------ TCP proxy
class TcpProxy:
    """Loopback TCP forwarder used to make the database 'disappear' and 'come back' (S9)."""

    def __init__(self, target_host: str, target_port: int, listen_port: int | None = None):
        self.target = (target_host, target_port)
        self.port = listen_port or _free_port()
        self._server = None
        self._thread = None
        self._conns: list = []
        self._lock = __import__("threading").Lock()

    def start(self) -> "TcpProxy":
        import socket
        import threading

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", self.port))
        srv.listen(50)
        self._server = srv

        def pump(src, dst):
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                for s in (src, dst):
                    try:
                        s.close()
                    except OSError:
                        pass

        def accept_loop():
            while True:
                try:
                    client, _ = srv.accept()
                except OSError:
                    return
                try:
                    upstream = socket.create_connection(self.target, timeout=5)
                    upstream.settimeout(None)
                except OSError:
                    client.close()
                    continue
                with self._lock:
                    self._conns += [client, upstream]
                threading.Thread(target=pump, args=(client, upstream), daemon=True).start()
                threading.Thread(target=pump, args=(upstream, client), daemon=True).start()

        self._thread = threading.Thread(target=accept_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        # shutdown() before close(): on Linux, close() alone does not wake a thread blocked in
        # accept()/recv(), so the listener kept accepting and relaying (CI failure, 2026-11-12).
        import socket

        if self._server is not None:
            try:
                self._server.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._server.close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        with self._lock:
            for s in self._conns:
                for fn in (lambda: s.shutdown(socket.SHUT_RDWR), s.close):
                    try:
                        fn()
                    except OSError:
                        pass
            self._conns = []
        # Harness rule (RCA BUG-005): "stopped" must be checkable, so verify that nothing accepts any more.
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(1.0)
        try:
            probe.connect(("127.0.0.1", self.port))
        except OSError:
            pass  # refused (Linux) or timed out (Windows retries refused SYNs): stopped
        else:
            raise AssertionError(f"TcpProxy on port {self.port} still accepts connections after stop()")
        finally:
            probe.close()


def db_url_via(port: int, base_url: str) -> str:
    import urllib.parse as up

    parts = up.urlsplit(base_url)
    netloc = parts.netloc.rsplit("@", 1)
    host = f"127.0.0.1:{port}"
    netloc = f"{netloc[0]}@{host}" if len(netloc) == 2 else host
    return up.urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
