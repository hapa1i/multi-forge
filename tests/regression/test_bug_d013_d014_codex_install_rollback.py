"""D013/D014 regression: Codex config mutations belong to the install transaction.

Root causes: ``Installer._execute_codex`` wrote the managed block outside the
existing file/settings rollback state, and its post-write registration read ran
without a typed failure boundary. A read-back or final tracking failure could
therefore leave an untracked Codex block and other partially installed surfaces.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from forge.core.runtime import get_runtime
from forge.core.runtime_vocab import CLAUDE_CODE_RUNTIME, CODEX_RUNTIME
from forge.core.state import atomic_write_text
from forge.install.codex_hooks import apply_codex_merge, get_builtin_codex_entries
from forge.install.exceptions import ForgeInstallError
from forge.install.installer import Installer
from forge.install.models import InstallScope
from forge.install.tracking import TrackingStore

pytestmark = pytest.mark.regression


@pytest.fixture
def installer_setup(
    tmp_path: Path,
    isolate_claude_home: Path,
) -> Generator[tuple[Installer, TrackingStore, Path, Path], None, None]:
    forge_home = tmp_path / ".forge"
    forge_home.mkdir()
    claude_home = isolate_claude_home

    source = tmp_path / "src"
    source.mkdir()
    (source / "commands").mkdir()
    (source / "commands" / "review.md").write_text("# Review\n", encoding="utf-8")
    (source / "skills").mkdir()
    (source / "forge").mkdir()

    tracking = TrackingStore(tracking_path=forge_home / "installed.json")
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)
    yield installer, tracking, claude_home, source


def _run(installer: Installer, claude_home: Path, source: Path, **kwargs: Any) -> Any:
    assert claude_home == Path(os.environ["CLAUDE_HOME"])
    with (
        patch("forge.install.installer.get_forge_source_root", return_value=source.parent),
        patch(
            "forge.install.installer.installed_runtimes",
            return_value=[get_runtime(CLAUDE_CODE_RUNTIME), get_runtime(CODEX_RUNTIME)],
        ),
        patch("forge.install.installer._codex_available", return_value=True),
    ):
        return installer.init(**kwargs)


@pytest.mark.parametrize("fault", ["readback", "tracking"])
@pytest.mark.parametrize("config_state", ["missing", "user", "stale-block"])
def test_codex_failure_restores_every_pre_install_surface(
    installer_setup: tuple[Installer, TrackingStore, Path, Path],
    fault: str,
    config_state: str,
) -> None:
    installer, tracking, claude_home, source = installer_setup
    config_path = Path(os.environ["CODEX_HOME"]) / "config.toml"
    original_config = b'model = "gpt-5.6-codex"\n'
    original_config_mode = 0o640
    if config_state == "user":
        config_path.write_bytes(original_config)
        config_path.chmod(original_config_mode)
    elif config_state == "stale-block":
        apply_codex_merge(config_path, get_builtin_codex_entries()[:1])
        config_path.chmod(original_config_mode)
        original_config = config_path.read_bytes()

    settings_path = claude_home / "settings.json"
    original_settings = b'{"env": {"USER_VALUE": "kept"}}\n'
    original_settings_mode = 0o640
    settings_path.write_bytes(original_settings)
    settings_path.chmod(original_settings_mode)

    if fault == "readback":
        failure = patch(
            "forge.install.installer.read_codex_registration",
            side_effect=OSError("injected Codex read-back failure"),
        )
    else:
        failure = patch.object(
            tracking,
            "set_installation",
            side_effect=OSError("injected tracking commit failure"),
        )

    with failure, pytest.raises(ForgeInstallError):
        _run(installer, claude_home, source)

    if config_state != "missing":
        assert config_path.read_bytes() == original_config
        assert stat.S_IMODE(config_path.stat().st_mode) == original_config_mode
    else:
        assert not config_path.exists()
    assert settings_path.read_bytes() == original_settings
    assert stat.S_IMODE(settings_path.stat().st_mode) == original_settings_mode
    assert not list(settings_path.parent.glob(f".{settings_path.name}.forge.added.*"))
    assert not (claude_home / "commands" / "review.md").exists()
    assert tracking.get_installation("user", None) is None

    recovered = _run(installer, claude_home, source)
    assert not recovered.has_conflicts
    assert "# >>> forge hooks >>>" in config_path.read_text(encoding="utf-8")
    assert tracking.get_installation("user", None) is not None


def test_incomplete_codex_rollback_names_the_config_without_claiming_success(
    installer_setup: tuple[Installer, TrackingStore, Path, Path],
) -> None:
    installer, tracking, claude_home, source = installer_setup
    config_path = Path(os.environ["CODEX_HOME"]) / "config.toml"

    with (
        patch.object(
            tracking,
            "set_installation",
            side_effect=OSError("injected tracking commit failure"),
        ),
        patch(
            "forge.install.installer.restore_codex_config_rollback_state",
            return_value=[f"Codex config '{config_path}'"],
        ),
        pytest.raises(ForgeInstallError) as exc_info,
    ):
        _run(installer, claude_home, source)

    message = str(exc_info.value)
    assert "Could not roll back" in message
    assert f"Codex config '{config_path}'" in message
    assert "inspect and restore those paths before retrying" in message
    assert "Codex config were rolled back" not in message


@pytest.mark.parametrize("config_existed", [False, True], ids=["missing-config", "existing-config"])
def test_codex_apply_failure_after_replace_restores_config(
    installer_setup: tuple[Installer, TrackingStore, Path, Path],
    config_existed: bool,
) -> None:
    installer, tracking, claude_home, source = installer_setup
    config_path = Path(os.environ["CODEX_HOME"]) / "config.toml"
    original = b'model = "gpt-5.6-codex"\n'
    if config_existed:
        config_path.write_bytes(original)
        config_path.chmod(0o640)

    def write_then_fail(path: Path, content: str, **kwargs: Any) -> None:
        atomic_write_text(path, content, **kwargs)
        raise OSError("injected post-replace Codex write failure")

    with (
        patch("forge.install.codex_hooks.atomic_write_text", side_effect=write_then_fail),
        pytest.raises(ForgeInstallError, match="Failed to apply Codex hook registration"),
    ):
        _run(installer, claude_home, source)

    if config_existed:
        assert config_path.read_bytes() == original
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o640
    else:
        assert not config_path.exists()
    assert not (claude_home / "commands" / "review.md").exists()
    assert tracking.get_installation("user", None) is None
