"""Unified corrupt-state handling.

Forge-owned durable-state corruption (session manifests, indexes, proxy
registry, installed manifest, proxy config) is surfaced once, through the
top-level ``AliasGroup.main`` catch, as a clear reset instruction instead of a
traceback. The mechanism is: every corruption error is a ``StateCorruptedError``,
and ``handle_corrupt_state_error`` prints the uniform recovery tip.
"""

from __future__ import annotations

import json
from pathlib import Path

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


# ---------------------------------------------------------------------------
# User-facing command routing: corruption must reach the uniform reset handler,
# not surface a raw parse error. Regression for the review finding that
# session show / session resume / extension status bypassed the top-level handler.
# ---------------------------------------------------------------------------


def _seed_corrupt_manifest_session(name: str, tmp_path: Path) -> None:
    """Index a session under tmp_path, then corrupt its manifest on disk."""
    from forge.session import IndexStore, SessionStore, create_session_state

    fr = tmp_path / "project"
    SessionStore(str(fr), name).write(create_session_state(name, worktree_path=str(fr)))
    IndexStore().add_session(
        name=name,
        worktree_path=str(fr),
        project_root=str(tmp_path),
        forge_root=str(fr),
        checkout_root=str(fr),
        relative_path=".",
        is_incognito=False,
        is_fork=False,
        parent_session=None,
    )
    (fr / ".forge" / "sessions" / name / "forge.session.json").write_text("{ corrupt manifest", encoding="utf-8")


def test_handle_session_error_routes_corruption_to_reset_handler(capsys: pytest.CaptureFixture[str]) -> None:
    """The central session-error chokepoint delegates corruption to the corrupt-state tip.

    Covers session resume + every other command that funnels through handle_session_error.
    """
    from forge.cli.output import handle_session_error

    with pytest.raises(SystemExit) as ei:
        handle_session_error(ManifestCorruptedError("/p/.forge/sessions/x/forge.session.json", "invalid JSON"))
    assert ei.value.code == 1
    out = capsys.readouterr().err
    assert "Forge state is corrupt" in out
    assert "forge clean" in out


def test_get_session_context_propagates_corruption(tmp_path: Path) -> None:
    """session show: a corrupt manifest raises StateCorruptedError, not a wrapped SessionContextError."""
    from forge.core.ops.session_context import get_session_context

    _seed_corrupt_manifest_session("bad", tmp_path)
    with pytest.raises(StateCorruptedError):
        get_session_context("bad")


def test_session_show_corrupt_manifest_routes_to_handler(tmp_path: Path) -> None:
    from click.testing import CliRunner

    from forge.cli.main import main

    _seed_corrupt_manifest_session("bad", tmp_path)
    result = CliRunner().invoke(main, ["session", "show", "bad"])
    combined = result.output + (result.stderr or "")
    assert result.exit_code == 1
    assert "Traceback" not in combined
    assert "Forge state is corrupt" in combined
    assert "forge clean" in combined


def test_extension_status_corrupt_tracking_routes_to_handler() -> None:
    from click.testing import CliRunner

    from forge.cli.main import main
    from forge.install.tracking import get_tracking_path

    path = get_tracking_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ corrupt tracking", encoding="utf-8")

    result = CliRunner().invoke(main, ["extension", "status"])
    combined = result.output + (result.stderr or "")
    assert result.exit_code == 1
    assert "Traceback" not in combined
    assert "Forge state is corrupt" in combined
    assert "forge clean" in combined


def test_in_chat_session_show_emits_json_block_on_corruption(tmp_path: Path) -> None:
    """The %session show hook stays a JSON block decision -- never a Rich tip or traceback."""
    import io
    from contextlib import redirect_stdout

    from forge.cli.hooks.direct_commands import _handle_session_show

    _seed_corrupt_manifest_session("bad", tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        _handle_session_show(["bad"])

    payload = json.loads(buf.getvalue())
    assert payload["decision"] == "block"
    assert "corrupt" in payload["reason"].lower()
    assert "forge clean" in payload["reason"]
