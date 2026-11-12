"""Static checks of the container files for R10 / AC23 / AC24 (no Docker needed)."""

from __future__ import annotations

import re

import pytest
import yaml

from tests.conftest import REQUIRE_APP, ROOT

COMPOSE = ["compose.yaml", "compose.demo.yaml"]
CONTAINER_FILES = COMPOSE + ["Dockerfile", ".dockerignore"]


def _need(name):
    p = ROOT / name
    if not p.exists():
        if REQUIRE_APP:
            pytest.fail(f"{name} missing")
        pytest.skip(f"{name} not delivered yet")
    return p


def _compose(name):
    return yaml.safe_load(_need(name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", CONTAINER_FILES)
def test_no_windows_paths_or_crlf(name):
    raw = _need(name).read_bytes()
    assert b"\r\n" not in raw, f"{name} has CRLF line endings"
    text = raw.decode("utf-8")
    assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", text), f"{name} contains a drive-letter path"
    for line in text.splitlines():
        stripped = line.split("#", 1)[0]
        assert "\\\\" not in stripped and not re.search(r"\\[A-Za-z]", stripped.replace("\\$", "")), (
            f"{name}: backslash path in {line!r}"
        )


@pytest.mark.parametrize("name", COMPOSE)
def test_no_host_bind_mounts(name):
    services = _compose(name).get("services", {})
    for svc, spec in services.items():
        for vol in spec.get("volumes", []) or []:
            source = vol.get("source") if isinstance(vol, dict) else str(vol).split(":", 1)[0]
            kind = vol.get("type", "volume") if isinstance(vol, dict) else None
            assert kind in (None, "volume"), f"{name}/{svc}: {kind} mount"
            assert re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", source or ""), f"{name}/{svc}: host path {source!r}"


def test_state_only_in_named_volumes():
    base, demo = _compose("compose.yaml"), _compose("compose.demo.yaml")
    assert "docqabot_pgdata" in base["volumes"]
    assert "docqabot_pgdata_demo" in demo["volumes"]
    assert "volumes" not in base["services"]["app"], "app container must be stateless"
    assert "volumes" not in demo["services"].get("app", {}), "app container must be stateless"
    db_vols = [str(v) for v in base["services"]["db"]["volumes"]]
    assert db_vols == ["docqabot_pgdata:/var/lib/postgresql/data"]
    assert [str(v) for v in demo["services"]["db"]["volumes"]] == ["docqabot_pgdata_demo:/var/lib/postgresql/data"]


def test_ports_and_settings_from_environment():
    app = _compose("compose.yaml")["services"]["app"]
    assert app["ports"] == ["${STUDIO_BIND_ADDR:-127.0.0.1}:${STUDIO_PORT:-8000}:8000"]
    db = _compose("compose.yaml")["services"]["db"]
    assert db["ports"] == ["${STUDIO_DB_BIND_ADDR:-127.0.0.1}:${STUDIO_DB_PORT:-5433}:5432"]
    env = app["environment"]
    assert "ivfflat.probes%3D100" in env["DATABASE_URL"]
    assert env["OPENAI_API_KEY"] == "${OPENAI_API_KEY:-}", "no key value in compose"
    assert app["depends_on"]["db"]["condition"] == "service_healthy"
    assert app["env_file"] == [{"path": ".env", "required": False}]


def test_demo_override_routes_to_stub():
    demo = _compose("compose.demo.yaml")["services"]
    assert demo["app"]["environment"]["STUDIO_DEMO_MODE"] == "true"
    assert demo["app"]["environment"]["STUDIO_STUB_URL"] == "http://openai-stub:8001/v1"
    assert "ports" not in demo["openai-stub"], "stub must not be published"
    assert demo["app"]["depends_on"]["openai-stub"]["condition"] == "service_healthy"


def test_dockerfile_health_check_user_and_no_secrets():
    text = _need("Dockerfile").read_text(encoding="utf-8")
    assert "/api/v1/health/live" in text and "HEALTHCHECK" in text
    assert re.search(r"^USER (?!root)\S+", text, re.M), "image must not run as root"
    assert "EXPOSE 8000" in text
    assert "OPENAI_API_KEY" not in text
    assert not re.search(r"^COPY .*\.env\b", text, re.M)
    assert "curl" not in text


def test_dockerignore_keeps_secrets_and_tests_out():
    lines = set(_need(".dockerignore").read_text(encoding="utf-8").split())
    assert {".env", ".git", "tests", "e2e", "node_modules"} <= lines


def test_C2_password_note_in_readme_and_env_example():
    """Architect Review v1 C2: POSTGRES_PASSWORD applies only when the volume is first created."""
    env = _need(".env.example").read_text(encoding="utf-8")
    readme = _need("README.md").read_text(encoding="utf-8")
    assert re.search(r"first created", env, re.I) and "ALTER USER" in env
    assert re.search(r"(first created|initialises an empty volume)", readme, re.I) and "ALTER USER" in readme
