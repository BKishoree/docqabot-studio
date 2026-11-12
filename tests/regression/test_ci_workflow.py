"""T9 local validation of .github/workflows/ci.yml (GitHub cannot run it before the push)."""

from __future__ import annotations

import yaml

from tests.conftest import ROOT

CI = ROOT / ".github" / "workflows" / "ci.yml"


def load():
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def test_ci_parses_and_has_three_jobs():
    wf = load()
    assert set(wf["jobs"]) == {"backend", "frontend", "container"}
    triggers = wf.get("on", wf.get(True))  # yaml 1.1 reads bare `on` as True
    assert "push" in triggers and "pull_request" in triggers


def test_ci_backend_checkout_has_full_history_and_tags():
    checkout = next(s for s in load()["jobs"]["backend"]["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == 0


def test_ci_uses_no_secrets_and_no_openai():
    text = CI.read_text(encoding="utf-8")
    assert "secrets." not in text
    assert "api.openai.com" not in text
    assert "OPENAI_API_KEY" not in text


def test_ci_runs_every_python_suite():
    runs = " ".join(s.get("run", "") for s in load()["jobs"]["backend"]["steps"])
    for suite in ("tests/unit", "tests/regression", "tests/contract", "tests/integration"):
        assert suite in runs
    assert load()["env"]["STUDIO_TESTS_REQUIRE_APP"] == "1"


def test_ci_container_job_runs_smoke_and_e2e():
    runs = " ".join(s.get("run", "") for s in load()["jobs"]["container"]["steps"])
    assert "up -d --wait" in runs and "tests/smoke/smoke.py" in runs and "playwright test" in runs
    assert "--force-recreate" in runs
