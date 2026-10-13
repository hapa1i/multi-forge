"""Sync cannot infer that a migrated, unattributed surface is a stale module file."""

from pathlib import Path

import pytest

from forge.install.installer import Installer
from forge.install.models import (
    Installation,
    InstalledFile,
    InstallModule,
    InstallProfile,
    InstallScope,
)
from forge.install.ownership import attributed, unattributed
from forge.install.tracking import TrackingStore, compute_checksum
from tests.src.install.test_runtime_scoped_modules import (
    _isolated_sources,
    _write_extension_sources,
)

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("operation", ["sync", "enable"])
@pytest.mark.parametrize("modified", [False, True])
def test_refresh_preserves_unattributed_file_and_tracking(tmp_path: Path, operation: str, modified: bool) -> None:
    project = tmp_path / "project"
    target = project / ".claude" / "legacy.bin"
    target.parent.mkdir(parents=True)
    target.write_text("legacy")
    record = InstalledFile(
        target_path=str(target),
        source_path=str(tmp_path / "retired-source"),
        checksum=compute_checksum(target),
        mode="copy",
        installed_at="2026-07-01T00:00:00Z",
        attribution=unattributed("legacy_path_unmapped"),
    )
    if modified:
        target.write_text("user edit")
    tracking = TrackingStore(tmp_path / "installed.json")
    tracking.set_installation(
        "project",
        Installation(
            scope="project",
            project_path=str(project),
            mode="copy",
            profile="minimal",
            module_owners=[attributed(InstallModule.COMMANDS, "claude_code")],
            files=[record],
        ),
        str(project),
    )
    extensions = _write_extension_sources(tmp_path, empty_file_modules=True)
    installer = Installer(scope=InstallScope.PROJECT, project_root=project, tracking_store=tracking)
    with _isolated_sources(extensions, "claude_code"):
        if operation == "sync":
            installer.update()
        else:
            installer.init(profile=InstallProfile.MINIMAL)

    assert target.read_text() == ("user edit" if modified else "legacy")
    installation = tracking.get_installation("project", str(project))
    assert installation is not None
    assert record in installation.files

    # Full disable remains an explicit removal of the entire tracked installation.
    installer.uninstall()
    assert not target.exists()
