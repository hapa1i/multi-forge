"""Unified corrupt-state handling.

Forge-owned durable-state corruption (session manifests, indexes, proxy
registry, installed manifest, proxy config) is surfaced once, through the
top-level ``AliasGroup.main`` catch, as a clear reset instruction instead of a
traceback. The mechanism is: every corruption error is a ``StateCorruptedError``,
and ``handle_corrupt_state_error`` prints the uniform recovery tip.
"""

from __future__ import annotations

import click
import pytest

from forge.config.loader import get_proxy_file_path, load_proxy_instance_config
from forge.core.state.exceptions import StateCorruptedError
from forge.install.exceptions import ForgeInstallError, TrackingCorruptedError
from forge.session.exceptions import (
    ForgeSessionError,
    IndexCorruptedError,
    ManifestCorruptedError,
    ManifestValidationError,
)


def test_corruption_errors_are_state_corrupted_errors() -> None:
    """Every durable-corruption error is a StateCorruptedError so one handler catches all."""
    manifest = ManifestCorruptedError("/x/forge.session.json", "bad json")
    validation = ManifestValidationError("/x/forge.session.json", ["name"])
    index = IndexCorruptedError("/x/index.json", "bad")
    tracking = TrackingCorruptedError("/x/installed.json", "bad")

    for exc in (manifest, validation, index, tracking):
        assert isinstance(exc, StateCorruptedError)
        assert exc.path  # the offending file is always named
        assert exc.reason  # ManifestValidationError derives a reason too

    # Domain bases still hold, so existing `except ForgeSessionError`/`ForgeInstallError`
    # callers (internal scan-degrade paths) keep intercepting before the top-level handler.
    assert isinstance(manifest, ForgeSessionError)
    assert isinstance(tracking, ForgeInstallError)


def test_load_proxy_instance_config_raises_state_corrupted_on_bad_yaml() -> None:
    """A malformed proxy.yaml raises typed StateCorruptedError, not a bare ValueError."""
    path = get_proxy_file_path("broken")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("tiers: [unclosed\n", encoding="utf-8")

    with pytest.raises(StateCorruptedError) as ei:
        load_proxy_instance_config("broken")
    assert str(path) in str(ei.value)


def test_load_proxy_instance_config_raises_state_corrupted_on_non_mapping() -> None:
    path = get_proxy_file_path("listy")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("- just\n- a list\n", encoding="utf-8")

    with pytest.raises(StateCorruptedError) as ei:
        load_proxy_instance_config("listy")
    assert "mapping" in str(ei.value)


def test_handle_corrupt_state_error_prints_reset_tip_and_exits(capsys: pytest.CaptureFixture[str]) -> None:
    from forge.cli.output import handle_corrupt_state_error

    err = StateCorruptedError("/p/.forge/sessions/x/forge.session.json", "could not parse")
    with pytest.raises(SystemExit) as ei:
        handle_corrupt_state_error(err)
    assert ei.value.code == 1

    out = capsys.readouterr().err
    assert "Forge state is corrupt" in out
    assert "forge extension enable" in out
    assert "forge clean" in out


def test_aliasgroup_main_catches_corrupt_state(capsys: pytest.CaptureFixture[str]) -> None:
    """A StateCorruptedError raised inside any command is caught once at the root group."""
    from forge.cli.main import AliasGroup

    @click.group(cls=AliasGroup)
    def root() -> None:
        pass

    @root.command()
    def boom() -> None:
        raise IndexCorruptedError("/p/.forge/sessions/index.json", "truncated")

    assert boom.name == "boom"  # registered command; references the symbol

    with pytest.raises(SystemExit) as ei:
        root.main(["boom"], prog_name="forge")
    assert ei.value.code == 1

    out = capsys.readouterr().err
    assert "Forge state is corrupt" in out
    assert "index.json" in out


def test_session_list_corrupt_index_routes_to_handler() -> None:
    """A corrupt global index surfaces the uniform reset tip via `forge session list`.

    Regression for the domain-catch bypass: list_sessions_op wraps ForgeSessionError as
    ForgeOpError, which would otherwise drop the reset tip. The op now defers
    StateCorruptedError to the top-level handler so corruption surfaces the same instruction
    regardless of which command hit it first.
    """
    from click.testing import CliRunner

    from forge.cli.main import main
    from forge.session.index import get_index_path

    index_path = get_index_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("{corrupt index")

    result = CliRunner().invoke(main, ["session", "list"])
    combined = result.output + (result.stderr or "")
    assert result.exit_code == 1
    assert "Traceback" not in combined
    assert "Forge state is corrupt" in combined
    assert "forge clean" in combined
