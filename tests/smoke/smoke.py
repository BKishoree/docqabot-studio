#!/usr/bin/env python3
"""SM-1 smoke test (DESIGN section 7). Standard library only, public API only.

    python tests/smoke/smoke.py --base-url http://127.0.0.1:8000 [--user U --password P]

Flow: live -> health -> config -> upload small .txt -> poll ready -> create conversation
-> ask -> citation present -> delete conversation and document. Exit code 0 = pass, 1 = fail.
Works against the laptop, the demo stack, or a server. In live mode it spends a few
OpenAI tokens (one embedding batch, one embedding, one chat call).
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

TEXT = (
    "DocQABot smoke test document.\n\n"
    "The smoke test marker word is periwinkle. Periwinkle shipments leave the warehouse every Friday.\n"
)
QUESTION = "When do periwinkle shipments leave the warehouse?"


class Smoke:
    def __init__(self, base: str, user: str | None, password: str | None, timeout: float):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.headers = {}
        if user is not None and password is not None:
            token = base64.b64encode(f"{user}:{password}".encode()).decode()
            self.headers["Authorization"] = f"Basic {token}"

    def call(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        req = urllib.request.Request(self.base + path, data=body, method=method, headers={**self.headers, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw.decode(errors="replace")

    def json(self, method: str, path: str, payload: dict):
        return self.call(method, path, json.dumps(payload).encode(), {"Content-Type": "application/json"})

    def upload(self, name: str, data: bytes):
        boundary = uuid.uuid4().hex
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
            f"Content-Type: text/plain\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        return self.call("POST", "/api/v1/documents", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--user")
    ap.add_argument("--password")
    ap.add_argument("--timeout", type=float, default=90.0, help="per-request timeout, seconds")
    ap.add_argument("--ready-timeout", type=float, default=120.0, help="seconds to wait for the document")
    args = ap.parse_args(argv)
    s = Smoke(args.base_url, args.user, args.password, args.timeout)
    doc_id = conv_id = None
    step = "start"

    def ok(msg):
        print(f"PASS {step}: {msg}")

    try:
        step = "live"
        st, body = s.call("GET", "/api/v1/health/live")
        assert st == 200 and body == {"status": "ok"}, (st, body)
        ok("live")

        step = "health"
        st, h = s.call("GET", "/api/v1/health?refresh=true")
        assert st == 200, (st, h)
        assert h["components"]["database"]["status"] == "ok", h
        assert h["components"]["openai"]["status"] == "ok", h
        ok(f"mode={h['mode']} version={h['version']} status={h['status']}")

        step = "config"
        st, cfg = s.call("GET", "/api/v1/config")
        assert st == 200 and ".txt" in cfg["allowed_extensions"], (st, cfg)
        ok("config")

        step = "upload"
        name = f"smoke-{uuid.uuid4().hex[:8]}.txt"
        st, doc = s.upload(name, TEXT.encode())
        assert st == 202 and doc["status"] == "processing", (st, doc)
        doc_id = doc["id"]
        ok(f"document {doc_id} {name}")

        step = "ready"
        deadline = time.monotonic() + args.ready_timeout
        while True:
            st, doc = s.call("GET", f"/api/v1/documents/{doc_id}")
            assert st == 200, (st, doc)
            if doc["status"] != "processing":
                break
            assert time.monotonic() < deadline, "document still processing"
            time.sleep(1)
        assert doc["status"] == "ready" and doc["chunk_count"] >= 1, doc
        ok(f"ready, {doc['chunk_count']} chunk(s)")

        step = "conversation"
        st, conv = s.json("POST", "/api/v1/conversations", {"title": "Smoke test"})
        assert st == 201, (st, conv)
        conv_id = conv["id"]
        ok(conv_id)

        step = "ask"
        st, res = s.json("POST", f"/api/v1/conversations/{conv_id}/messages", {"question": QUESTION})
        assert st == 201, (st, res)
        a = res["assistant_message"]
        assert a["grounded"] is True and a["citations"], a
        cit = next((c for c in a["citations"] if c["document_id"] == doc_id), None)
        assert cit is not None, a["citations"]
        assert "periwinkle" in cit["text"].lower(), cit
        ok(f"answer with {len(a['citations'])} citation(s): {a['content'][:80]!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {step}: {exc!r}")
        rc = 1
    else:
        rc = 0
    finally:
        if conv_id:
            st, _ = s.call("DELETE", f"/api/v1/conversations/{conv_id}")
            print(f"{'PASS' if st == 204 else 'FAIL'} cleanup conversation: {st}")
            rc = rc or (0 if st == 204 else 1)
        if doc_id:
            st, _ = s.call("DELETE", f"/api/v1/documents/{doc_id}")
            print(f"{'PASS' if st == 204 else 'FAIL'} cleanup document: {st}")
            rc = rc or (0 if st == 204 else 1)
    print("SMOKE PASSED" if rc == 0 else "SMOKE FAILED")
    return rc


if __name__ == "__main__":
    sys.exit(main())
