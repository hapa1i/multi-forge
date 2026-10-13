"""Codex-only enable must not depend on unrelated Claude settings or presets."""

from pathlib import Path

import pytest

from forge.install.installer import Installer
from forge.install.models import InstallModule, InstallProfile, InstallScope
from forge.install.preset import get_preset_path
from forge.install.settings_merge import get_settings_path
from forge.install.tracking import TrackingStore
from tests.src.install.test_runtime_scoped_modules import (
    _isolated_sources,
    _write_extension_sources,
)

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("malformed", ["settings", "preset"])
def test_codex_only_enable_preserves_unreadable_claude_input(tmp_path: Path, malformed: str) -> None:
    extensions = _write_extension_sources(tmp_path)
    settings = get_settings_path(InstallScope.USER)
    preset = get_preset_path()
    unrelated = settings if malformed == "settings" else preset
    unrelated.parent.mkdir(parents=True, exist_ok=True)
    unrelated.write_text("{malformed Claude JSON")
    tracking = TrackingStore(tmp_path / "installed.json")

    with _isolated_sources(extensions, "codex"):
        plan = Installer(scope=InstallScope.USER, tracking_store=tracking).init(
            profile=InstallProfile.MINIMAL,
            with_modules={InstallModule.HOOKS},
            skill_runtimes=("codex",),
        )

    assert not plan.has_conflicts
    assert unrelated.read_text() == "{malformed Claude JSON"
    assert not (preset if malformed == "settings" else settings).exists()
    installation = tracking.get_installation("user")
    assert installation is not None
    assert installation.codex_config_path is not None
    assert "# >>> forge hooks >>>" in Path(installation.codex_config_path).read_text()
