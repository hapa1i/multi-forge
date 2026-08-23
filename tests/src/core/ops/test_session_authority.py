"""Core authority mutation rollback and posture derivation tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import forge.core.ops.session_authority as ops
import forge.core.ops.session_authority_launch as launch
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import ForgeOpError
from forge.core.reactive.env import new_root_run_identity
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.active import ActiveSessionStore
from forge.session.authority import (
    append_authority_event,
    authority_config_sha256,
    authority_hook_contract_sha256,
    new_authority_event,
    read_authority_events,
)
from forge.session.events import SessionEvent, SessionEventValidationError
from forge.session.models import AuthorityIntent, LaunchIntent
from tests.fixtures.session_state import publish_session


@pytest.fixture
def temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    (project / ".git").mkdir(parents=True)
    (project / ".forge").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    monkeypatch.chdir(project)
    return project


def _seed(project: Path, *, sidecar: bool = False, journal_config: bool = True) -> SessionStore:
    state = create_session_state(
        "planner",
        worktree_path=str(project),
        authority=AuthorityIntent("advisory"),
    )
    state.forge_root = str(project)
    if sidecar:
        state.intent.launch = LaunchIntent(mode="sidecar")
    publish_session(
        IndexStore(),
        state,
        project,
        forge_root=str(project),
        checkout_root=str(project),
        relative_path=".",
    )
    store = SessionStore(str(project), "planner")
    if journal_config:
        append_authority_event(
            str(project),
            new_authority_event(
                state,
                event_type="authority_configured",
                run_id=None,
                origin_surface="external_cli",
                operation="set",
                outcome="success",
            ),
        )
    return store


def test_required_mutation_append_failure_rolls_manifest_back(temp_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _seed(temp_env, journal_config=False)
    original = store.manifest_path.read_bytes()
    monkeypatch.setattr(
        ops,
        "append_authority_event",
        lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(ops.ForgeOpError, match="manifest was rolled back"):
        ops.set_session_authority(
            ctx=ExecutionContext.from_cwd(),
            session_name="planner",
            role="producer",
            tier=None,
        )

    assert store.manifest_path.read_bytes() == original


def test_required_mutation_event_construction_failure_rolls_manifest_back(
    temp_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _seed(temp_env, journal_config=False)
    original = store.manifest_path.read_bytes()
    monkeypatch.setattr(
        ops,
        "new_authority_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("invalid event")),
    )

    with pytest.raises(ops.ForgeOpError, match="manifest was rolled back"):
        ops.set_session_authority(
            ctx=ExecutionContext.from_cwd(),
            session_name="planner",
            role="producer",
            tier=None,
        )

    assert store.manifest_path.read_bytes() == original


def test_launch_support_precedence_unsupported_then_not_running(temp_env: Path) -> None:
    _seed(temp_env, sidecar=True)
    report = ops.get_session_authority_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    )
    assert report.launch_support == "unsupported"
    assert report.active is False


def test_marked_missing_history_is_unproven(temp_env: Path) -> None:
    _seed(temp_env, journal_config=False)

    report = ops.get_session_authority_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    )

    assert report.configuration_history == "unproven"
    assert report.launch_support == "not_running"


def test_unmarked_manifest_with_dangling_config_history_is_unproven(
    temp_env: Path,
) -> None:
    store = _seed(temp_env)
    store.update(
        timeout_s=5.0,
        mutate=lambda state: setattr(state.intent, "authority", None),
    )

    report = ops.get_session_authority_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    )

    assert report.role is None
    assert report.configuration_history == "unproven"
    assert report.configured_epoch is not None
    assert report.configured_epoch["ended_at"] is None


def test_clear_establishes_supported_unmarked_history_without_prior_designation(
    temp_env: Path,
) -> None:
    store = _seed(temp_env, journal_config=False)
    state = store.update(
        timeout_s=5.0,
        mutate=lambda current: setattr(current.intent, "authority", None),
    )
    append_authority_event(
        str(temp_env),
        new_authority_event(
            state,
            event_type="authority_cleared",
            run_id=None,
            origin_surface="external_cli",
            operation="clear",
            outcome="success",
            authority=None,
        ),
    )

    report = ops.get_session_authority_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    )

    assert report.configuration_history == "supported"
    assert report.configured_epoch is None


def test_live_matching_preflight_is_verified_and_show_is_read_only(
    temp_env: Path,
) -> None:
    store = _seed(temp_env)
    state = store.read()
    authority = state.intent.authority
    assert authority is not None
    root = new_root_run_identity()
    config_digest = authority_config_sha256(authority, "claude_code")
    hook_digest = authority_hook_contract_sha256("claude_code")
    for event_type in ("launch_preflight", "run_started"):
        append_authority_event(
            str(temp_env),
            new_authority_event(
                state,
                event_type=event_type,
                run_id=root.run_id,
                origin_surface="launcher",
                operation="resume",
                outcome="success",
                config_sha256=config_digest,
                hook_registration_sha256=hook_digest,
            ),
        )
    active = ActiveSessionStore()
    active.upsert_session(
        "planner",
        worktree_path=str(temp_env),
        launch_mode="host",
        launcher_pid=os.getpid(),
        forge_root=str(temp_env),
        authority_run_id=root.run_id,
        authority_config_sha256=config_digest,
        authority_hook_registration_sha256=hook_digest,
    )
    tracked = [store.manifest_path, active.index_path]
    journal = temp_env / ".forge" / "artifacts" / "planner" / "authority" / "events.jsonl"
    tracked.append(journal)
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tracked}
    try:
        report = ops.get_session_authority_report(
            ctx=ExecutionContext.from_cwd(),
            session_name="planner",
        )
        assert report.launch_support == "verified"
        for path, snapshot in before.items():
            assert (path.read_bytes(), path.stat().st_mtime_ns) == snapshot
    finally:
        active.clear_session("planner", forge_root=str(temp_env))


def test_matching_launch_abort_supersedes_visible_run_started(temp_env: Path) -> None:
    store = _seed(temp_env)
    state = store.read()
    authority = state.intent.authority
    assert authority is not None
    root = new_root_run_identity()
    config_digest = authority_config_sha256(authority, "claude_code")
    hook_digest = authority_hook_contract_sha256("claude_code")
    for event_type, outcome, reason in (
        ("launch_preflight", "success", None),
        ("run_started", "success", None),
        ("launch_aborted", "error", "route_projection_failed"),
    ):
        append_authority_event(
            str(temp_env),
            new_authority_event(
                state,
                event_type=event_type,
                run_id=root.run_id,
                origin_surface="launcher",
                operation="resume",
                outcome=outcome,
                reason_code=reason,
                config_sha256=config_digest,
                hook_registration_sha256=hook_digest,
            ),
        )
    active = ActiveSessionStore()
    active.upsert_session(
        "planner",
        worktree_path=str(temp_env),
        launch_mode="host",
        launcher_pid=os.getpid(),
        forge_root=str(temp_env),
        authority_run_id=root.run_id,
        authority_config_sha256=config_digest,
        authority_hook_registration_sha256=hook_digest,
    )
    try:
        report = ops.get_session_authority_report(
            ctx=ExecutionContext.from_cwd(),
            session_name="planner",
        )
        assert report.launch_support == "aborted"
    finally:
        active.clear_session("planner", forge_root=str(temp_env))


def test_late_run_started_append_failure_is_reported_as_aborted(
    temp_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _seed(temp_env)
    active = ActiveSessionStore()
    real_append = launch.append_authority_event

    monkeypatch.setattr(
        launch,
        "_preflight_authority_seam",
        lambda *_args, **_kwargs: authority_hook_contract_sha256("claude_code"),
    )

    def land_then_fail(root: str, event: SessionEvent) -> None:
        real_append(root, event)
        if getattr(event, "event_type", None) == "run_started":
            raise OSError("append acknowledgement lost")

    monkeypatch.setattr(launch, "append_authority_event", land_then_fail)
    monkeypatch.setattr(
        active,
        "clear_session",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("active registry locked")),
    )

    with pytest.raises(ForgeOpError, match="active registry locked"):
        with launch.authority_launch_transaction(
            store=store,
            root=new_root_run_identity(),
            operation="resume",
            launch_mode="host",
            worktree_path=temp_env,
            active_store=active,
        ):
            pytest.fail("the failed run_started append must not enter the child boundary")

    report = ops.get_session_authority_report(
        ctx=ExecutionContext.from_cwd(),
        session_name="planner",
    )
    assert report.active is True
    assert report.launch_support == "aborted"
    assert [event.event_type for event in read_authority_events(str(temp_env), "planner")][-3:] == [
        "launch_preflight",
        "run_started",
        "launch_aborted",
    ]
    ActiveSessionStore().clear_session("planner", forge_root=str(temp_env))


def test_malformed_active_registry_is_an_actionable_read_only_error(
    temp_env: Path,
) -> None:
    _seed(temp_env)
    active_path = ActiveSessionStore().index_path
    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_text('{"version":', encoding="utf-8")
    before = (active_path.read_bytes(), active_path.stat().st_mtime_ns)

    with pytest.raises(ForgeOpError, match="active-session registry.*forge session list"):
        ops.get_session_authority_report(
            ctx=ExecutionContext.from_cwd(),
            session_name="planner",
        )

    assert (active_path.read_bytes(), active_path.stat().st_mtime_ns) == before


def test_unrepresentable_active_pid_is_an_actionable_read_only_error(temp_env: Path) -> None:
    _seed(temp_env)
    active = ActiveSessionStore()
    active.upsert_session(
        "planner",
        worktree_path=str(temp_env),
        launch_mode="host",
        launcher_pid=os.getpid(),
        forge_root=str(temp_env),
    )
    data = json.loads(active.index_path.read_text())
    next(iter(data["sessions"].values()))["launcher_pid"] = 10**100
    active.index_path.write_text(json.dumps(data), encoding="utf-8")
    before = (active.index_path.read_bytes(), active.index_path.stat().st_mtime_ns)

    with pytest.raises(ForgeOpError, match="active-session registry.*forge session list"):
        ops.get_session_authority_report(
            ctx=ExecutionContext.from_cwd(),
            session_name="planner",
        )

    assert (active.index_path.read_bytes(), active.index_path.stat().st_mtime_ns) == before


def test_malformed_history_is_a_read_error(temp_env: Path) -> None:
    _seed(temp_env)
    journal = temp_env / ".forge" / "artifacts" / "planner" / "authority" / "events.jsonl"
    with journal.open("a", encoding="utf-8") as stream:
        stream.write("not-json\n")

    with pytest.raises(SessionEventValidationError, match="record 2"):
        ops.get_session_authority_report(
            ctx=ExecutionContext.from_cwd(),
            session_name="planner",
        )


def test_authority_mutation_wraps_lock_open_failure_as_command_error(
    temp_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _seed(temp_env)

    class UnopenableLock:
        def __enter__(self) -> None:
            raise OSError("permission denied")

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(ops, "authority_session_lock", lambda *_args, **_kwargs: UnopenableLock())

    with pytest.raises(
        ForgeOpError,
        match="could not change authority.*authority lock.*permission denied",
    ):
        with ops._authority_mutation_lock(store, operation="set"):
            pytest.fail("authority mutation continued without its authority lock")
