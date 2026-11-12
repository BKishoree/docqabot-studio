"""SM-1: tests/smoke/smoke.py passes against a running instance and fails cleanly when it should."""

from __future__ import annotations

import subprocess
import sys

import pytest

from tests.conftest import ROOT, _free_port
from tests.helpers import run_app

pytestmark = [pytest.mark.app, pytest.mark.db, pytest.mark.subprocess]
SMOKE = str(ROOT / "tests" / "smoke" / "smoke.py")


def run_smoke(*args):
    return subprocess.run([sys.executable, SMOKE, *args], capture_output=True, text=True, timeout=300)


def test_SM1_smoke_passes_and_cleans_up(stub_url, clean_db, db):
    with run_app() as app:
        r = run_smoke("--base-url", app.base_url)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SMOKE PASSED" in r.stdout
    with db.cursor() as cur:
        cur.execute("SELECT (SELECT count(*) FROM documents) AS d, (SELECT count(*) FROM studio_conversations) AS c")
        assert cur.fetchone() == {"d": 0, "c": 0}


def test_SM1_smoke_with_basic_auth(stub_url, clean_db):
    with run_app({"STUDIO_AUTH_USER": "u", "STUDIO_AUTH_PASSWORD": "p"}) as app:
        assert run_smoke("--base-url", app.base_url, "--user", "u", "--password", "p").returncode == 0
        bad = run_smoke("--base-url", app.base_url)
    assert bad.returncode == 1 and "FAIL health" in bad.stdout


def test_SM1_smoke_fails_when_nothing_listens():
    r = run_smoke("--base-url", f"http://127.0.0.1:{_free_port()}", "--timeout", "3")
    assert r.returncode == 1 and "FAIL live" in r.stdout
