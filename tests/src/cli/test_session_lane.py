"""Tests for `forge session lane` (consumer-lane placement CLI, epic consumer_lanes T6a)."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from pytest import fixture

from forge.cli.main import main
from forge.core.state import now_iso
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.models import (
    ConsumerLaneBinding,
    ConsumerLaneConfirmed,
    ConsumerLaneIntent,
    LaneRecord,
)

# memory_writer's two valid lanes: the default + the claude-max subscription lane.
_DEFAULT = LaneRecord("claude_code", "anthropic-direct", "opus")
_CLAUDE_MAX = LaneRecord("claude_code", "claude-max", "opus")


@fixture
def runner() -> CliRunner:
    return CliRunner()


@fixture
def project(tmp_path: Path, monkeypatch) -> Path:
    """A cwd with .git/.forge and an ambient 'worker' session (via $FORGE_SESSION)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    proj = tmp_path / "project"
    (proj / ".git").mkdir(parents=True)
    (proj / ".forge").mkdir(parents=True)
    monkeypatch.chdir(proj)
    monkeypatch.setenv("FORGE_SESSION", "worker")
    return proj


def _seed(
    project: Path,
    *,
    intent: ConsumerLaneIntent | None = None,
    confirmed: ConsumerLaneConfirmed | None = None,
) -> SessionStore:
    manifest = create_session_state("worker", worktree_path=str(project))
    manifest.forge_root = str(project)
    if intent is not None:
        manifest.intent.consumer_lanes = intent
    if confirmed is not None:
        manifest.confirmed.consumer_lanes = confirmed
    store = SessionStore(str(project), "worker")
    store.write(manifest)
    # resolve_session (FORGE_SESSION path) looks the session up in the index, so register it
    # the way `forge session start` would -- a cwd-only manifest is invisible to get_session_store.
    IndexStore().add_session(
        name="worker",
        worktree_path=str(project),
        project_root=str(project),
        forge_root=str(project),
        checkout_root=str(project),
        relative_path=".",
    )
    return store


def _seed_degrade(store: SessionStore) -> None:
    """Seed a sticky codex degrade marker (the T7 supervisor overlay) into the manifest."""
    from forge.policy.supervisor_lane_degrade import set_supervisor_degrade

    codex = LaneRecord("codex", "chatgpt", "gpt-5-codex")
    store.update(
        timeout_s=5.0,
        mutate=lambda m: set_supervisor_degrade(
            m, from_lane=codex, to_lane=None, reason="subscription_exhausted", at=now_iso()
        ),
    )


def test_set_writes_intent_slot(runner: CliRunner, project: Path) -> None:
    store = _seed(project)
    result = runner.invoke(main, ["session", "lane", "set", "--consumer", "memory_writer", "--backend", "claude-max"])
    assert result.exit_code == 0, result.output
    lanes = store.read().intent.consumer_lanes
    assert lanes is not None
    assert lanes.memory_writer == _CLAUDE_MAX


def test_set_accepts_hyphenated_consumer(runner: CliRunner, project: Path) -> None:
    """`--consumer memory-writer` (hyphen) normalizes to the underscore id."""
    store = _seed(project)
    result = runner.invoke(main, ["session", "lane", "set", "--consumer", "memory-writer", "--backend", "claude-max"])
    assert result.exit_code == 0, result.output
    lanes = store.read().intent.consumer_lanes
    assert lanes is not None
    assert lanes.memory_writer == _CLAUDE_MAX


def test_set_supervisor_via_general_surface(runner: CliRunner, project: Path) -> None:
    """The supervisor is reachable through the general surface too (same intent slot)."""
    store = _seed(project)
    result = runner.invoke(main, ["session", "lane", "set", "--consumer", "supervisor", "--backend", "claude-max"])
    assert result.exit_code == 0, result.output
    lanes = store.read().intent.consumer_lanes
    assert lanes is not None
    assert lanes.supervisor == _CLAUDE_MAX


def test_set_shadow_curation_via_codex_runtime(runner: CliRunner, project: Path) -> None:
    """T6b: `--consumer shadow_curation --runtime codex` resolves to the codex lane (was LaneError)."""
    store = _seed(project)
    result = runner.invoke(main, ["session", "lane", "set", "--consumer", "shadow_curation", "--runtime", "codex"])
    assert result.exit_code == 0, result.output
    lanes = store.read().intent.consumer_lanes
    assert lanes is not None
    assert lanes.shadow_curation == LaneRecord("codex", "chatgpt", "gpt-5-codex")


def test_set_memory_writer_via_codex_runtime(runner: CliRunner, project: Path) -> None:
    """T6c: `--consumer memory_writer --runtime codex` resolves to the codex lane (was LaneError)."""
    store = _seed(project)
    result = runner.invoke(main, ["session", "lane", "set", "--consumer", "memory_writer", "--runtime", "codex"])
    assert result.exit_code == 0, result.output
    lanes = store.read().intent.consumer_lanes
    assert lanes is not None
    assert lanes.memory_writer == LaneRecord("codex", "chatgpt", "gpt-5-codex")


def test_set_unknown_consumer_rejects(runner: CliRunner, project: Path) -> None:
    _seed(project)
    result = runner.invoke(main, ["session", "lane", "set", "--consumer", "bogus", "--backend", "claude-max"])
    assert result.exit_code != 0
    assert "Unknown consumer" in result.output


def test_set_requires_a_constraint(runner: CliRunner, project: Path) -> None:
    _seed(project)
    result = runner.invoke(main, ["session", "lane", "set", "--consumer", "memory_writer"])
    assert result.exit_code != 0


def test_set_invalid_backend_rejects(runner: CliRunner, project: Path) -> None:
    _seed(project)
    result = runner.invoke(main, ["session", "lane", "set", "--consumer", "memory_writer", "--backend", "nope"])
    assert result.exit_code != 0


def test_set_rejects_change_to_a_frozen_lane(runner: CliRunner, project: Path) -> None:
    """Once a different lane is frozen in confirmed, `set` must reject the change (immutability)."""
    store = _seed(
        project,
        confirmed=ConsumerLaneConfirmed(
            memory_writer=ConsumerLaneBinding(lane=_DEFAULT, source="intent", resolved_at=now_iso())
        ),
    )
    result = runner.invoke(main, ["session", "lane", "set", "--consumer", "memory_writer", "--backend", "claude-max"])
    assert result.exit_code != 0
    assert "frozen" in result.output.lower()
    # The frozen binding is untouched and no drifting intent was written.
    state = store.read()
    confirmed = state.confirmed.consumer_lanes
    assert confirmed is not None and confirmed.memory_writer is not None
    assert confirmed.memory_writer.lane == _DEFAULT
    assert state.intent.consumer_lanes is None or state.intent.consumer_lanes.memory_writer is None


def test_show_json_reflects_requested_and_frozen(runner: CliRunner, project: Path) -> None:
    _seed(
        project,
        intent=ConsumerLaneIntent(memory_writer=_CLAUDE_MAX),
        confirmed=ConsumerLaneConfirmed(
            shadow_curation=ConsumerLaneBinding(lane=_DEFAULT, source="intent", resolved_at=now_iso())
        ),
    )
    result = runner.invoke(main, ["session", "lane", "show", "--json"])
    assert result.exit_code == 0, result.output
    by_id = {row["consumer"]: row for row in json.loads(result.output)["consumers"]}
    assert by_id["memory_writer"]["requested"] == {"runtime": "claude_code", "backend": "claude-max", "model": "opus"}
    assert by_id["shadow_curation"]["frozen"] == {
        "runtime": "claude_code",
        "backend": "anthropic-direct",
        "model": "opus",
    }


def test_show_json_flags_supervisor_degraded(runner: CliRunner, project: Path) -> None:
    """T7: `lane show --json` marks the supervisor row degraded (its frozen codex lane is routed to
    the default this session) while leaving the frozen binding itself untouched; other consumers are
    never flagged (supervisor-only overlay)."""
    store = _seed(
        project,
        confirmed=ConsumerLaneConfirmed(
            supervisor=ConsumerLaneBinding(
                lane=LaneRecord("codex", "chatgpt", "gpt-5-codex"), source="intent", resolved_at=now_iso()
            )
        ),
    )
    _seed_degrade(store)

    result = runner.invoke(main, ["session", "lane", "show", "--json"])
    assert result.exit_code == 0, result.output
    by_id = {row["consumer"]: row for row in json.loads(result.output)["consumers"]}
    assert by_id["supervisor"]["degraded"] is True
    assert by_id["memory_writer"]["degraded"] is False  # supervisor-only overlay
    # Degrade routes around the binding, never rewrites it: frozen is still codex.
    assert by_id["supervisor"]["frozen"] == {"runtime": "codex", "backend": "chatgpt", "model": "gpt-5-codex"}


def test_clear_removes_intent_only_preserving_frozen(runner: CliRunner, project: Path) -> None:
    """`clear` drops the intent request but leaves an already-frozen confirmed binding."""
    store = _seed(
        project,
        intent=ConsumerLaneIntent(memory_writer=_CLAUDE_MAX),
        confirmed=ConsumerLaneConfirmed(
            memory_writer=ConsumerLaneBinding(lane=_CLAUDE_MAX, source="intent", resolved_at=now_iso())
        ),
    )
    result = runner.invoke(main, ["session", "lane", "clear", "--consumer", "memory_writer"])
    assert result.exit_code == 0, result.output
    state = store.read()
    intent = state.intent.consumer_lanes
    confirmed = state.confirmed.consumer_lanes
    assert intent is not None and confirmed is not None and confirmed.memory_writer is not None
    assert intent.memory_writer is None
    assert confirmed.memory_writer.lane == _CLAUDE_MAX


def test_supervisor_set_clears_degrade(runner: CliRunner, project: Path) -> None:
    """T7 reset map: re-pinning the supervisor lane ('topped up, retry codex') clears the sticky degrade."""
    from forge.policy.supervisor_lane_degrade import is_supervisor_degraded

    store = _seed(project)
    _seed_degrade(store)
    assert is_supervisor_degraded(store.read()) is True  # precondition

    result = runner.invoke(main, ["session", "lane", "set", "--consumer", "supervisor", "--backend", "claude-max"])
    assert result.exit_code == 0, result.output
    assert is_supervisor_degraded(store.read()) is False


def test_set_non_supervisor_consumer_leaves_degrade(runner: CliRunner, project: Path) -> None:
    """The degrade overlay is supervisor-only: setting another consumer's lane must not clear it."""
    from forge.policy.supervisor_lane_degrade import is_supervisor_degraded

    store = _seed(project)
    _seed_degrade(store)

    result = runner.invoke(main, ["session", "lane", "set", "--consumer", "memory_writer", "--backend", "claude-max"])
    assert result.exit_code == 0, result.output
    assert is_supervisor_degraded(store.read()) is True


def test_supervisor_clear_lane_leaves_degrade(runner: CliRunner, project: Path) -> None:
    """D3 asymmetry: 'lane clear' drops the intent request but is NOT a 'retry codex' signal,
    so the sticky degrade survives (only remove/re-pin reset it)."""
    from forge.policy.supervisor_lane_degrade import is_supervisor_degraded

    store = _seed(project, intent=ConsumerLaneIntent(supervisor=_CLAUDE_MAX))
    _seed_degrade(store)

    result = runner.invoke(main, ["session", "lane", "clear", "--consumer", "supervisor"])
    assert result.exit_code == 0, result.output
    assert is_supervisor_degraded(store.read()) is True


def test_no_session_exits_with_error(runner: CliRunner, tmp_path: Path, monkeypatch) -> None:
    """With no --session and no $FORGE_SESSION, the command fails actionably (not a crash)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    result = runner.invoke(main, ["session", "lane", "show"])
    assert result.exit_code != 0
