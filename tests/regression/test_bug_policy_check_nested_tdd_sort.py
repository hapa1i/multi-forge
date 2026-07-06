"""Regression: ``%policy check`` must sort nested tests before nested src files.

Bug: the direct Claude diagnostic path sorted only top-level ``tests/`` and
``src/`` paths. For a nested ``pkg/src`` + ``pkg/tests`` diff, Git reports
``pkg/src`` first, so TDD evaluated implementation before the sibling test and
false-denied an atomic impl+test change.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks._group import hooks
from forge.policy.deterministic.base import (
    tests_first_sort_key as _tests_first_sort_key,
)
from forge.session import SessionStore, create_session_state
from forge.session.models import PolicyIntent

pytestmark = pytest.mark.regression


def _make_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True, check=True)
    (path / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(path), capture_output=True, check=True)


def _make_tdd_session(path: Path) -> None:
    store = SessionStore(str(path), "test-session")
    manifest = create_session_state("test-session")
    manifest.intent.policy = PolicyIntent(enabled=True, bundles=["tdd"], fail_mode="closed")
    store.write(manifest)


def test_policy_check_orders_nested_tests_before_nested_src(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_git_repo(tmp_path)
    _make_tdd_session(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", "test-session")

    src_dir = tmp_path / "pkg" / "src"
    tests_dir = tmp_path / "pkg" / "tests"
    src_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    (src_dir / "widget.py").write_text("# placeholder\n")
    (tests_dir / "test_widget.py").write_text("# placeholder\n")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "add nested files"], cwd=str(tmp_path), capture_output=True, check=True)

    (src_dir / "widget.py").write_text("def widget():\n    return 42\n")
    (tests_dir / "test_widget.py").write_text("def test_widget():\n    assert True\n")

    result = CliRunner().invoke(
        hooks,
        ["user-prompt-submit"],
        input=json.dumps({"prompt": "%policy check --bundle tdd", "transcript_path": ""}),
    )

    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["decision"] == "block"
    assert out["passed"] is True
    assert out["files_checked"] == 2


def test_tests_first_sort_key_keeps_backslash_paths_nested_aware() -> None:
    assert _tests_first_sort_key(r"pkg\tests\test_widget.py") == 0
    assert _tests_first_sort_key(r"pkg\src\widget.py") == 2
