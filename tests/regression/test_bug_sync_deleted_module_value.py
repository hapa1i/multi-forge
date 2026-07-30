"""Regression: sync migrates the released ``codex-hooks`` module value."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.install.installer import Installer
from forge.install.models import InstallScope
from forge.install.tracking import TrackingStore

pytestmark = pytest.mark.regression


def test_sync_normalizes_deleted_codex_hooks_value_without_value_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracking = TrackingStore(tmp_path / "tracking" / "installed.json")
    tracking.path.parent.mkdir(parents=True)
    tracking.path.write_text(
        json.dumps(
            {
                "version": 2,
                "installations": {
                    "user": {
                        "scope": "user",
                        "mode": "copy",
                        "profile": "standard",
                        "modules_enabled": ["codex-hooks"],
                        "files": [],
                        "skill_packages": [],
                        "settings_entries": [],
                        "codex_config_path": None,
                        "codex_commands": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    extensions = tmp_path / "empty-extensions"
    extensions.mkdir()
    monkeypatch.setattr("forge.install.installer.get_extensions_root", lambda: extensions)

    plan = Installer(scope=InstallScope.USER, tracking_store=tracking).update()

    assert not plan.has_conflicts
    persisted = json.loads(tracking.path.read_text(encoding="utf-8"))
    assert persisted["version"] == 3
    assert persisted["installations"]["user"]["module_owners"] == []
    assert "modules_enabled" not in persisted["installations"]["user"]
