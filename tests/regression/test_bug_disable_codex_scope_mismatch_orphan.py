"""Regression: disable must not orphan Codex hooks after CODEX_HOME changes.

Root cause: the pre-fix ``Installer._remove_codex_registration`` treated a
tracked Codex config path that no longer matched the current scope mapping as
a successful no-op. ``uninstall()`` then removed the installation's tracking
row, leaving the managed hook block active with no recorded owner.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Generator
from unittest.mock import patch

import pytest

from forge.core.runtime import get_runtime
from forge.core.runtime_vocab import CLAUDE_CODE_RUNTIME, CODEX_RUNTIME
from forge.install.exceptions import ForgeInstallError
from forge.install.installer import Installer
from forge.install.models import InstallScope
from forge.install.settings_merge import find_added_files, find_backup_files
from forge.install.tracking import TrackingStore

pytestmark = pytest.mark.regression


@pytest.fixture
def setup_installer(tmp_path: Path) -> Generator[tuple[Installer, Path, Path, Path], None, None]:
    """Minimal installer over temp dirs (mirrors TestInstallerCodexHooks)."""
    forge_home = tmp_path / ".forge"
    forge_home.mkdir()
    tracking_path = forge_home / "installed.json"
    # Must match the autouse isolate_claude_home target (settings boundary check).
    claude_home = tmp_path / "claude_home"

    src = tmp_path / "src"
    src.mkdir()
    commands = src / "commands"
    commands.mkdir()
    (commands / "test.md").write_text("# Test Command\n")
    (src / "skills").mkdir()
    (src / "forge").mkdir()

    tracking = TrackingStore(tracking_path=tracking_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    yield installer, claude_home, src, tracking_path


def _run(installer: Installer, src: Path, claude_home: Path, method: str = "init", **kwargs: Any) -> Any:
    with (
        patch("forge.install.installer.get_forge_source_root", return_value=src.parent),
        patch("forge.install.installer.get_target_root", return_value=claude_home),
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=[get_runtime(CLAUDE_CODE_RUNTIME), get_runtime(CODEX_RUNTIME)],
        ),
        patch("forge.install.installer._codex_available", return_value=True),
    ):
        return getattr(installer, method)(**kwargs)


def _codex_config() -> Path:
    return Path(os.environ["CODEX_HOME"]) / "config.toml"


def test_scope_mismatch_preserves_managed_state_and_tracking(
    setup_installer: tuple[Installer, Path, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installer, claude_home, src, tracking_path = setup_installer
    settings_path = claude_home / "settings.json"
    settings_path.write_text('{"userSetting": true}\n')
    _run(installer, src, claude_home)

    installation = installer._tracking.get_installation("user", None)
    assert installation is not None
    assert installation.codex_config_path is not None
    tracked_codex_config = Path(installation.codex_config_path)
    assert tracked_codex_config.resolve().is_relative_to(tmp_path.resolve())
    assert "# >>> forge hooks >>>" in tracked_codex_config.read_text()

    tracked_payloads = [Path(file_record.target_path) for file_record in installation.files]
    backup_files = find_backup_files(settings_path)
    added_files = find_added_files(settings_path)
    assert tracked_payloads
    assert backup_files
    assert added_files

    managed_files = [
        *tracked_payloads,
        settings_path,
        *backup_files,
        *added_files,
        tracked_codex_config,
        tracking_path,
    ]
    before = {path: path.read_bytes() for path in managed_files}

    moved_codex_home = tmp_path / "moved_codex_home"
    moved_codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(moved_codex_home))
    assert tracked_codex_config.resolve() != _codex_config().resolve()

    error: ForgeInstallError | None = None
    try:
        _run(installer, src, claude_home, method="uninstall")
    except ForgeInstallError as exc:
        error = exc

    block_present = tracked_codex_config.is_file() and "# >>> forge hooks >>>" in tracked_codex_config.read_text()
    tracking_present = installer._tracking.get_installation("user", None) is not None
    assert block_present and tracking_present, (
        "scope mismatch orphaned the managed Codex block: "
        f"block_present={block_present}, tracking_present={tracking_present}, error={error!r}"
    )
    assert error is not None
    assert type(error).__name__ == "CodexConfigScopeMismatchError", repr(error)
    assert {path: path.read_bytes() for path in managed_files} == before
