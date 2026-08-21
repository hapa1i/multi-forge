"""Hook-wire tests for authority-before-policy denial."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks.commands import hooks
from forge.session.authority import (
    AUTHORITY_MARKER_ENV,
    authority_hook_contract_sha256,
    build_authority_marker,
    read_authority_events,
)
from forge.session.models import AuthorityIntent, PolicyIntent, create_session_state
from forge.session.store import SessionStore


def _managed_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    runtime: str,
    tier: str = "shell_closed",
) -> None:
    name = "advisory"
    state = create_session_state(
        name,
        worktree_path=str(tmp_path),
        runtime=runtime,
        authority=AuthorityIntent("advisory", tier),
    )
    state.forge_root = str(tmp_path)
    # Authority must run before this disabled ordinary-policy posture.
    state.intent.policy = PolicyIntent(enabled=False)
    SessionStore(str(tmp_path), name).write(state)
    marker = build_authority_marker(state, "run_0123456789ab", authority_hook_contract_sha256(runtime))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", name)
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(tmp_path))
    monkeypatch.setenv(AUTHORITY_MARKER_ENV, marker)


def _payload(tmp_path: Path, tool_name: object) -> str:
    return json.dumps(
        {
            "session_id": "session-id",
            "hook_event_name": "PreToolUse",
            "cwd": str(tmp_path),
            "tool_name": tool_name,
            "tool_input": {
                "file_path": "/secret/source.py",
                "command": "do not persist this",
            },
        }
    )


def test_claude_authority_denies_raw_write_and_journals_only_safe_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _managed_marker(tmp_path, monkeypatch, runtime="claude_code")

    result = CliRunner().invoke(hooks, ["authority-check"], input=_payload(tmp_path, "Write"))

    assert result.exit_code == 2
    assert "Artifact authority denied" in result.stderr
    events = read_authority_events(str(tmp_path), "advisory")
    assert len(events) == 1
    assert events[0].event_type == "request_denied"
    assert events[0].payload["covered_tool"] == "Write"
    serialized = json.dumps(events[0].payload)
    assert "source.py" not in serialized
    assert "do not persist" not in serialized


def test_claude_shell_closed_declines_read_without_grant_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _managed_marker(tmp_path, monkeypatch, runtime="claude_code")

    result = CliRunner().invoke(hooks, ["authority-check"], input=_payload(tmp_path, "Read"))

    assert result.exit_code == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert read_authority_events(str(tmp_path), "advisory") == []


def test_malformed_present_marker_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _managed_marker(tmp_path, monkeypatch, runtime="claude_code")
    monkeypatch.setenv(AUTHORITY_MARKER_ENV, "{malformed")

    result = CliRunner().invoke(hooks, ["authority-check"], input=_payload(tmp_path, "Read"))

    assert result.exit_code == 2
    event = read_authority_events(str(tmp_path), "advisory")[0]
    assert event.reason_code == "authority_guard_error"


def test_codex_authority_denies_bash_before_disabled_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _managed_marker(tmp_path, monkeypatch, runtime="codex")

    result = CliRunner().invoke(hooks, ["codex-policy-check"], input=_payload(tmp_path, "Bash"))

    assert result.exit_code == 0
    wire = json.loads(result.stdout)["hookSpecificOutput"]
    assert wire["permissionDecision"] == "deny"
    assert "Artifact authority denied" in wire["permissionDecisionReason"]
    event = read_authority_events(str(tmp_path), "advisory")[0]
    assert event.origin_surface == "codex_policy_hook"
    assert event.payload["covered_tool"] == "Bash"


def test_codex_denial_journal_failure_keeps_valid_deny_wire(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _managed_marker(tmp_path, monkeypatch, runtime="codex")
    monkeypatch.setattr(
        "forge.cli.hooks.authority.append_authority_event",
        lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
    )

    result = CliRunner().invoke(hooks, ["codex-policy-check"], input=_payload(tmp_path, "Bash"))

    assert result.exit_code == 0
    wire = json.loads(result.stdout)["hookSpecificOutput"]
    assert wire["permissionDecision"] == "deny"
    assert "journal write failed" in result.stderr


def test_named_tools_codex_bash_declines_to_existing_compatibility_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _managed_marker(tmp_path, monkeypatch, runtime="codex", tier="named_tools")

    result = CliRunner().invoke(hooks, ["codex-policy-check"], input=_payload(tmp_path, "Bash"))

    assert result.exit_code == 0
    assert result.stdout == ""
    assert read_authority_events(str(tmp_path), "advisory") == []


def test_absent_marker_keeps_authority_row_a_silent_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _managed_marker(tmp_path, monkeypatch, runtime="claude_code")
    monkeypatch.delenv(AUTHORITY_MARKER_ENV)

    result = CliRunner().invoke(hooks, ["authority-check"], input=_payload(tmp_path, "Write"))

    assert result.exit_code == 0
    assert result.stdout == ""
    assert result.stderr == ""
