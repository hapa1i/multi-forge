"""Reset leaked a dacite error while snapshotting malformed supervisor overrides.

Translate that failure without weakening frozen-lane or native-source identity
checks, and offer a recovery command that works on the persisted configuration.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.consumer_lanes import ensure_consumer_lane_binding
from forge.session.models import (
    LaneRecord,
    NativeSupervisorSource,
    PolicyIntent,
    SupervisorConfig,
)
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "project").resolve()
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (root / ".forge").mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setenv("COLUMNS", "500")
    return root


@pytest.mark.parametrize("reset_args", [["--all"], ["policy.supervisor.timeout_seconds"]])
def test_malformed_supervisor_reset_reports_recovery(project: Path, reset_args: list[str]) -> None:
    state = create_session_state("parent", worktree_path=str(project))
    state.intent.policy = PolicyIntent(supervisor=SupervisorConfig(plan_override_path="/plan", supervisor_model="opus"))
    publish_session(IndexStore(), state, project)
    store = SessionStore(str(project), "parent")
    # Legacy writers could persist a known override path with an invalid value type.
    state.overrides = {"policy": {"supervisor": {"timeout_seconds": "bad"}}}
    store.write(state)
    before = store.manifest_path.read_bytes()
    runner = CliRunner()

    result = runner.invoke(main, ["session", "reset", "--session", "parent", *reset_args])

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit)
    assert "invalid supervisor configuration" in result.stderr
    assert "timeout_seconds" in result.stderr
    assert "forge policy supervisor remove --session parent" in " ".join(result.stderr.split())
    assert store.manifest_path.read_bytes() == before
    removed = runner.invoke(main, ["policy", "supervisor", "remove", "--session", "parent"])
    assert removed.exit_code == 0, removed.output
    updated = store.read()
    assert updated.intent.policy is not None
    assert updated.intent.policy.supervisor is None
    assert updated.overrides == {"policy": {}}


def test_reset_keeps_frozen_supervisor_identity(project: Path) -> None:
    state = create_session_state("parent", worktree_path=str(project))
    state.intent.policy = PolicyIntent(
        supervisor=SupervisorConfig(plan_override_path="/plan", supervisor_model="opus", supervisor_effort="low")
    )
    state.overrides = {"policy": {"supervisor": {"supervisor_effort": "high"}}}
    ensure_consumer_lane_binding(state, SUPERVISOR_CONSUMER, LaneRecord("claude_code", "anthropic-direct", "opus"))
    publish_session(IndexStore(), state, project)
    store = SessionStore(str(project), "parent")
    before = store.manifest_path.read_bytes()

    result = CliRunner().invoke(main, ["session", "reset", "--session", "parent", "--all"])

    assert result.exit_code == 1, result.output
    assert "Frozen supervisor identity requires remove/reconfigure" in result.stderr
    assert store.manifest_path.read_bytes() == before


def test_reset_keeps_native_source_identity(project: Path) -> None:
    state = create_session_state("parent", worktree_path=str(project))
    state.intent.policy = PolicyIntent(supervisor=SupervisorConfig(plan_override_path="/plan", supervisor_model="opus"))
    publish_session(IndexStore(), state, project)
    store = SessionStore(str(project), "parent")
    # A legacy override can name a different source from the baseline supervisor.
    source = NativeSupervisorSource(
        "codex", "01a12b5c-ce1a-72c2-ad3f-05d75f3fba00", "/codex", "/codex/log", "/repo", "a" * 64
    )
    state.overrides = {"policy": {"supervisor": {"native_source": asdict(source)}}}
    store.write(state)
    before = store.manifest_path.read_bytes()

    result = CliRunner().invoke(main, ["session", "reset", "--session", "parent", "--all"])

    assert result.exit_code == 1, result.output
    assert "Native source identity requires remove/reconfigure" in result.stderr
    assert store.manifest_path.read_bytes() == before
