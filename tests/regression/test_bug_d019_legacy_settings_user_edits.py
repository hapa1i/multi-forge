"""D019 regression: legacy settings removal must preserve user-modified values."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.core.runtime_vocab import CLAUDE_CODE_RUNTIME
from forge.install.installer import Installer
from forge.install.models import (
    Installation,
    InstalledSettingsEntry,
    InstallModule,
    InstallScope,
)
from forge.install.ownership import attributed
from forge.install.settings_merge import read_settings, write_settings
from forge.install.tracking import TrackingStore

pytestmark = pytest.mark.regression


def test_legacy_unmerge_does_not_unconditionally_delete_modified_scalar_and_env(
    tmp_path: Path,
) -> None:
    """Pin D019's unconditional scalar/env deletion in legacy no-sidecar unmerge."""

    project_root = tmp_path / "project"
    settings_path = project_root / ".claude" / "settings.json"
    tracked_statusline = {"type": "command", "command": "forge status-line"}
    user_statusline = {"type": "command", "command": "my status-line"}
    write_settings(
        settings_path,
        {
            "statusLine": user_statusline,
            "env": {
                "EDITED": "user-value",
                "OWNED": "forge-value",
                "USER_ONLY": "keep-me",
            },
        },
    )

    statusline_owner = attributed(InstallModule.STATUSLINE, CLAUDE_CODE_RUNTIME)
    permissions_owner = attributed(InstallModule.PERMISSIONS, CLAUDE_CODE_RUNTIME)
    entries = [
        InstalledSettingsEntry(
            key_path="statusLine",
            value=tracked_statusline,
            merge_type="scalar",
            stable_id="statusLine",
            attribution=statusline_owner,
        ),
        InstalledSettingsEntry(
            key_path="env.EDITED",
            value="forge-value",
            merge_type="env",
            stable_id="EDITED",
            attribution=permissions_owner,
        ),
        InstalledSettingsEntry(
            key_path="env.OWNED",
            value="forge-value",
            merge_type="env",
            stable_id="OWNED",
            attribution=permissions_owner,
        ),
    ]
    tracking = TrackingStore(tmp_path / ".forge" / "installed.json")
    tracking.set_installation(
        InstallScope.PROJECT.value,
        Installation(
            scope=InstallScope.PROJECT.value,
            project_path=str(project_root),
            mode="copy",
            profile="minimal",
            module_owners=sorted({statusline_owner, permissions_owner}),
            settings_entries=entries,
            installed_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        ),
        str(project_root),
    )

    Installer(
        scope=InstallScope.PROJECT,
        project_root=project_root,
        tracking_store=tracking,
    ).uninstall()

    assert read_settings(settings_path) == {
        "statusLine": user_statusline,
        "env": {"EDITED": "user-value", "USER_ONLY": "keep-me"},
    }
    assert tracking.get_installation(InstallScope.PROJECT.value, str(project_root)) is None
