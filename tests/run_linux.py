#!/usr/bin/env python3
"""Run the Python suites on Linux in a container (huddle 2026-11-12, RCA BUG-005, Backlog T1).

    python tests/run_linux.py                       # unit + contract + integration
    python tests/run_linux.py tests/integration -k IS9

Copies only the Python sources into a fresh `python:3.13-slim` container (no bind mount of
the repo, no node_modules) that joins the network namespace of the test DB container, so the
database is on 127.0.0.1 inside the container and the loopback guard in conftest still holds.
Regression tests are left out by default because they need git history.
Exit code is pytest's. Needs Docker and the running container `docqabot-test-db`
(override with TEST_DB_CONTAINER). The container is named `docqabot-test-linux-<pid>`.
"""

from __future__ import annotations

import io
import os
import pathlib
import subprocess
import sys
import tarfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
INCLUDE = ["app", "studio", "tests", "requirements.txt", "requirements-studio.txt", "requirements-dev.txt", "pytest.ini"]
IMAGE = os.environ.get("LINUX_TEST_IMAGE", "python:3.13-slim")
DB_CONTAINER = os.environ.get("TEST_DB_CONTAINER", "docqabot-test-db")
DB_URL = os.environ.get(
    "LINUX_TEST_DATABASE_URL",
    "postgresql://docqabot:docqabot_test@127.0.0.1:5432/docqabot_test?options=-c%20ivfflat.probes%3D100",
)


def source_tar() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name in INCLUDE:
            tar.add(
                ROOT / name,
                arcname=name,
                filter=lambda ti: None if "__pycache__" in ti.name or ti.name.endswith(".pyc") else ti,
            )
    return buf.getvalue()


def main(argv: list[str]) -> int:
    targets = argv or ["tests/unit", "tests/contract", "tests/integration"]
    script = (
        "set -e; mkdir /w; cd /w; tar -xf -; "
        "pip install -q --root-user-action=ignore --disable-pip-version-check "
        "-r requirements-studio.txt -r requirements-dev.txt; "
        "uname -sr; python -V; "
        'exec python -m pytest -p no:cacheprovider -q "$@"'
    )
    cmd = [
        "docker", "run", "--rm", "-i", "--name", f"docqabot-test-linux-{os.getpid()}",
        "--network", f"container:{DB_CONTAINER}",
        "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "STUDIO_TESTS_REQUIRE_APP=1",
        "-e", f"TEST_DATABASE_URL={DB_URL}",
        IMAGE, "sh", "-c", script, "run_linux", *targets,
    ]
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    return subprocess.run(cmd, input=source_tar(), env=env).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
