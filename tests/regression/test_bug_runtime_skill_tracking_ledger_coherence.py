"""Regression: runtime package ownership must match the canonical file ledger."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.install.exceptions import TrackingCorruptedError
from forge.install.installer import Installer
from forge.install.models import InstallScope
from forge.install.tracking import TrackingStore

pytestmark = pytest.mark.regression


def test_bug_incoherent_skill_package_tracking_cannot_drop_ownership(
    tmp_path: Path,
) -> None:
    package_dir = Path.home() / ".agents" / "skills" / "portable"
    package_dir.mkdir(parents=True)
    skill_document = package_dir / "SKILL.md"
    skill_document.write_text("managed package\n", encoding="utf-8")
    tracking_path = tmp_path / "tracking" / "installed.json"
    tracking_path.parent.mkdir(parents=True)
    tracking_path.write_text(
        json.dumps(
            {
                "version": 2,
                "installations": {
                    "user": {
                        "scope": "user",
                        "mode": "copy",
                        "profile": "standard",
                        "modules_enabled": ["skills"],
                        "files": [],
                        "skill_packages": [
                            {
                                "runtime": "codex",
                                "skill": "portable",
                                "target_dir": str(package_dir),
                                "file_paths": [str(skill_document)],
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    original_tracking = tracking_path.read_bytes()
    tracking = TrackingStore(tracking_path=tracking_path)
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

    with pytest.raises(TrackingCorruptedError, match="not backed by files ledger"):
        tracking.get_installation("user", None)
    with pytest.raises(TrackingCorruptedError, match="not backed by files ledger"):
        installer.uninstall()

    assert skill_document.read_text(encoding="utf-8") == "managed package\n"
    assert tracking_path.read_bytes() == original_tracking
