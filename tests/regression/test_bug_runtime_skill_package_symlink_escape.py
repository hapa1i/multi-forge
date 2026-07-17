"""Regression: a substituted runtime-skill package symlink must not escape ownership."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from forge.core.runtime import get_runtime
from forge.install.exceptions import ForgeInstallError
from forge.install.installer import Installer, inspect_skill_package_status
from forge.install.models import (
    InstallMode,
    InstallModule,
    InstallProfile,
    InstallScope,
)
from forge.install.tracking import TrackingStore

pytestmark = pytest.mark.regression


def test_bug_runtime_skill_package_symlink_cannot_delete_sibling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extensions_root = tmp_path / "extensions"
    source = extensions_root / "skills" / "portable"
    (source / "references").mkdir(parents=True)
    (source / "forge-skill.yaml").write_text(
        """\
schema_version: 1
name: portable
description: Runtime package symlink regression fixture.
runtimes: [claude_code, codex]
""",
        encoding="utf-8",
    )
    (source / "content.md").write_text("# Portable\n\nRegression fixture.\n", encoding="utf-8")
    (source / "references" / "note.md").write_text("tracked auxiliary\n", encoding="utf-8")
    monkeypatch.setattr("forge.install.installer.get_extensions_root", lambda: extensions_root)
    monkeypatch.setattr("forge.install.installer.installed_runtimes", lambda: [get_runtime("codex")])

    tracking = TrackingStore(tracking_path=tmp_path / "tracking" / "installed.json")
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    installer.init(
        profile=InstallProfile.STANDARD,
        mode=InstallMode.COPY,
        skill_runtimes=("codex",),
        _modules_override={InstallModule.SKILLS},
    )

    installation = tracking.get_installation("user", None)
    assert installation is not None
    package = installation.skill_packages[0]
    package_dir = Path(package.target_dir)
    sibling_dir = package_dir.parent / "sibling"
    shutil.copytree(package_dir, sibling_dir)
    sibling_bytes = {
        relative: (sibling_dir / relative).read_bytes()
        for relative in (Path(path).relative_to(package_dir) for path in package.file_paths)
    }
    shutil.rmtree(package_dir)
    package_dir.symlink_to(sibling_dir, target_is_directory=True)

    status = inspect_skill_package_status(
        installation,
        InstallScope.USER,
        None,
        tracked_installations=tracking.list_installations(),
    )

    assert status[0].state == "invalid-target"
    assert status[0].target_present is False
    with pytest.raises(ForgeInstallError, match="Cannot change extensions"):
        installer.update()
    with pytest.raises(ForgeInstallError, match="security violation"):
        installer.uninstall()

    assert package_dir.is_symlink()
    assert {relative: (sibling_dir / relative).read_bytes() for relative in sibling_bytes} == sibling_bytes
    assert tracking.get_installation("user", None) is not None
