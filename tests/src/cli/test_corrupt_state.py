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


def test_aliasgroup_main_catches_unreadable_state(capsys: pytest.CaptureFixture[str]) -> None:
    """A StateUnreadableError (failed read, not bad content) is caught at the root group too.

    Routes to the distinct check/retry message -- never the corrupt-state reset tip (which
    would wrongly suggest deletion) and never a traceback.
    """
    from forge.cli.main import AliasGroup
    from forge.session.exceptions import IndexUnreadableError

    @click.group(cls=AliasGroup)
    def root() -> None:
        pass

    @root.command()
    def boom() -> None:
        raise IndexUnreadableError("/p/.forge/sessions/index.json", "read error: [Errno 5] I/O error")

    assert boom.name == "boom"  # registered command; references the symbol

    with pytest.raises(SystemExit) as ei:
        root.main(["boom"], prog_name="forge")
    assert ei.value.code == 1

    out = capsys.readouterr().err
    assert "could not read a state file" in out
    assert "index.json" in out
    assert "Forge state is corrupt" not in out  # not misrouted to the reset handler


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


# ---------------------------------------------------------------------------
# The exception-split ripple: a transient *read failure* (OSError) is a state
# problem too, so it must propagate to the unreadable handler at the same
# specific-target resolution sites -- never get swallowed into a misleading
# "no session found" dead-end (the durable-state policy forbids that).
# ---------------------------------------------------------------------------


def _seed_valid_session(name: str, tmp_path: Path) -> Path:
    """Index a session with a VALID manifest on disk. Returns the manifest path."""
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
    return fr / ".forge" / "sessions" / name / "forge.session.json"


def _fail_open_for(monkeypatch: pytest.MonkeyPatch, target: Path) -> None:
    """Make ``open(target, ...)`` raise OSError; delegate every other open (path-scoped)."""
    import builtins

    real_open = builtins.open
    target_str = str(target)

    def fake_open(file, *args, **kwargs):  # type: ignore[no-untyped-def]
        if str(file) == target_str:
            raise OSError("simulated transient I/O failure")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)


def test_get_session_context_propagates_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """session show: an unreadable manifest raises StateUnreadableError, not 'no session found'."""
    from forge.core.ops.session_context import get_session_context
    from forge.core.state.exceptions import StateUnreadableError

    manifest = _seed_valid_session("locked", tmp_path)
    _fail_open_for(monkeypatch, manifest)
    with pytest.raises(StateUnreadableError):
        get_session_context("locked")


def test_session_show_unreadable_manifest_routes_to_handler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from click.testing import CliRunner

    from forge.cli.main import main

    manifest = _seed_valid_session("locked", tmp_path)
    _fail_open_for(monkeypatch, manifest)
    result = CliRunner().invoke(main, ["session", "show", "locked"])
    combined = result.output + (result.stderr or "")
    assert result.exit_code == 1
    assert "Traceback" not in combined
    assert "could not read a state file" in combined
    assert "no session found" not in combined.lower()  # not the misleading dead-end
    assert "Forge state is corrupt" not in combined  # not misrouted to the reset handler


def test_in_chat_session_show_emits_block_on_unreadable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`%session show` stays a JSON block decision on an unreadable manifest -- with check/retry guidance."""
    import io
    from contextlib import redirect_stdout

    from forge.cli.hooks.direct_commands import _handle_session_show

    manifest = _seed_valid_session("locked", tmp_path)
    _fail_open_for(monkeypatch, manifest)
    buf = io.StringIO()
    with redirect_stdout(buf):
        _handle_session_show(["locked"])

    payload = json.loads(buf.getvalue())
    assert payload["decision"] == "block"
    assert "could not read" in payload["reason"].lower()
    assert "will not delete" in payload["reason"].lower()  # never suggests deletion
    assert "corrupt" not in payload["reason"].lower()


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


# ---------------------------------------------------------------------------
# Comprehensive class fix: the op layer (proxy registry, codex resolve/start,
# transfer regenerate) and the env-var resolution fallbacks all defer corruption
# to the top-level handler instead of masking it as ForgeOpError / a generic
# registry error / "no session found". Regression for the broad-`except`
# interception class (a corruption error is also a domain error, so the domain
# catch would otherwise swallow it before the root handler).
# ---------------------------------------------------------------------------


def test_proxy_registry_corrupt_routes_to_handler() -> None:
    """A corrupt proxy registry surfaces the uniform reset tip via `forge proxy list`."""
    from click.testing import CliRunner

    from forge.cli.main import main
    from forge.proxy.proxies import get_proxy_registry_path

    path = get_proxy_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ corrupt registry", encoding="utf-8")

    result = CliRunner().invoke(main, ["proxy", "list"])
    combined = result.output + (result.stderr or "")
    assert result.exit_code == 1
    assert "Traceback" not in combined
    assert "Forge state is corrupt" in combined
    assert "forge clean" in combined


def test_resolve_codex_session_propagates_corruption(tmp_path: Path) -> None:
    """The codex resolve op re-raises a corrupt manifest instead of wrapping it as ForgeOpError."""
    from forge.core.ops.codex_session import resolve_codex_session
    from forge.session import SessionManager

    _seed_corrupt_manifest_session("bad", tmp_path)
    with pytest.raises(StateCorruptedError):
        resolve_codex_session(SessionManager(), "bad", forge_root=tmp_path / "project")


def test_regenerate_transfer_propagates_corruption(tmp_path: Path) -> None:
    """The transfer-regenerate op re-raises a corrupt parent manifest, not 'parent not found'."""
    from forge.core.ops.context import ExecutionContext
    from forge.core.ops.transfer import regenerate_transfer

    _seed_corrupt_manifest_session("bad", tmp_path)
    fr = tmp_path / "project"
    ctx = ExecutionContext(cwd=fr, worktree_root=fr, project_root=fr, forge_root=fr)
    with pytest.raises(StateCorruptedError):
        regenerate_transfer(ctx=ctx, parent="bad")


def test_in_chat_proxy_list_emits_json_block_on_corrupt_registry() -> None:
    """`%proxy list` stays a JSON block decision on a corrupt registry -- not a Rich tip / exit 1.

    Regression for the hook-contract gap: list_proxies now propagates
    ProxyRegistryCorruptedError (a StateCorruptedError, not a ForgeOpError), so the
    assistant-facing handler must catch it and emit a decision block rather than let it
    escape to the CLI reset handler (which would break the UserPromptSubmit JSON contract).
    """
    import io
    from contextlib import redirect_stdout

    from forge.cli.hooks.direct_commands import _handle_proxy_list
    from forge.proxy.proxies import get_proxy_registry_path

    path = get_proxy_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ corrupt registry", encoding="utf-8")

    buf = io.StringIO()
    with redirect_stdout(buf):
        _handle_proxy_list()

    payload = json.loads(buf.getvalue())
    assert payload["decision"] == "block"
    assert "corrupt" in payload["reason"].lower()
    assert "forge clean" in payload["reason"]


def test_in_chat_session_list_emits_json_block_on_corrupt_index() -> None:
    """`%session list` stays a JSON block decision on a corrupt index -- not a Rich tip / exit 1."""
    import io
    from contextlib import redirect_stdout

    from forge.cli.hooks.direct_commands import _handle_cmd_session
    from forge.session.index import get_index_path

    index_path = get_index_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("{ corrupt index", encoding="utf-8")

    buf = io.StringIO()
    with redirect_stdout(buf):
        _handle_cmd_session({}, ["list"])

    payload = json.loads(buf.getvalue())
    assert payload["decision"] == "block"
    assert "corrupt" in payload["reason"].lower()
    assert "forge clean" in payload["reason"]


def test_resolve_session_identifier_env_corrupt_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """FORGE_SESSION pointing at a corrupt index propagates, not a silent fall-through.

    Guards the nested env-fallback: IndexCorruptedError is also a ForgeSessionError, so
    the env-var ``except ForgeSessionError`` would otherwise swallow it and end at the
    generic "No session found" path instead of the reset handler.
    """
    from forge.core.ops.session_context import resolve_session_identifier
    from forge.session.index import get_index_path

    index_path = get_index_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("{ corrupt index", encoding="utf-8")

    monkeypatch.setenv("FORGE_SESSION", "whatever")
    monkeypatch.delenv("FORGE_FORGE_ROOT", raising=False)
    with pytest.raises(StateCorruptedError):
        resolve_session_identifier(None)
