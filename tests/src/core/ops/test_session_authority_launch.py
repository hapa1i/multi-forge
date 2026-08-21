"""Tests for marked authority launch preflight and lifecycle transactions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import forge.core.ops.session_authority_launch as launch
from forge.core.ops.claude_session import launch_claude_session
from forge.core.ops.codex_enrollment import CodexEnrollmentVerification
from forge.core.ops.session import ForgeOpError
from forge.core.reactive.env import RunIdentity, new_root_run_identity
from forge.install.hooks import ForgeHookRegistration
from forge.session.active import ActiveSessionStore
from forge.session.authority import (
    authority_hook_contract_sha256,
    read_authority_events,
)
from forge.session.models import AuthorityIntent, create_session_state
from forge.session.store import SessionStore


def _store(tmp_path: Path, *, role: str = "producer", runtime: str = "claude_code") -> SessionStore:
    store = SessionStore(str(tmp_path), "planner")
    store.write(
        create_session_state(
            "planner",
            worktree_path=str(tmp_path),
            runtime=runtime,
            authority=AuthorityIntent(role),
        )
    )
    return store


def _active_store(tmp_path: Path) -> ActiveSessionStore:
    return ActiveSessionStore(tmp_path / "active" / "active.json")


def test_marked_launch_commits_preflight_and_start_before_runner(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    active = _active_store(tmp_path)
    root = new_root_run_identity()

    with launch.authority_launch_transaction(
        store=store,
        root=root,
        operation="start",
        launch_mode="host",
        worktree_path=tmp_path,
        active_store=active,
    ) as attempt:
        assert attempt is not None
        entry = active.peek_session("planner", forge_root=str(tmp_path))
        assert entry is not None
        assert entry.authority_run_id == root.run_id
        assert [event.event_type for event in read_authority_events(str(tmp_path), "planner")] == [
            "launch_preflight",
            "run_started",
        ]
        attempt.complete(0)

    assert active.peek_session("planner", forge_root=str(tmp_path)) is None
    events = read_authority_events(str(tmp_path), "planner")
    assert [event.event_type for event in events] == [
        "launch_preflight",
        "run_started",
        "run_ended",
    ]
    assert {event.run_id for event in events} == {root.run_id}
    assert events[-1].outcome == "success"
    assert events[-1].reason_code is None


def test_spawn_failure_is_distinct_from_nonzero_exit(tmp_path: Path) -> None:
    spawn_store = _store(tmp_path / "spawn")
    (tmp_path / "spawn").mkdir(exist_ok=True)
    # Re-write after creating the root because the strict journal resolver requires it.
    spawn_store.write(
        create_session_state(
            "planner",
            worktree_path=str(tmp_path / "spawn"),
            authority=AuthorityIntent("producer"),
        )
    )
    with pytest.raises(FileNotFoundError):
        with launch.authority_launch_transaction(
            store=spawn_store,
            root=new_root_run_identity(),
            operation="start",
            launch_mode="host",
            worktree_path=tmp_path / "spawn",
            active_store=_active_store(tmp_path / "spawn"),
        ):
            raise FileNotFoundError("missing launcher")
    spawn_end = read_authority_events(str(tmp_path / "spawn"), "planner")[-1]
    assert spawn_end.reason_code == "child_never_spawned"

    nonzero_root = tmp_path / "nonzero"
    nonzero_root.mkdir()
    nonzero_store = _store(nonzero_root)
    with launch.authority_launch_transaction(
        store=nonzero_store,
        root=new_root_run_identity(),
        operation="resume",
        launch_mode="host",
        worktree_path=nonzero_root,
        active_store=_active_store(nonzero_root),
    ) as attempt:
        assert attempt is not None
        attempt.complete(7)
    nonzero_end = read_authority_events(str(nonzero_root), "planner")[-1]
    assert nonzero_end.reason_code == "child_exited_nonzero"


def test_advisory_sidecar_refuses_without_started_claim(tmp_path: Path) -> None:
    store = _store(tmp_path, role="advisory")

    with pytest.raises(ForgeOpError, match="unsupported"):
        with launch.authority_launch_transaction(
            store=store,
            root=new_root_run_identity(),
            operation="start",
            launch_mode="sidecar",
            worktree_path=tmp_path,
            active_store=_active_store(tmp_path),
        ):
            pytest.fail("unsupported launch must not enter the transaction")

    events = read_authority_events(str(tmp_path), "planner")
    assert [event.event_type for event in events] == [
        "launch_preflight",
        "launch_aborted",
    ]
    assert all(event.reason_code == "advisory_sidecar_unsupported" for event in events)


def test_marker_failure_happens_before_active_registration_or_started_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, role="advisory")
    active = _active_store(tmp_path)
    monkeypatch.setattr(
        launch,
        "_preflight_authority_seam",
        lambda *_args, **_kwargs: authority_hook_contract_sha256("claude_code"),
    )
    monkeypatch.setattr(
        launch,
        "build_authority_marker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad marker")),
    )

    with pytest.raises(ForgeOpError, match="construct.*marker"):
        with launch.authority_launch_transaction(
            store=store,
            root=new_root_run_identity(),
            operation="start",
            launch_mode="host",
            worktree_path=tmp_path,
            active_store=active,
        ):
            pytest.fail("marker failure must not enter the launch transaction")

    assert active.peek_session("planner", forge_root=str(tmp_path)) is None
    events = read_authority_events(str(tmp_path), "planner")
    assert [event.event_type for event in events] == [
        "launch_preflight",
        "launch_aborted",
    ]
    assert all(event.reason_code == "authority_marker_invalid" for event in events)


def test_claude_advisory_requires_exact_registration_and_current_executable_dispatcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = launch.render_dispatcher_command("authority-check")
    dispatcher = tmp_path / "forge-hook"
    dispatcher.write_text("#!/bin/sh\n")
    dispatcher.chmod(0o700)
    monkeypatch.setattr(
        launch,
        "find_forge_hook_registrations",
        lambda *_args: [
            ForgeHookRegistration(
                scope="user",
                settings_path=tmp_path / "settings.json",
                event="PreToolUse",
                handler="authority-check",
                command=command,
                matcher=None,
                timeout=60,
            )
        ],
    )
    monkeypatch.setattr(
        launch,
        "diagnose_hook_dispatcher",
        lambda: SimpleNamespace(status="current", path=str(dispatcher)),
    )

    digest = launch._preflight_authority_seam(
        AuthorityIntent("advisory"),
        runtime="claude_code",
        launch_mode="host",
        worktree_path=tmp_path,
        codex_preflight=None,
    )
    assert digest == authority_hook_contract_sha256("claude_code")

    monkeypatch.setattr(
        launch,
        "find_forge_hook_registrations",
        lambda *_args: [
            ForgeHookRegistration(
                scope="user",
                settings_path=tmp_path / "settings.json",
                event="PreToolUse",
                handler="authority-check",
                command=command,
                matcher="Write",
                timeout=60,
            )
        ],
    )
    with pytest.raises(ForgeOpError, match="exactly one catch-all"):
        launch._preflight_authority_seam(
            AuthorityIntent("advisory"),
            runtime="claude_code",
            launch_mode="host",
            worktree_path=tmp_path,
            codex_preflight=None,
        )


def test_codex_advisory_verifies_enrollment_on_every_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path, role="advisory", runtime="codex")
    calls = 0

    def verified(**_kwargs):
        nonlocal calls
        calls += 1
        return CodexEnrollmentVerification(
            ready=True,
            registered=True,
            config_path="/codex/config.toml",
            attempted=True,
            codex_succeeded=True,
            enrolled=True,
            reason="verified",
            version="0.139.0",
            version_validated="0.139.0",
        )

    monkeypatch.setattr("forge.core.ops.codex_enrollment.verify_codex_enrollment", verified)
    active = _active_store(tmp_path)
    markers: list[str] = []
    for _ in range(2):
        with launch.authority_launch_transaction(
            store=store,
            root=new_root_run_identity(),
            operation="resume",
            launch_mode="host",
            worktree_path=tmp_path,
            active_store=active,
        ) as attempt:
            assert attempt is not None and attempt.marker is not None
            markers.append(attempt.marker)
            attempt.complete(0)

    assert calls == 2
    assert markers[0] != markers[1]


def test_claude_launcher_reuses_preflight_root_in_marker_and_invoker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    (project / ".git").mkdir(parents=True)
    (project / ".forge").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)
    state = create_session_state(
        "planner",
        worktree_path=str(project),
        authority=AuthorityIntent("advisory"),
    )
    state.forge_root = str(project)
    SessionStore(str(project), "planner").write(state)
    digest = authority_hook_contract_sha256("claude_code")
    monkeypatch.setattr(launch, "_preflight_authority_seam", lambda *_args, **_kwargs: digest)
    observed: dict[str, object] = {}

    def invoke(**kwargs: object) -> int:
        import json

        marker = json.loads(kwargs["env_vars"]["FORGE_AUTHORITY_MARKER"])  # type: ignore[index]
        identity = kwargs["run_identity"]
        observed["marker_run_id"] = marker["run_id"]
        observed["identity"] = identity
        return 0

    result = launch_claude_session(
        manifest=state,
        session_id="claude-session-id",
        resume_id=None,
        effective_template=None,
        runtime_base_url=None,
        context_limit=200_000,
        use_sidecar=False,
        invoke=invoke,
        run_active=lambda **_kwargs: pytest.fail("marked launch owns active registration"),
        authority_operation="start",
    )

    identity = observed["identity"]
    assert isinstance(identity, RunIdentity)
    assert result.exit_code == 0
    assert observed["marker_run_id"] == identity.run_id
    assert identity.run_id == identity.root_run_id
    events = read_authority_events(str(project), "planner")
    assert [event.event_type for event in events] == [
        "launch_preflight",
        "run_started",
        "run_ended",
    ]
    assert {event.run_id for event in events} == {identity.run_id}
