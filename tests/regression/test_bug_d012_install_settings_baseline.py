"""D012 regression: repeated settings writes must retain the pre-Forge baseline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from forge.core.runtime import get_runtime
from forge.core.runtime_vocab import CLAUDE_CODE_RUNTIME
from forge.install.installer import Installer
from forge.install.models import InstallModule, InstallProfile, InstallScope
from forge.install.settings_merge import (
    find_backup_files,
    read_settings,
    write_settings,
)
from forge.install.tracking import TrackingStore

pytestmark = pytest.mark.regression


def _run_with_timestamp(installer: Installer, source_root: Path, timestamp: str, *, update: bool = False) -> None:
    with (
        patch("forge.install.installer.get_forge_source_root", return_value=source_root),
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=[get_runtime(CLAUDE_CODE_RUNTIME)],
        ),
        patch("forge.install.settings_merge._get_timestamp", return_value=timestamp),
    ):
        if update:
            installer.update()
        else:
            installer.init(
                profile=InstallProfile.MINIMAL,
                with_modules={InstallModule.STATUSLINE},
            )


@pytest.mark.parametrize("second_run", ["enable", "sync"])
@pytest.mark.parametrize(
    "second_timestamp",
    ["20260101-000001", "20260101-000000"],
    ids=["later", "same-second"],
)
def test_repeated_settings_runs_preserve_pre_forge_baseline_for_full_disable(
    tmp_path: Path,
    second_run: str,
    second_timestamp: str,
) -> None:
    """Pin D012's baseline rotation plus newest-backup selection failure across sync and disable."""

    source_root = tmp_path / "forge-source"
    (source_root / "src" / "forge").mkdir(parents=True)
    commands = source_root / "src" / "commands"
    commands.mkdir()
    (commands / "review.md").write_text("# Review\n", encoding="utf-8")

    project_root = tmp_path / "project"
    settings_path = project_root / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    pre_forge = {"theme": "dark"}
    write_settings(settings_path, pre_forge)

    tracking = TrackingStore(tmp_path / ".forge" / "installed.json")
    installer = Installer(
        scope=InstallScope.PROJECT,
        project_root=project_root,
        tracking_store=tracking,
    )

    _run_with_timestamp(installer, source_root, "20260101-000000")
    first = tracking.get_installation(InstallScope.PROJECT.value, str(project_root))
    assert first is not None
    assert first.settings_backup_path is not None
    baseline_path = Path(first.settings_backup_path)
    assert read_settings(baseline_path) == pre_forge

    current = read_settings(settings_path)
    current["theme"] = "light"
    write_settings(settings_path, current)
    _run_with_timestamp(
        installer,
        source_root,
        second_timestamp,
        update=second_run == "sync",
    )

    updated = tracking.get_installation(InstallScope.PROJECT.value, str(project_root))
    assert updated is not None
    assert updated.settings_backup_path == str(baseline_path)
    assert read_settings(baseline_path) == pre_forge
    assert len(find_backup_files(settings_path)) == 2

    installer.uninstall()

    final_settings = read_settings(settings_path)
    assert final_settings == {"theme": "light"}
    assert len(find_backup_files(settings_path)) == 2
    assert tracking.get_installation(InstallScope.PROJECT.value, str(project_root)) is None
