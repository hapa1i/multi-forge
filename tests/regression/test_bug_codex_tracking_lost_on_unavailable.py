"""Regression: Codex hook tracking lost when codex is temporarily unavailable.

Bug (codex_frontend Phase 6 review, P1): ``Installer._execute_codex()``
returned ``(None, [])`` for the unavailable/conflict outcomes, and ``init()``
only preserved prior tracking when the module was absent from the run
(``plan.codex is None``). A previously written managed block therefore stayed
on disk while ``Installation.codex_config_path`` was overwritten to ``None``
-- a later ``forge extension disable`` no longer knew to remove it (orphaned
block in the user's Codex config).

Root cause: src/forge/install/installer.py -- the "no authoritative outcome"
cases (no codex binary, conflict, apply failure) were conflated with the
legitimately-empty outcome (skip due to a manual registration, where ownership
transferred to the user and dropping tracking is correct).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Generator
from unittest.mock import patch

import pytest

from forge.install.installer import Installer
from forge.install.models import InstallScope
from forge.install.tracking import TrackingStore

pytestmark = pytest.mark.regression


@pytest.fixture
def setup_installer(tmp_path: Path) -> Generator[tuple[Installer, Path], None, None]:
    """Minimal installer over temp dirs (mirrors TestInstallerCodexHooks)."""
    forge_home = tmp_path / ".forge"
    forge_home.mkdir()
    # Must match the autouse isolate_claude_home target (settings boundary check).
    claude_home = tmp_path / "claude_home"

    src = tmp_path / "src"
    src.mkdir()
    commands = src / "commands"
    commands.mkdir()
    (commands / "test.md").write_text("# Test Command\n")
    (src / "skills").mkdir()
    (src / "forge").mkdir()

    tracking = TrackingStore(tracking_path=forge_home / "installed.json")
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    yield installer, claude_home


def _run(installer: Installer, claude_home: Path, method: str = "init", available: bool = True, **kwargs: Any) -> Any:
    src_parent = claude_home.parent / "src"
    with patch("forge.install.installer.get_forge_source_root", return_value=src_parent.parent):
        with patch("forge.install.installer.get_target_root", return_value=claude_home):
            with patch("forge.install.installer._codex_available", return_value=available):
                return getattr(installer, method)(**kwargs)


def _codex_config() -> Path:
    import os

    return Path(os.environ["CODEX_HOME"]) / "config.toml"


def test_unavailable_rerun_preserves_tracking_and_disable_cleans_up(
    setup_installer: tuple[Installer, Path],
) -> None:
    """The exact failure: enable (codex present) -> re-enable (codex absent).

    Tracking must survive the unavailable run so a later disable -- which
    does not gate on the binary -- still removes the on-disk block.
    """
    installer, claude_home = setup_installer
    _run(installer, claude_home)
    assert "# >>> forge hooks >>>" in _codex_config().read_text()

    _run(installer, claude_home, available=False)

    installation = installer._tracking.get_installation("user", None)
    assert installation is not None
    assert installation.codex_config_path == str(_codex_config()), (
        "tracking lost on an unavailable re-run: the managed block is still "
        "on disk but disable would no longer know to remove it"
    )

    _run(installer, claude_home, method="uninstall", available=False)
    assert not _codex_config().exists()


def test_conflict_rerun_preserves_tracking(setup_installer: tuple[Installer, Path]) -> None:
    """A config corrupted after install (plan=conflict) must not drop tracking.

    remove_codex_block de-blocks textually even when the remainder is
    unparseable, so disable can still clean up -- but only if tracking
    survives the conflicted run.
    """
    installer, claude_home = setup_installer
    _run(installer, claude_home)
    config = _codex_config()
    config.write_text("not = valid = toml\n" + config.read_text())

    _run(installer, claude_home)

    installation = installer._tracking.get_installation("user", None)
    assert installation is not None
    assert installation.codex_config_path == str(config)

    _run(installer, claude_home, method="uninstall")
    assert "# >>> forge hooks >>>" not in config.read_text()


def test_manual_registration_skip_still_drops_tracking(setup_installer: tuple[Installer, Path]) -> None:
    """Guard the deliberate non-preserve case: ownership transferred to the user.

    Block removed by hand + commands re-registered manually -> the skip
    outcome is authoritative ("nothing Forge-owned on disk") and tracking
    must clear, not be preserved.
    """
    installer, claude_home = setup_installer
    _run(installer, claude_home)
    manual = (
        "[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n"
        'type = "command"\ncommand = "forge hook codex-session-start"\ntimeout = 60\n'
        "[[hooks.PreToolUse]]\n[[hooks.PreToolUse.hooks]]\n"
        'type = "command"\ncommand = "forge hook codex-policy-check"\ntimeout = 60\n'
    )
    _codex_config().write_text(manual)

    _run(installer, claude_home)

    installation = installer._tracking.get_installation("user", None)
    assert installation is not None
    assert installation.codex_config_path is None
    assert installation.codex_commands == []
