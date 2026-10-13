"""Invalid Codex config witnesses must fail before disable can discard tracking."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from forge.install.codex_hooks import (
    apply_codex_merge,
    get_builtin_codex_entries,
    get_codex_config_path,
)
from forge.install.exceptions import TrackingCorruptedError
from forge.install.installer import Installer
from forge.install.models import (
    Installation,
    InstalledManifest,
    InstallModule,
    InstallScope,
)
from forge.install.ownership import attributed
from forge.install.tracking import TrackingStore

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("invalid_path", ["", " ", "\t\n"])
def test_invalid_codex_config_path_is_rejected_before_mutation(tmp_path: Path, invalid_path: str) -> None:
    config = get_codex_config_path(InstallScope.USER)
    apply_codex_merge(config, get_builtin_codex_entries())
    original_config = config.read_bytes()
    tracking = TrackingStore(tmp_path / "installed.json")
    installation = Installation(
        scope="user",
        mode="copy",
        profile="minimal",
        module_owners=[attributed(InstallModule.HOOKS, "codex")],
        codex_config_path=invalid_path,
        codex_commands=["codex-session-start"],
    )
    with pytest.raises(TrackingCorruptedError, match="codex_config_path.*nonblank"):
        tracking.set_installation("user", installation)
    assert not tracking.path.exists()

    # Simulate a corrupted on-disk witness; normal writers must never produce this.
    tracking.path.write_text(json.dumps(asdict(InstalledManifest(installations={"user": installation}))))
    original_tracking = tracking.path.read_bytes()
    with pytest.raises(TrackingCorruptedError, match="codex_config_path.*nonblank"):
        Installer(scope=InstallScope.USER, tracking_store=tracking).uninstall()
    assert tracking.path.read_bytes() == original_tracking
    assert config.read_bytes() == original_config
