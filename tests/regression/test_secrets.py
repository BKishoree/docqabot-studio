"""T-R4 secret scan (AC3)."""

from __future__ import annotations

import re
import subprocess

from tests.conftest import ROOT

# Built from parts so this file never matches its own patterns.
SK = "sk" + "-"
PATTERNS = {
    "openai-style key": re.compile(re.escape(SK) + r"(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{32,}"),
    "aws access key": re.compile(r"\bAKIA" + r"[0-9A-Z]{16}\b"),
    "github token": re.compile(r"\bgh[pousr]_" + r"[A-Za-z0-9]{36,}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE " + r"KEY-----"),
    "anthropic key": re.compile(re.escape(SK) + r"ant-[A-Za-z0-9_\-]{20,}"),
}
# Assignments in dotenv / yaml / shell style: KEY=value or KEY: value
ASSIGN = re.compile(
    r"^\s*(?:export\s+|-\s+)?[\"']?(OPENAI_API_KEY|STUDIO_AUTH_PASSWORD)[\"']?\s*[=:]\s*[\"']?([^\"'\s#]*)",
    re.MULTILINE,
)
ALLOWED_VALUES = {
    "", "not-configured", SK + "demo-stub", SK + "stub-test", SK + "stub-invalid",
}
ALLOWED_VALUE_RE = re.compile(r"^\$\{?[A-Z_]+(:?-[^}]*)?\}?$|^\$\{\{.*")  # ${VAR}, ${VAR:-}, GH expressions
PLACEHOLDER_RE = re.compile(r"\.\.\.|your|<[^>]*>|change-?me|example|placeholder|xxx", re.IGNORECASE)
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".pdf", ".zip", ".lock"}


def _files() -> list[str]:
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True).stdout
    untracked = subprocess.run(
        ["git", "ls-files", "-z", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    names = {n for n in (tracked + untracked).split("\0") if n}
    return sorted(n for n in names if not any(n.lower().endswith(s) for s in SKIP_SUFFIXES))


def _read(rel: str) -> str | None:
    path = ROOT / rel
    if not path.is_file():
        return None
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if b"\0" in raw[:4096]:
        return None
    return raw.decode("utf-8", errors="replace")


def test_TR4_no_secrets_in_tracked_or_unignored_files():
    hits = []
    files = _files()
    assert files, "git ls-files returned nothing"
    for rel in files:
        text = _read(rel)
        if text is None:
            continue
        for label, rx in PATTERNS.items():
            for m in rx.finditer(text):
                hits.append(f"{rel}: {label}: {m.group(0)[:8]}…")
        for m in ASSIGN.finditer(text):
            value = m.group(2)
            if value in ALLOWED_VALUES or ALLOWED_VALUE_RE.match(value) or PLACEHOLDER_RE.search(value):
                continue
            # Python/TS code that reads the variable is not an assignment of a secret.
            if value.startswith(("os.", "process.", "getenv", "env")):
                continue
            hits.append(f"{rel}: {m.group(1)} assigned a non-placeholder value")
    assert not hits, "possible secrets:\n" + "\n".join(hits)


def test_TR4_dotenv_is_ignored():
    r = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT)
    assert r.returncode == 0, ".env is not git-ignored"
    tracked = subprocess.run(["git", "ls-files", ".env"], cwd=ROOT, capture_output=True, text=True).stdout
    assert tracked.strip() == "", ".env is tracked"


def test_TR4_env_example_has_placeholders_only():
    path = ROOT / ".env.example"
    if not path.exists():
        import pytest

        from tests.conftest import REQUIRE_APP

        if REQUIRE_APP:
            pytest.fail(".env.example missing")
        pytest.skip(".env.example not delivered yet")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    assert values.get("OPENAI_API_KEY", "") == ""
    assert values.get("STUDIO_AUTH_USER", "") == ""
    assert values.get("STUDIO_AUTH_PASSWORD", "") == ""
    assert values.get("POSTGRES_PASSWORD", "change-me") in {"", "change-me"}
