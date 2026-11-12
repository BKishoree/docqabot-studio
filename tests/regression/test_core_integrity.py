"""T-R1 core integrity (AC1, AC18) and T-R2 import boundary (AC2)."""

from __future__ import annotations

import ast
import pathlib
import subprocess

import pytest

from tests.conftest import REQUIRE_APP, ROOT

BASELINE = "core-baseline"
CORE_FILES = {"app/chunker.py", "app/database.py", "app/embeddings.py", "app/main.py", "app/rag.py"}
ALLOWED_IMPORTERS = {"studio/core_adapter.py", "studio/bootstrap.py"}


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def test_baseline_tag_present():
    r = git("rev-parse", "--verify", "--quiet", f"refs/tags/{BASELINE}^{{commit}}")
    assert r.returncode == 0, "tag core-baseline missing (CI must check out with fetch-depth: 0 and tags)"


def test_TR1_no_diff_against_baseline():
    r = git("diff", "--exit-code", "--stat", BASELINE, "--", "app/", "requirements.txt")
    assert r.returncode == 0, f"core changed vs {BASELINE}:\n{r.stdout}{r.stderr}"


def test_TR1_no_uncommitted_or_untracked_core_changes():
    r = git("status", "--porcelain", "--untracked-files=all", "--", "app/", "requirements.txt")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", f"working-tree changes in core:\n{r.stdout}"


def test_TR1_app_holds_exactly_the_five_baseline_files():
    tracked = set(git("ls-files", "app/").stdout.split())
    assert tracked == CORE_FILES
    baseline = set(git("ls-tree", "-r", "--name-only", BASELINE, "app/").stdout.split())
    assert baseline == CORE_FILES
    on_disk = {
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "app").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    assert on_disk == CORE_FILES, f"unexpected files in app/: {sorted(on_disk - CORE_FILES)}"


def test_TR1_requirements_still_utf16_with_bom():
    raw = (ROOT / "requirements.txt").read_bytes()
    assert raw[:2] == b"\xff\xfe", "root requirements.txt lost its UTF-16 LE BOM"
    text = raw.decode("utf-16")
    assert "openai" in text.lower() and "psycopg2" in text.lower()


def _studio_py_files() -> list[pathlib.Path]:
    studio = ROOT / "studio"
    if not studio.is_dir():
        if REQUIRE_APP:
            pytest.fail("studio/ does not exist")
        pytest.skip("studio/ not delivered yet")
    return sorted(p for p in studio.rglob("*.py") if "__pycache__" not in p.parts)


def _app_imports(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name == "app" or a.name.startswith("app.")]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "app" or node.module.startswith("app."):
                found.append(node.module)
        elif isinstance(node, ast.Call):
            # importlib.import_module("app...") / __import__("app...")
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name in {"import_module", "__import__"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if arg.value == "app" or arg.value.startswith("app."):
                        found.append(arg.value)
    return found


def test_TR2_only_adapter_and_bootstrap_import_app():
    offenders = {}
    for path in _studio_py_files():
        rel = path.relative_to(ROOT).as_posix()
        imports = _app_imports(path)
        if imports and rel not in ALLOWED_IMPORTERS:
            offenders[rel] = imports
    assert not offenders, f"modules other than {sorted(ALLOWED_IMPORTERS)} import app: {offenders}"


def test_TR2_adapter_exists_and_imports_core():
    files = {p.relative_to(ROOT).as_posix(): p for p in _studio_py_files()}
    if "studio/core_adapter.py" not in files and not REQUIRE_APP:
        pytest.skip("studio/core_adapter.py not delivered yet")
    assert "studio/core_adapter.py" in files
    assert _app_imports(files["studio/core_adapter.py"]), "core_adapter.py does not import app"


def test_TR2_stub_is_free_of_app_and_bootstrap():
    stub_dir = ROOT / "studio" / "stub"
    if not stub_dir.is_dir():
        if REQUIRE_APP:
            pytest.fail("studio/stub/ does not exist")
        pytest.skip("studio/stub not delivered yet")
    for path in stub_dir.rglob("*.py"):
        assert not _app_imports(path), path
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith("studio.bootstrap") for a in node.names), path
            elif isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
                assert not mod.startswith("studio.bootstrap"), path
                assert not (mod == "studio" and any(a.name == "bootstrap" for a in node.names)), path
                if node.level:  # relative import from inside studio/stub
                    assert "bootstrap" not in mod and not any(a.name == "bootstrap" for a in node.names), path
