"""CLI contracts for ``forge session authority``."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.active import ActiveSessionStore
from forge.session.authority import read_authority_events
from tests.fixtures.session_state import publish_session


def _seed(project: Path, name: str = "worker") -> SessionStore:
    state = create_session_state(name, worktree_path=str(project))
    state.forge_root = str(project)
    publish_session(
        IndexStore(),
        state,
        project,
        forge_root=str(project),
        checkout_root=str(project),
        relative_path=".",
    )
    return SessionStore(str(project), name)


def test_set_show_and_clear_round_trip(runner: CliRunner, temp_env: Path) -> None:
    store = _seed(temp_env)

    set_result = runner.invoke(main, ["session", "authority", "set", "worker", "--role", "advisory"])
    show_result = runner.invoke(main, ["session", "authority", "show", "worker", "--json"])
    clear_result = runner.invoke(main, ["session", "authority", "clear", "worker"])

    assert set_result.exit_code == 0, set_result.output
    assert clear_result.exit_code == 0, clear_result.output
    report = json.loads(show_result.stdout)
    assert report == {
        "session": "worker",
        "role": "advisory",
        "tier": "shell_closed",
        "runtime": "claude_code",
        "active": False,
        "launch_support": "not_running",
        "configuration_history": "supported",
        "configured_epoch": {
            "started_at": report["configured_epoch"]["started_at"],
            "ended_at": None,
        },
        "covered_tools": [
            "Write",
            "Edit",
            "NotebookEdit",
            "apply_patch",
            "Bash",
            "unknown_tools",
        ],
        "read_only_tools": ["Read", "Glob", "Grep", "WebFetch", "WebSearch"],
        "control_tools": [
            "AskUserQuestion",
            "EnterPlanMode",
            "ExitPlanMode",
            "ReportFindings",
            "TaskCreate",
            "TaskGet",
            "TaskList",
            "TaskUpdate",
            "TodoWrite",
        ],
        "observed_denials": {"count": 0, "first_at": None, "last_at": None},
        "limitations": report["limitations"],
    }
    assert len(report["limitations"]) == 5
    assert any("authority abort evidence and active-state cleanup fail" in item for item in report["limitations"])
    assert store.read().intent.authority is None
    assert [event.event_type for event in read_authority_events(str(temp_env), "worker")] == [
        "authority_configured",
        "authority_cleared",
    ]


def test_set_refuses_inside_managed_session_and_journals(runner: CliRunner, temp_env: Path, monkeypatch) -> None:
    _seed(temp_env)
    monkeypatch.setenv("FORGE_SESSION", "caller")

    result = runner.invoke(
        main,
        ["session", "authority", "set", "worker", "--role", "producer"],
    )

    assert result.exit_code == 1
    assert "outside a managed Forge session" in result.output
    event = read_authority_events(str(temp_env), "worker")[0]
    assert event.event_type == "mutation_refused"
    assert event.reason_code == "in_agent_authority_mutation"


def test_set_refuses_active_target_and_journals(runner: CliRunner, temp_env: Path) -> None:
    _seed(temp_env)
    active = ActiveSessionStore()
    active.upsert_session(
        "worker",
        worktree_path=str(temp_env),
        launch_mode="host",
        launcher_pid=os.getpid(),
        forge_root=str(temp_env),
    )
    try:
        result = runner.invoke(
            main,
            ["session", "authority", "set", "worker", "--role", "producer"],
        )
    finally:
        active.clear_session("worker", forge_root=str(temp_env))

    assert result.exit_code == 1
    assert "is active" in result.output
    event = read_authority_events(str(temp_env), "worker")[0]
    assert event.reason_code == "active_session_authority_mutation"


def test_show_unmarked_is_read_only_and_has_stable_nulls(runner: CliRunner, temp_env: Path) -> None:
    store = _seed(temp_env)
    before = store.manifest_path.stat().st_mtime_ns

    result = runner.invoke(main, ["session", "authority", "show", "worker", "--json"])

    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["role"] is None
    assert report["tier"] is None
    assert report["launch_support"] is None
    assert report["configuration_history"] is None
    assert report["configured_epoch"] is None
    assert report["covered_tools"] == []
    assert store.manifest_path.stat().st_mtime_ns == before
    assert not (temp_env / ".forge" / "artifacts" / "worker" / "authority").exists()


def test_producer_rejects_tier_before_manifest_write(runner: CliRunner, temp_env: Path) -> None:
    store = _seed(temp_env)
    before = store.manifest_path.read_bytes()

    result = runner.invoke(
        main,
        [
            "session",
            "authority",
            "set",
            "worker",
            "--role",
            "producer",
            "--tier",
            "shell_closed",
        ],
    )

    assert result.exit_code == 1
    assert "producer" in result.output
    assert store.manifest_path.read_bytes() == before
    assert read_authority_events(str(temp_env), "worker") == []


def test_start_no_launch_persists_explicit_authority_and_event(runner: CliRunner, temp_env: Path) -> None:
    result = runner.invoke(
        main,
        [
            "session",
            "start",
            "planner",
            "--no-launch",
            "--no-proxy",
            "--authority",
            "advisory",
            "--authority-tier",
            "named_tools",
        ],
    )

    assert result.exit_code == 0, result.output
    state = SessionStore(str(temp_env), "planner").read()
    assert state.intent.authority is not None
    assert state.intent.authority.role == "advisory"
    assert state.intent.authority.tier == "named_tools"
    event = read_authority_events(str(temp_env), "planner")[0]
    assert event.event_type == "authority_configured"
    assert event.origin_surface == "external_cli"
    assert event.operation == "start"
    assert event.run_id is None


def test_authority_creation_refuses_inside_agent_before_state_exists(
    runner: CliRunner, temp_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FORGE_SESSION", "caller")

    result = runner.invoke(
        main,
        ["session", "start", "blocked", "--no-launch", "--authority", "producer"],
    )

    assert result.exit_code == 1
    assert "outside a managed session" in result.output
    assert not SessionStore(str(temp_env), "blocked").exists()


def test_in_place_resume_rejects_authority_flags(runner: CliRunner, temp_env: Path) -> None:
    created = runner.invoke(main, ["session", "start", "existing", "--no-launch", "--no-proxy"])
    assert created.exit_code == 0, created.output

    result = runner.invoke(main, ["session", "resume", "existing", "--authority", "producer"])

    assert result.exit_code == 1
    assert "require --fresh" in result.output
    assert SessionStore(str(temp_env), "existing").read().intent.authority is None


def test_adopt_surface_does_not_offer_authority_creation_flags(runner: CliRunner, temp_env: Path) -> None:
    result = runner.invoke(main, ["session", "adopt", "--help"])

    assert result.exit_code == 0
    assert "--authority" not in result.output


@pytest.mark.parametrize(
    "command",
    [
        ["session", "start", "--help"],
        ["session", "incognito", "--help"],
        ["session", "fork", "--help"],
        ["session", "resume", "--help"],
    ],
)
def test_governed_creation_surfaces_offer_authority_flags(
    runner: CliRunner, temp_env: Path, command: list[str]
) -> None:
    result = runner.invoke(main, command)

    assert result.exit_code == 0
    assert "--authority" in result.output
    assert "--authority-tier" in result.output
