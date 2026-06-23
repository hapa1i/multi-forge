"""Unit tests for `forge codex status` (read-only Codex inspection).

Covers the read-only `status` leaf (the proxy-backed `start` launcher is tested in
`test_codex_start.py`). Runtime detection is faked so tests are deterministic
regardless of whether `codex` is on the host PATH; Codex config is written under a
temp ``$CODEX_HOME``. installed.json is isolated by the autouse FORGE_HOME fixture.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.install.codex_hooks import get_builtin_codex_entries, render_codex_block
from forge.install.exceptions import NoForgeInstallationError
from forge.install.models import Installation, InstallScope
from forge.install.tracking import TrackingStore

_EXPECTED_COMMANDS = {
    "forge hook codex-session-start",
    "forge hook codex-policy-check",
}

# Both commands present, but codex-session-start is under PreToolUse (its
# correct event is SessionStart) -- a registration that exists by name but
# cannot fire correctly.
_WRONG_EVENT_CONFIG = """\
# >>> forge hooks >>>
[[hooks.PreToolUse]]
[[hooks.PreToolUse.hooks]]
type = "command"
command = "forge hook codex-session-start"
timeout = 60

[[hooks.PreToolUse]]
[[hooks.PreToolUse.hooks]]
type = "command"
command = "forge hook codex-policy-check"
timeout = 60
# <<< forge hooks <<<
"""


class _FakeSpec:
    """Stand-in for a RuntimeSpec with controllable presence/version."""

    id = "codex"
    display_name = "Codex CLI"

    def __init__(self, *, installed: bool = False, version: str | None = None) -> None:
        self._installed = installed
        self._version = version

    def is_installed(self) -> bool:
        return self._installed

    def detect(self) -> str | None:
        return self._version


@pytest.fixture
def codex_home(tmp_path, monkeypatch):
    """Point Codex's user-scope config at a temp dir."""
    home = tmp_path / "codex"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home


def _fake_runtime(monkeypatch, *, installed: bool = False, version: str | None = None) -> None:
    monkeypatch.setattr(
        "forge.cli.codex.get_runtime",
        lambda _id: _FakeSpec(installed=installed, version=version),
    )


def _status_json(args: list[str]) -> dict:
    result = CliRunner().invoke(main, ["codex", "status", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_status_codex_absent_exits_zero(codex_home, monkeypatch):
    _fake_runtime(monkeypatch, installed=False)
    data = _status_json(["--json"])
    assert data["runtime"]["installed"] is False
    assert data["runtime"]["version"] is None


def test_status_reports_managed_block(codex_home, monkeypatch):
    _fake_runtime(monkeypatch, installed=True, version="1.2.3")
    (codex_home / "config.toml").write_text(render_codex_block(get_builtin_codex_entries()), encoding="utf-8")
    scope = _status_json(["--scope", "user", "--json"])["scopes"][0]
    assert scope["config_exists"] is True
    assert scope["block_present"] is True
    assert scope["registered"] == "yes"
    assert set(scope["commands_registered"]) == _EXPECTED_COMMANDS


def test_status_surfaces_installed_json_tracking(codex_home, monkeypatch):
    _fake_runtime(monkeypatch, installed=True, version="1.2.3")
    # installed.json is isolated under the autouse FORGE_HOME fixture.
    TrackingStore().set_installation(
        "user",
        Installation(
            scope="user",
            mode="copy",
            profile="standard",
            codex_config_path=str(codex_home / "config.toml"),
            codex_commands=["forge hook codex-session-start"],
        ),
    )
    scope = _status_json(["--scope", "user", "--json"])["scopes"][0]
    assert scope["tracked_config_path"] is not None
    assert scope["tracked_commands"] == ["forge hook codex-session-start"]


def test_status_catches_wrong_event(codex_home, monkeypatch):
    _fake_runtime(monkeypatch, installed=True, version="1.2.3")
    (codex_home / "config.toml").write_text(_WRONG_EVENT_CONFIG, encoding="utf-8")
    scope = _status_json(["--scope", "user", "--json"])["scopes"][0]
    assert scope["registered"] == "wrong-event"  # not "yes"


def test_status_does_not_claim_enrollment(codex_home, monkeypatch):
    _fake_runtime(monkeypatch, installed=True, version="1.2.3")
    (codex_home / "config.toml").write_text(render_codex_block(get_builtin_codex_entries()), encoding="utf-8")
    data = _status_json(["--json"])
    assert data["enrollment"] == "unverified by static read"
    assert data["verify_command"] == "forge runtime preflight codex --verify-enrollment"


def test_status_json_has_stable_fields(codex_home, monkeypatch):
    _fake_runtime(monkeypatch, installed=False)
    data = _status_json(["--json"])
    assert set(data) == {"runtime", "scopes", "enrollment", "verify_command"}
    assert set(data["runtime"]) == {"id", "display_name", "installed", "version"}
    assert set(data["scopes"][0]) == {
        "scope",
        "config_path",
        "config_exists",
        "block_present",
        "registered",
        "registered_pairs",
        "commands_registered",
        "tracked_config_path",
        "tracked_commands",
    }


def test_status_human_output(codex_home, monkeypatch):
    _fake_runtime(monkeypatch, installed=False)
    result = CliRunner().invoke(main, ["codex", "status"])
    assert result.exit_code == 0
    assert "Codex runtime" in result.output
    assert "Enrollment: unverified by static read" in result.output


def test_status_all_and_scope_mutually_exclusive(codex_home, monkeypatch):
    _fake_runtime(monkeypatch, installed=False)
    result = CliRunner().invoke(main, ["codex", "status", "--all", "--scope", "user"])
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_codex_group_registered_and_visible():
    top = CliRunner().invoke(main, ["--help"])
    assert top.exit_code == 0
    assert "codex" in top.output
    group = CliRunner().invoke(main, ["codex", "--help"])
    assert group.exit_code == 0
    # Two visible leaves now that the Phase 4 launcher shipped (card forge_codex_command_group).
    assert "status" in group.output
    assert "start" in group.output
    # `start` is a registered subcommand: invoking it without the required --proxy is a
    # missing-option error, not "No such command".
    no_proxy = CliRunner().invoke(main, ["codex", "start"])
    assert no_proxy.exit_code != 0
    assert "No such command" not in no_proxy.output
    assert "--proxy" in no_proxy.output


def test_status_all_includes_local_scope(codex_home, monkeypatch):
    _fake_runtime(monkeypatch, installed=False)
    data = _status_json(["--all", "--json"])
    # PROJECT and LOCAL share a config path but have distinct installed.json keys,
    # so --all must list local, not collapse it onto project.
    assert {sc["scope"] for sc in data["scopes"]} == {"user", "project", "local"}


def test_status_filters_unrelated_hooks(codex_home, monkeypatch):
    _fake_runtime(monkeypatch, installed=True, version="1.2.3")
    unrelated = (
        "\n[[hooks.PreToolUse]]\n[[hooks.PreToolUse.hooks]]\n"
        'type = "command"\ncommand = "some-unrelated-linter"\ntimeout = 30\n'
    )
    (codex_home / "config.toml").write_text(
        render_codex_block(get_builtin_codex_entries()) + unrelated, encoding="utf-8"
    )
    scope = _status_json(["--scope", "user", "--json"])["scopes"][0]
    pairs = " ".join(scope["registered_pairs"])
    assert "some-unrelated-linter" not in pairs  # not Forge's footprint
    assert "forge hook codex-session-start" in pairs


def test_status_project_scope_resolves_root_from_subdir(tmp_path, monkeypatch):
    _fake_runtime(monkeypatch, installed=True, version="1.2.3")
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".codex").mkdir()
    (root / ".codex" / "config.toml").write_text(render_codex_block(get_builtin_codex_entries()), encoding="utf-8")
    subdir = root / "src" / "deep"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    scope = _status_json(["--scope", "project", "--json"])["scopes"][0]
    # Resolved root/.codex/config.toml by walking up, not <subdir>/.codex.
    assert scope["config_exists"] is True
    assert scope["block_present"] is True


def test_status_default_uses_detected_scope(monkeypatch, tmp_path):
    _fake_runtime(monkeypatch, installed=False)
    monkeypatch.setattr(
        "forge.cli.codex.find_forge_installation",
        lambda **_: (InstallScope.PROJECT, tmp_path),
    )
    data = _status_json(["--json"])  # no --scope, no --all -> detected scope
    assert [sc["scope"] for sc in data["scopes"]] == ["project"]


def test_status_default_is_user_when_no_install(codex_home, monkeypatch):
    _fake_runtime(monkeypatch, installed=False)

    def _no_install(**_):
        raise NoForgeInstallationError("none")

    monkeypatch.setattr("forge.cli.codex.find_forge_installation", _no_install)
    data = _status_json(["--json"])
    assert [sc["scope"] for sc in data["scopes"]] == ["user"]
