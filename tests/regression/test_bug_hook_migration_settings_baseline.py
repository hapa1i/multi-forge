"""Hook migration must retain the original baseline for a later full disable."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from forge.install.hook_migration import apply_project_hook_migration
from forge.install.installer import Installer
from forge.install.models import (
    Installation,
    InstalledSettingsEntry,
    InstallModule,
    InstallScope,
)
from forge.install.ownership import attributed
from forge.install.settings_merge import (
    entries_to_added_structure,
    get_settings_path,
    read_settings,
    save_added_settings,
)
from forge.install.tracking import TrackingStore
from tests.src.install.test_hook_migration import (
    _forge_root,
    _installation,
    _legacy_entry,
)

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("scope", [InstallScope.PROJECT, InstallScope.USER])
@pytest.mark.parametrize("has_baseline_file", [False, True])
def test_migration_preserves_original_baseline_and_disable_removes_statusline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scope: InstallScope,
    has_baseline_file: bool,
) -> None:
    project = _forge_root(tmp_path)
    legacy = _legacy_entry()
    get_settings_path(InstallScope.PROJECT, project).write_text(json.dumps({"hooks": {"SessionStart": [legacy]}}))
    settings = get_settings_path(scope, project)
    settings.parent.mkdir(parents=True, exist_ok=True)
    statusline = {"type": "command", "command": "forge status-line"}
    current: dict[str, object] = {"theme": "user edit", "statusLine": statusline}
    if scope == InstallScope.PROJECT:
        current["hooks"] = {"SessionStart": [legacy]}
    settings.write_text(json.dumps(current))
    installation = (
        _installation(project, legacy)
        if scope == InstallScope.PROJECT
        else Installation(
            scope="user",
            mode="copy",
            profile="minimal",
            module_owners=[attributed(InstallModule.STATUSLINE, "claude_code")],
        )
    )
    installation.settings_entries.append(
        InstalledSettingsEntry(
            key_path="statusLine",
            value=statusline,
            merge_type="scalar",
            stable_id="statusLine",
            attribution=attributed(InstallModule.STATUSLINE, "claude_code"),
        )
    )
    original_baseline = settings.parent / ".settings.json.forge.backup.original"
    if has_baseline_file:
        original_baseline.write_text(json.dumps({"theme": "original"}))
        installation.settings_backup_path = str(original_baseline)
    save_added_settings(settings, entries_to_added_structure(installation.settings_entries))
    tracking = TrackingStore(tmp_path / "installed.json")
    project_path = str(project) if scope == InstallScope.PROJECT else None
    tracking.set_installation(scope.value, installation, project_path)
    monkeypatch.setattr(
        "forge.install.hook_migration.diagnose_hook_dispatcher", lambda: SimpleNamespace(status="current")
    )
    monkeypatch.setattr("forge.install.hook_migration.install_hook_dispatcher", lambda: None)

    apply_project_hook_migration(project, tracking=tracking)

    updated = tracking.get_installation(scope.value, project_path)
    assert updated is not None
    assert updated.settings_backup_path == installation.settings_backup_path
    if has_baseline_file:
        assert json.loads(original_baseline.read_text()) == {"theme": "original"}
    Installer(scope=scope, project_root=project, tracking_store=tracking).uninstall()
    assert read_settings(settings) == {"theme": "user edit"}
