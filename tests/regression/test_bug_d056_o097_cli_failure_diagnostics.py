"""Regression D056/O097: terminating CLI diagnostics were split across streams.

Root cause: workflow, extension, and policy adapters printed their error header with
the shared stderr helper but kept details, plans, or recovery tips on stdout.
Affected files: ``forge/cli/workflow.py``, ``extensions.py``, and ``policy.py``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.install.exceptions import SettingsConflictError
from forge.install.models import InstallPlan, InstallScope

pytestmark = pytest.mark.regression


def _plan(
    *,
    has_conflicts: bool = False,
    requires_claude_version: bool = False,
    scope: str = "user",
) -> InstallPlan:
    return InstallPlan(
        scope=scope,
        mode="copy",
        profile="minimal",
        has_conflicts=has_conflicts,
        conflicts=["managed surface conflict"] if has_conflicts else [],
        requires_claude_version=requires_claude_version,
    )


def test_sync_conflict_plan_and_failure_stay_together_on_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    installer = SimpleNamespace(plan_update=lambda **_kwargs: _plan(has_conflicts=True))
    monkeypatch.setattr("forge.cli.extensions.Installer", lambda **_kwargs: installer)
    monkeypatch.setattr("forge.cli.extensions.find_forge_installation", lambda: (InstallScope.USER, None))

    result = CliRunner().invoke(main, ["extension", "sync"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Auto-detected scope: user" in result.stderr
    assert "Installation Plan" in result.stderr
    assert "managed surface conflict" in result.stderr
    assert "Sync failed due to conflicts" in result.stderr


def test_sync_success_keeps_auto_detected_scope_on_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan()
    installer = SimpleNamespace(
        plan_update=lambda **_kwargs: plan,
        update=lambda **_kwargs: plan,
    )
    monkeypatch.setattr("forge.cli.extensions.Installer", lambda **_kwargs: installer)
    monkeypatch.setattr("forge.cli.extensions.find_forge_installation", lambda: (InstallScope.USER, None))

    result = CliRunner().invoke(main, ["extension", "sync"])

    assert result.exit_code == 0
    assert "Auto-detected scope: user" in result.stdout
    assert "Already up to date" in result.stdout
    assert result.stderr == ""


def test_auto_detected_enable_buffers_created_notice_with_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    monkeypatch.chdir(project)
    plan = _plan(scope="local", requires_claude_version=True)

    def _raise_conflict(**_kwargs: object) -> None:
        raise SettingsConflictError("permissions.allow", ["Read"], ["Read", "Write"])

    installer = SimpleNamespace(plan=lambda **_kwargs: plan, init=_raise_conflict)
    monkeypatch.setattr("forge.cli.extensions.Installer", lambda **_kwargs: installer)
    monkeypatch.setattr(
        "forge.install.version.check_minimum_version",
        lambda: SimpleNamespace(ok=True),
    )

    result = CliRunner().invoke(main, ["extension", "enable", "--profile", "minimal"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.index("Auto-detected scope: local") < result.stderr.index("Created ")
    assert result.stderr.index("Created ") < result.stderr.index("Settings conflict")
    assert (project / ".claude").is_dir()


def test_enable_dry_run_conflict_keeps_creation_preview_on_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    installer = SimpleNamespace(plan=lambda **_kwargs: _plan(has_conflicts=True))
    monkeypatch.setattr("forge.cli.extensions.Installer", lambda **_kwargs: installer)

    result = CliRunner().invoke(
        main,
        ["extension", "enable", "--scope", "local", "--root", str(project), "--dry-run"],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Would create" in result.stderr
    assert ".forge" in result.stderr
    assert "managed surface conflict" in result.stderr


def test_enable_settings_conflict_and_recovery_stay_together_on_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_conflict(**_kwargs: object) -> None:
        raise SettingsConflictError("permissions.allow", ["Read"], ["Read", "Write"])

    installer = SimpleNamespace(plan=lambda **_kwargs: _plan(), init=_raise_conflict)
    monkeypatch.setattr("forge.cli.extensions.Installer", lambda **_kwargs: installer)

    result = CliRunner().invoke(main, ["extension", "enable", "--scope", "user", "--profile", "minimal"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Settings conflict" in result.stderr
    assert "permissions.allow" in result.stderr
    assert "Use --force to override" in result.stderr
