"""Relative Codex homes are valid install targets, not corrupt ownership records."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from forge.core.ops.gc import collect_clean_report, run_clean
from forge.install.codex_hooks import (
    apply_codex_merge,
    get_builtin_codex_entries,
    get_codex_config_path,
)
from forge.install.installer import Installer
from forge.install.models import (
    Installation,
    InstalledManifest,
    InstallMode,
    InstallModule,
    InstallProfile,
    InstallScope,
)
from forge.install.ownership import attributed
from forge.install.tracking import TrackingStore
from tests.src.core.ops.test_gc import _make_ctx
from tests.src.install.test_runtime_scoped_modules import (
    _isolated_sources,
    _write_extension_sources,
)

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("codex_home", [".codex-alt", "."])
def test_relative_codex_home_survives_enable_sync_clean_and_disable(tmp_path, monkeypatch, codex_home):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_HOME", codex_home)
    extensions = _write_extension_sources(tmp_path)
    tracking = TrackingStore()
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

    with _isolated_sources(extensions, "codex"):
        enabled = installer.init(
            profile=InstallProfile.STANDARD,
            mode=InstallMode.COPY,
            skill_runtimes=("codex",),
            _modules_override={InstallModule.HOOKS, InstallModule.SKILLS},
        )
        assert not enabled.has_conflicts
        installation = tracking.get_installation("user")
        assert installation is not None
        assert installation.codex_config_path == str(Path(codex_home) / "config.toml")
        assert not installer.update().has_conflicts

        before = tracking.path.read_bytes()
        config = get_codex_config_path(InstallScope.USER)
        config_before = config.read_bytes()
        owned_files = {Path(row.target_path): Path(row.target_path).read_bytes() for row in installation.files}
        assert owned_files
        report = collect_clean_report(ctx=_make_ctx(tmp_path), scope="all")
        assert not any(str(tracking.path) in category.items for category in report.categories)
        run_clean(ctx=_make_ctx(tmp_path), scope="all")
        assert tracking.path.read_bytes() == before
        assert config.read_bytes() == config_before
        assert all(path.read_bytes() == content for path, content in owned_files.items())

        installer.uninstall()
        assert tracking.get_installation("user") is None
        assert not config.exists() or "# >>> forge hooks >>>" not in config.read_text()


@pytest.mark.parametrize("operation", ["read", "clean_preview", "clean_apply"])
def test_preexisting_relative_config_witness_is_not_corrupt(tmp_path, monkeypatch, operation):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CODEX_HOME", ".codex-alt")
    config = get_codex_config_path(InstallScope.USER)
    entries = get_builtin_codex_entries()
    apply_codex_merge(config, entries)
    installation = Installation(
        scope="user",
        mode="copy",
        profile="minimal",
        module_owners=[attributed(InstallModule.HOOKS, "codex")],
        codex_config_path=str(config),
        codex_commands=[entry.command for entry in entries],
    )
    tracking = TrackingStore()
    tracking.path.parent.mkdir(parents=True, exist_ok=True)
    # Released installers persisted this spelling; load the existing on-disk record directly.
    tracking.path.write_text(json.dumps(asdict(InstalledManifest(installations={"user": installation}))))
    before = tracking.path.read_bytes()
    config_before = config.read_bytes()

    if operation == "read":
        assert tracking.get_installation("user") == installation
    elif operation == "clean_preview":
        report = collect_clean_report(ctx=_make_ctx(tmp_path), scope="all")
        assert not any(str(tracking.path) in category.items for category in report.categories)
    else:
        run_clean(ctx=_make_ctx(tmp_path), scope="all")
    assert tracking.path.read_bytes() == before
    assert config.read_bytes() == config_before
