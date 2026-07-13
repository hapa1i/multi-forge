"""Project-compatibility diagnostics on fail-open hook write paths."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from forge.cli.hooks import commands
from forge.cli.hooks._group import hooks
from forge.install.project_compat import diagnose_project_compatibility_for_hook
from forge.policy.semantic.plan_check import PlanCheckVerdict
from forge.session import SessionStore, create_session_state
from forge.session.codex_handoff import observation_receipt_path, stage_pending_context
from forge.session.models import PolicyIntent, SupervisorConfig


def _write_pin(root: Path, state: str) -> None:
    compat_path = root / ".forge" / "project.toml"
    compat_path.parent.mkdir(parents=True, exist_ok=True)
    if state == "incompatible":
        compat_path.write_text('schema_version = 1\nrequired_forge = ">=9999"\n', encoding="utf-8")
    elif state == "malformed":
        compat_path.write_text("not = valid = toml\n", encoding="utf-8")
    elif state == "compatible":
        compat_path.write_text('schema_version = 1\nrequired_forge = ">=0"\n', encoding="utf-8")
    elif state == "unsupported_schema":
        compat_path.write_text('schema_version = 2\nrequired_forge = ">=0"\n', encoding="utf-8")
    elif state == "unreadable":
        compat_path.write_text('schema_version = 1\nrequired_forge = ">=0"\n', encoding="utf-8")
    else:
        raise ValueError(f"unknown compatibility fixture: {state}")


def _compat_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if "Project compatibility degraded for hook" in record.message]


def _make_session(root: Path, monkeypatch: pytest.MonkeyPatch, *, name: str = "session") -> SessionStore:
    monkeypatch.chdir(root)
    monkeypatch.setenv("HOME", str(root / "home"))
    monkeypatch.setenv("FORGE_SESSION", name)
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(root))
    store = SessionStore(str(root), name)
    manifest = create_session_state(name, worktree_path=str(root))
    manifest.forge_root = str(root)
    store.write(manifest)
    return store


@pytest.mark.parametrize("state", ["incompatible", "malformed"])
def test_lenient_diagnostic_degrades_once_and_proceeds(
    state: str,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _write_pin(tmp_path, state)

    with caplog.at_level(logging.DEBUG, logger="forge.install.project_compat"):
        results = diagnose_project_compatibility_for_hook(tmp_path, operation="test-hook")

    assert len(results) == 1
    assert results[0].compatible is True
    assert results[0].state == state
    assert results[0].degraded
    assert len(_compat_records(caplog)) == 1


@pytest.mark.parametrize("state", ["missing", "compatible"])
def test_lenient_diagnostic_is_silent_when_not_degraded(
    state: str,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    if state == "compatible":
        _write_pin(tmp_path, state)

    with caplog.at_level(logging.DEBUG, logger="forge.install.project_compat"):
        results = diagnose_project_compatibility_for_hook(tmp_path, operation="test-hook")

    assert len(results) == 1
    assert results[0].state == state
    assert results[0].degraded is None
    assert _compat_records(caplog) == []


@pytest.mark.parametrize("state", ["incompatible", "malformed", "unsupported_schema", "unreadable"])
def test_session_start_rollover_preserves_wire_and_emits_one_diagnostic_for_all_refusal_states(
    state: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _make_session(tmp_path, monkeypatch)
    previous_transcript = tmp_path / "previous.jsonl"
    previous_transcript.write_text('{"type":"assistant"}\n', encoding="utf-8")
    current = store.read()
    current.confirmed.claude_session_id = "old-uuid"
    current.confirmed.transcript_path = str(previous_transcript)
    store.write(current)
    _write_pin(tmp_path, state)
    if state == "unreadable":
        compat_path = tmp_path / ".forge" / "project.toml"
        real_open = Path.open

        def _open(path: Path, *args: Any, **kwargs: Any) -> Any:
            if path == compat_path:
                raise PermissionError("denied")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", _open)

    payload = json.dumps(
        {
            "session_id": "new-uuid",
            "transcript_path": str(tmp_path / "current.jsonl"),
            "source": "compact",
        }
    )
    with caplog.at_level(logging.DEBUG, logger="forge.install.project_compat"):
        result = CliRunner().invoke(
            hooks,
            ["session-start", "--cwd", str(tmp_path)],
            input=payload,
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["success"] is True
    assert store.read().confirmed.claude_session_id == "new-uuid"
    assert len(_compat_records(caplog)) == 1


@pytest.mark.parametrize(
    ("command", "payload", "operation"),
    [
        (
            "plan-write",
            {
                "hook_event_name": "PostToolUse",
                "tool_input": {"file_path": ".claude/plans/plan.md"},
            },
            "plan-write",
        ),
        ("exit-plan-mode", {"hook_event_name": "PreToolUse"}, "exit-plan-mode"),
        (
            "stop",
            {
                "hook_event_name": "Stop",
                "session_id": "uuid",
                "transcript_path": "transcript.jsonl",
            },
            "stop",
        ),
        (
            "stop-failure",
            {
                "hook_event_name": "StopFailure",
                "session_id": "uuid",
                "transcript_path": "transcript.jsonl",
            },
            "stop-failure",
        ),
        (
            "pre-compact",
            {"session_id": "uuid", "transcript_path": "transcript.jsonl"},
            "pre-compact",
        ),
        ("post-compact", {"session_id": "uuid", "trigger": "manual"}, "post-compact"),
        (
            "subagent-stop",
            {"session_id": "uuid", "agent_id": "agent", "agent_type": "Explore"},
            "subagent-stop",
        ),
    ],
)
def test_lifecycle_write_hooks_call_the_invocation_diagnostic_once(
    command: str,
    payload: dict[str, Any],
    operation: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _make_session(tmp_path, monkeypatch)
    plan = tmp_path / ".claude" / "plans" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text('{"type":"assistant"}\n', encoding="utf-8")
    manifest = store.read()
    manifest.confirmed.latest_plan_path = ".claude/plans/plan.md"
    manifest.confirmed.claude_session_id = "uuid"
    manifest.confirmed.transcript_path = str(transcript)
    store.write(manifest)

    payload = dict(payload)
    if command in {"pre-compact", "post-compact", "subagent-stop"}:
        payload["cwd"] = str(tmp_path)
    if "transcript_path" in payload:
        payload["transcript_path"] = str(transcript)

    diagnostic = MagicMock()
    monkeypatch.setattr(commands, "diagnose_project_compatibility_for_hook", diagnostic)
    monkeypatch.setattr(commands, "enqueue_stop_marker", lambda **_kwargs: None)
    monkeypatch.setattr(commands, "enqueue_index_marker", lambda **_kwargs: None)
    monkeypatch.setattr(commands, "enqueue_handoff_marker", lambda **_kwargs: None)
    monkeypatch.setattr(commands, "enqueue_shadow_marker", lambda **_kwargs: None)
    monkeypatch.setattr(commands, "_copy_transcript_to_pending_runs", lambda *_args, **_kwargs: None)

    result = CliRunner().invoke(hooks, [command], input=json.dumps(payload), catch_exceptions=False)

    assert result.exit_code == 0
    diagnostic.assert_called_once_with(store.forge_root, operation=operation)


@pytest.mark.parametrize(
    ("command", "handler_name"),
    [
        ("teammate-idle", "handle_teammate_idle"),
        ("task-completed", "handle_task_completed"),
    ],
)
def test_team_hooks_call_the_invocation_diagnostic_once(
    command: str,
    handler_name: str,
    tmp_path: Path,
) -> None:
    store = SessionStore(str(tmp_path), "session")
    store.write(create_session_state("session"))
    effective = MagicMock()
    effective.policy.team_supervisor.enabled = True
    diagnostic = MagicMock()

    with (
        patch("forge.cli.hooks.commands.resolve_session_store", return_value=store),
        patch("forge.cli.hooks.commands.compute_effective_intent", return_value=effective),
        patch(
            "forge.cli.hooks.commands.diagnose_project_compatibility_for_hook",
            diagnostic,
        ),
        patch("forge.cli.hooks.commands._run_team_handler", lambda _key, fn: fn({})),
        patch(f"forge.policy.team.handlers.{handler_name}", return_value=(0, "")),
    ):
        result = CliRunner().invoke(
            hooks,
            [command],
            input=json.dumps({"session_id": "uuid"}),
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    diagnostic.assert_called_once_with(store.forge_root, operation=command)


def test_policy_hook_aggregates_store_and_shadow_roots_in_one_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    shadow_root = tmp_path / "supervisor-project"
    shadow_root.mkdir()
    store = _make_session(project_root, monkeypatch)
    plan = shadow_root / "plan.md"
    plan.write_text("# Approved plan\n", encoding="utf-8")
    manifest = store.read()
    manifest.intent.policy = PolicyIntent(
        enabled=True,
        supervisor=SupervisorConfig(
            resume_id="planner",
            direct=True,
            forge_root=str(shadow_root),
            cascade=True,
            plan_override_path=str(plan),
            shadow_sample_rate=1.0,
        ),
    )
    store.write(manifest)
    _write_pin(project_root, "incompatible")
    _write_pin(shadow_root, "malformed")
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": "docs/note.md", "content": "note"},
            "session_id": "uuid",
        }
    )

    with (
        patch(
            "forge.policy.semantic.plan_check.run_plan_check",
            return_value=PlanCheckVerdict(aligned=True, reason="aligned"),
        ),
        caplog.at_level(logging.DEBUG, logger="forge.install.project_compat"),
    ):
        result = CliRunner().invoke(hooks, ["policy-check"], input=payload, catch_exceptions=False)

    assert result.exit_code == 0
    records = _compat_records(caplog)
    assert len(records) == 1
    assert str(project_root / ".forge" / "project.toml") in records[0].message
    assert str(shadow_root / ".forge" / "project.toml") in records[0].message
    assert list((shadow_root / ".forge" / "artifacts" / "session" / "shadow").glob("*.json"))


@pytest.mark.parametrize("state", ["incompatible", "malformed"])
@pytest.mark.parametrize("staged", [False, True])
def test_codex_session_start_keeps_wire_and_stderr_unchanged(
    state: str,
    staged: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _make_session(tmp_path, monkeypatch, name="codex-session")
    _write_pin(tmp_path, state)
    body = "# Handoff\n"
    if staged:
        stage_pending_context(store.session_dir, body)
    payload = json.dumps(
        {
            "hook_event_name": "SessionStart",
            "session_id": "thread-uuid",
            "cwd": str(tmp_path),
            "source": "startup",
            "transcript_path": "/tmp/rollout.jsonl",
        }
    )

    with caplog.at_level(logging.DEBUG, logger="forge.install.project_compat"):
        result = CliRunner().invoke(hooks, ["codex-session-start"], input=payload, catch_exceptions=False)

    assert result.exit_code == 0
    assert result.stderr == ""
    if staged:
        wire = json.loads(result.stdout)
        assert wire["hookSpecificOutput"]["additionalContext"] == body
    else:
        assert result.stdout == ""
        assert observation_receipt_path(store.session_dir).is_file()
    assert len(_compat_records(caplog)) == 1


def test_codex_policy_allow_remains_silent_while_diagnostic_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _make_session(tmp_path, monkeypatch, name="codex-session")
    manifest = store.read()
    manifest.intent.policy = PolicyIntent(enabled=True, bundles=["tdd"])
    store.write(manifest)
    _write_pin(tmp_path, "incompatible")
    patch_command = "*** Begin Patch\n*** Add File: tests/test_x.py\n+def test_x(): pass\n*** End Patch"
    payload = json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": patch_command},
            "cwd": str(tmp_path),
            "session_id": "thread-uuid",
        }
    )

    with caplog.at_level(logging.DEBUG, logger="forge.install.project_compat"):
        result = CliRunner().invoke(hooks, ["codex-policy-check"], input=payload, catch_exceptions=False)

    assert result.exit_code == 0
    assert result.stdout == ""
    assert "Project compatibility" not in result.stderr
    assert "checked apply_patch:tests/test_x.py" in result.stderr
    assert len(_compat_records(caplog)) == 1
