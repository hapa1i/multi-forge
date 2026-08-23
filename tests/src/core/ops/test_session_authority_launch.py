"""Tests for marked authority launch preflight and lifecycle transactions."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import forge.core.ops.session_authority_launch as launch
import forge.core.ops.session_routing as routing_ops
from forge.core.models.direct_model import resolve_direct_model_pin
from forge.core.ops.claude_session import launch_claude_session
from forge.core.ops.codex_enrollment import CodexEnrollmentVerification
from forge.core.ops.session import ForgeOpError
from forge.core.reactive.env import RunIdentity, new_root_run_identity
from forge.install.codex_hooks import get_builtin_codex_entries, render_codex_block
from forge.install.hooks import ForgeHookRegistration
from forge.session.active import ActiveSessionStore
from forge.session.authority import (
    authority_hook_contract_sha256,
    read_authority_events,
)
from forge.session.events import SessionEvent
from forge.session.models import AuthorityIntent, create_session_state
from forge.session.routing import derive_routing_history, read_routing_events
from forge.session.store import SessionStore


def _store(tmp_path: Path, *, role: str | None = "producer", runtime: str = "claude_code") -> SessionStore:
    store = SessionStore(str(tmp_path), "planner")
    store.write(
        create_session_state(
            "planner",
            worktree_path=str(tmp_path),
            runtime=runtime,
            authority=AuthorityIntent(role) if role is not None else None,
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


def test_pre_invocation_abort_skips_run_ended_and_clears_active(tmp_path: Path) -> None:
    store = _store(tmp_path)
    active = _active_store(tmp_path)

    with pytest.raises(ForgeOpError, match="projection failed"):
        with launch.authority_launch_transaction(
            store=store,
            root=new_root_run_identity(),
            operation="start",
            launch_mode="host",
            worktree_path=tmp_path,
            active_store=active,
        ) as attempt:
            assert attempt is not None
            attempt.abort_before_child(reason_code="route_projection_failed")
            raise ForgeOpError("projection failed")

    assert active.peek_session("planner", forge_root=str(tmp_path)) is None
    events = read_authority_events(str(tmp_path), "planner")
    assert [event.event_type for event in events] == [
        "launch_preflight",
        "run_started",
        "launch_aborted",
    ]


def test_pre_invocation_abort_reports_authority_and_active_cleanup_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    active = _active_store(tmp_path)
    original_append = launch.append_authority_event

    def fail_abort(root: str, event: SessionEvent) -> None:
        if getattr(event, "event_type", None) == "launch_aborted":
            raise OSError("abort disk full")
        original_append(root, event)

    monkeypatch.setattr(launch, "append_authority_event", fail_abort)
    monkeypatch.setattr(
        active,
        "clear_session",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("locked")),
    )

    with pytest.raises(ForgeOpError) as raised:
        with launch.authority_launch_transaction(
            store=store,
            root=new_root_run_identity(),
            operation="start",
            launch_mode="host",
            worktree_path=tmp_path,
            active_store=active,
        ) as attempt:
            assert attempt is not None
            try:
                attempt.abort_before_child(reason_code="route_projection_failed")
            except OSError as exc:
                raise ForgeOpError(f"projection failed; authority abort failed: {exc}") from exc

    assert "authority abort failed: abort disk full" in str(raised.value)
    assert "active-state cleanup also failed: locked" in str(raised.value)
    assert "run_ended" not in [event.event_type for event in read_authority_events(str(tmp_path), "planner")]


def test_route_preparation_failure_writes_no_routing_history_or_invokes_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    active = _active_store(tmp_path)
    invoked = False
    monkeypatch.setattr(
        routing_ops,
        "load_model_practices",
        lambda: (_ for _ in ()).throw(ValueError("catalog invalid")),
    )

    with pytest.raises(ValueError, match="catalog invalid"):
        with launch.authority_launch_transaction(
            store=store,
            root=new_root_run_identity(),
            operation="start",
            launch_mode="host",
            worktree_path=tmp_path,
            active_store=active,
        ):
            state = store.read()
            routing_ops.build_claude_routing_payload(
                state,
                effective_template=None,
                runtime_base_url=None,
                proxy_id=None,
                applied_direct_model=resolve_direct_model_pin("claude-opus-5"),
            )
            invoked = True

    assert invoked is False
    assert active.peek_session("planner", forge_root=str(tmp_path)) is None
    assert not (tmp_path / ".forge" / "artifacts" / "planner" / "routing").exists()
    authority = read_authority_events(str(tmp_path), "planner")
    assert [event.event_type for event in authority] == [
        "launch_preflight",
        "run_started",
        "run_ended",
    ]
    assert authority[-1].reason_code == "launcher_exception"


def test_invalid_proxy_backend_is_actionable_before_routing_or_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    active = _active_store(tmp_path)
    invoked = False
    monkeypatch.setattr(
        routing_ops,
        "load_config",
        lambda **_kwargs: (_ for _ in ()).throw(
            ValueError(
                "Invalid proxy.backend: 'OpenRouter' (must start with a lowercase letter or digit and contain only "
                "lowercase letters, digits, '.', '_', or '-')"
            )
        ),
    )

    with pytest.raises(
        ForgeOpError,
        match=r"proxy\.yaml for proxy 'edited-proxy' is invalid: Invalid proxy\.backend: 'OpenRouter'",
    ):
        with launch.authority_launch_transaction(
            store=store,
            root=new_root_run_identity(),
            operation="start",
            launch_mode="host",
            worktree_path=tmp_path,
            active_store=active,
        ):
            state = store.read()
            routing_ops.build_claude_routing_payload(
                state,
                effective_template="openrouter-anthropic",
                runtime_base_url="http://localhost:8085",
                proxy_id="edited-proxy",
            )
            invoked = True

    assert invoked is False
    assert active.peek_session("planner", forge_root=str(tmp_path)) is None
    assert not (tmp_path / ".forge" / "artifacts" / "planner" / "routing").exists()


def test_routing_append_failure_compensates_marked_transaction_without_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    active = _active_store(tmp_path)
    root = new_root_run_identity()
    invoked = False
    monkeypatch.setattr(
        routing_ops,
        "append_routing_event",
        lambda *_args: (_ for _ in ()).throw(OSError("routing disk full")),
    )

    with pytest.raises(ForgeOpError, match="required routing commit append failed"):
        with launch.authority_launch_transaction(
            store=store,
            root=root,
            operation="start",
            launch_mode="host",
            worktree_path=tmp_path,
            active_store=active,
        ) as attempt:
            routing_ops.commit_launch_routing(
                store=store,
                state=store.read(),
                root=root,
                operation="start",
                payload=routing_ops.build_claude_routing_payload(
                    store.read(),
                    effective_template=None,
                    runtime_base_url=None,
                    proxy_id=None,
                    applied_direct_model=resolve_direct_model_pin("claude-opus-5"),
                ),
                authority_attempt=attempt,
            )
            invoked = True

    assert invoked is False
    assert active.peek_session("planner", forge_root=str(tmp_path)) is None
    authority = read_authority_events(str(tmp_path), "planner")
    assert [event.event_type for event in authority] == [
        "launch_preflight",
        "run_started",
        "launch_aborted",
    ]
    assert authority[-1].reason_code == "routing_commit_failed"
    assert {event.run_id for event in authority} == {root.run_id}
    assert not (tmp_path / ".forge" / "artifacts" / "planner" / "routing").exists()


def test_projection_failure_compensates_routing_then_authority_without_run_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    active = _active_store(tmp_path)
    root = new_root_run_identity()
    routing_types: list[str] = []
    real_append = routing_ops.append_routing_event

    def record_append(forge_root: str | Path, event: SessionEvent) -> Path:
        routing_types.append(event.event_type)
        return real_append(forge_root, event)

    monkeypatch.setattr(routing_ops, "append_routing_event", record_append)
    monkeypatch.setattr(
        store,
        "update",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("manifest read-only")),
    )

    with pytest.raises(ForgeOpError, match="route projection failed"):
        with launch.authority_launch_transaction(
            store=store,
            root=root,
            operation="resume",
            launch_mode="host",
            worktree_path=tmp_path,
            active_store=active,
        ) as attempt:
            state = store.read()
            routing_ops.commit_launch_routing(
                store=store,
                state=state,
                root=root,
                operation="resume",
                payload=routing_ops.build_claude_routing_payload(
                    state,
                    effective_template=None,
                    runtime_base_url=None,
                    proxy_id=None,
                    applied_direct_model=resolve_direct_model_pin("claude-sonnet-5"),
                ),
                authority_attempt=attempt,
            )

    assert routing_types == ["launch_routing_committed", "launch_aborted"]
    routing = read_routing_events(tmp_path, store.read())
    assert routing[0].payload == routing[1].payload
    assert {event.run_id for event in routing} == {root.run_id}
    authority = read_authority_events(str(tmp_path), "planner")
    assert [event.event_type for event in authority] == [
        "launch_preflight",
        "run_started",
        "launch_aborted",
    ]
    assert authority[-1].reason_code == "route_projection_failed"
    assert active.peek_session("planner", forge_root=str(tmp_path)) is None


def test_routing_validation_failure_compensates_authority_without_run_ended(tmp_path: Path) -> None:
    store = _store(tmp_path)
    active = _active_store(tmp_path)
    root = new_root_run_identity()
    state = store.read()
    payload = routing_ops.build_claude_routing_payload(
        state,
        effective_template=None,
        runtime_base_url=None,
        proxy_id=None,
        applied_direct_model=resolve_direct_model_pin("claude-opus-5"),
    )
    payload["selected_model"] = "claude-sonnet-5"

    with pytest.raises(ForgeOpError, match="routing commit validation failed"):
        with launch.authority_launch_transaction(
            store=store,
            root=root,
            operation="start",
            launch_mode="host",
            worktree_path=tmp_path,
            active_store=active,
        ) as attempt:
            routing_ops.commit_launch_routing(
                store=store,
                state=state,
                root=root,
                operation="start",
                payload=payload,
                authority_attempt=attempt,
            )

    assert active.peek_session("planner", forge_root=str(tmp_path)) is None
    authority = read_authority_events(str(tmp_path), "planner")
    assert [event.event_type for event in authority] == [
        "launch_preflight",
        "run_started",
        "launch_aborted",
    ]
    assert authority[-1].reason_code == "routing_commit_failed"
    assert not (tmp_path / ".forge" / "artifacts" / "planner" / "routing").exists()


def test_projection_compensation_failures_are_aggregated_and_child_is_suppressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    active = _active_store(tmp_path)
    root = new_root_run_identity()
    invoked = False
    real_route_append = routing_ops.append_routing_event
    real_authority_append = launch.append_authority_event

    def fail_route_abort(forge_root: str | Path, event: SessionEvent) -> Path:
        if event.event_type == "launch_aborted":
            raise OSError("routing compensation disk full")
        return real_route_append(forge_root, event)

    def fail_authority_abort(forge_root: str, event: SessionEvent) -> None:
        if event.event_type == "launch_aborted":
            raise OSError("authority compensation disk full")
        real_authority_append(forge_root, event)

    monkeypatch.setattr(routing_ops, "append_routing_event", fail_route_abort)
    monkeypatch.setattr(launch, "append_authority_event", fail_authority_abort)
    monkeypatch.setattr(
        store,
        "update",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("manifest read-only")),
    )

    with pytest.raises(ForgeOpError) as raised:
        with launch.authority_launch_transaction(
            store=store,
            root=root,
            operation="resume",
            launch_mode="host",
            worktree_path=tmp_path,
            active_store=active,
        ) as attempt:
            state = store.read()
            routing_ops.commit_launch_routing(
                store=store,
                state=state,
                root=root,
                operation="resume",
                payload=routing_ops.build_claude_routing_payload(
                    state,
                    effective_template=None,
                    runtime_base_url=None,
                    proxy_id=None,
                    applied_direct_model=resolve_direct_model_pin("claude-opus-5"),
                ),
                authority_attempt=attempt,
            )
            invoked = True

    message = str(raised.value)
    assert "route projection failed: manifest read-only" in message
    assert "routing abort failed: routing compensation disk full" in message
    assert "authority abort failed: authority compensation disk full" in message
    assert invoked is False
    assert active.peek_session("planner", forge_root=str(tmp_path)) is None
    history = derive_routing_history(tmp_path, store.read())
    assert history.status == "unproven"
    assert [event.event_type for event in read_authority_events(str(tmp_path), "planner")] == [
        "launch_preflight",
        "run_started",
    ]


def test_spawn_failure_after_projection_retains_route_with_same_root_run_id(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    active = _active_store(tmp_path)
    root = new_root_run_identity()

    with pytest.raises(FileNotFoundError, match="missing child"):
        with launch.authority_launch_transaction(
            store=store,
            root=root,
            operation="start",
            launch_mode="host",
            worktree_path=tmp_path,
            active_store=active,
        ) as attempt:
            state = store.read()
            routing_ops.commit_launch_routing(
                store=store,
                state=state,
                root=root,
                operation="start",
                payload=routing_ops.build_claude_routing_payload(
                    state,
                    effective_template=None,
                    runtime_base_url=None,
                    proxy_id=None,
                    applied_direct_model=resolve_direct_model_pin("claude-opus-5"),
                ),
                authority_attempt=attempt,
            )
            raise FileNotFoundError("missing child")

    state = store.read()
    routing = read_routing_events(tmp_path, state)
    authority = read_authority_events(str(tmp_path), "planner")
    assert derive_routing_history(tmp_path, state).status == "supported"
    assert state.confirmed.route_commit is not None
    assert state.confirmed.route_commit.run_id == root.run_id
    assert {event.run_id for event in [*routing, *authority]} == {root.run_id}
    assert authority[-1].event_type == "run_ended"
    assert authority[-1].reason_code == "child_never_spawned"


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


def test_post_child_oserror_is_not_reported_as_never_spawned(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(OSError, match="post-child"):
        with launch.authority_launch_transaction(
            store=store,
            root=new_root_run_identity(),
            operation="start",
            launch_mode="host",
            worktree_path=tmp_path,
            active_store=_active_store(tmp_path),
        ) as attempt:
            assert attempt is not None
            attempt.complete(0)
            raise OSError("post-child bookkeeping")

    ended = read_authority_events(str(tmp_path), "planner")[-1]
    assert ended.reason_code == "launcher_exception_after_child"


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
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text(render_codex_block(get_builtin_codex_entries()), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
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


def test_codex_advisory_rejects_missing_policy_row_before_empirical_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    session_start = tuple(entry for entry in get_builtin_codex_entries() if entry.event == "SessionStart")
    (codex_home / "config.toml").write_text(render_codex_block(session_start), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(
        "forge.core.ops.codex_enrollment.verify_codex_enrollment",
        lambda **_kwargs: pytest.fail("the empirical probe must not run when the policy row is absent"),
    )

    with pytest.raises(launch.AuthoritySeamPreflightError, match="codex-policy-check") as error:
        launch._preflight_authority_seam(
            AuthorityIntent("advisory"),
            runtime="codex",
            launch_mode="host",
            worktree_path=tmp_path,
            codex_preflight=None,
        )

    assert error.value.reason_code == "codex_policy_registration_invalid"


def test_unmarked_launch_holds_authority_lock_without_using_active_registry(
    tmp_path: Path,
) -> None:
    import forge.core.ops.session_authority as control

    store = _store(tmp_path, role=None)
    errors: list[Exception] = []

    with launch.authority_launch_transaction(
        store=store,
        root=new_root_run_identity(),
        operation="start",
        launch_mode="host",
        worktree_path=tmp_path,
        active_store=cast(
            ActiveSessionStore,
            SimpleNamespace(
                get_session=lambda *_args, **_kwargs: pytest.fail("unmarked preflight must not require active state"),
                upsert_session=lambda *_args, **_kwargs: pytest.fail(
                    "unmarked preflight must not register active state"
                ),
            ),
        ),
    ) as attempt:
        assert attempt is None

        def mutate() -> None:
            try:
                with control._authority_mutation_lock(store, operation="set"):
                    pytest.fail("a concurrent authority mutation acquired the launch lock")
            except Exception as exc:  # capture the worker outcome for the main test thread
                errors.append(exc)

        worker = threading.Thread(target=mutate)
        worker.start()
        worker.join(timeout=2)
        assert not worker.is_alive()

    assert len(errors) == 1
    assert isinstance(errors[0], ForgeOpError)
    assert "launching or active" in str(errors[0])
    assert store.read().intent.authority is None
    refused = read_authority_events(str(tmp_path), "planner")
    assert len(refused) == 1
    assert refused[0].event_type == "mutation_refused"
    assert refused[0].reason_code == "active_session_authority_mutation"


def test_concurrent_unmarked_launch_has_actionable_lock_contention_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, role=None)
    active = _active_store(tmp_path)
    monkeypatch.setattr(launch, "AUTHORITY_LAUNCH_LOCK_TIMEOUT_S", 0.01)

    with launch.authority_launch_transaction(
        store=store,
        root=new_root_run_identity(),
        operation="start",
        launch_mode="host",
        worktree_path=tmp_path,
        active_store=active,
    ):
        with pytest.raises(ForgeOpError, match="another launch or authority change in progress"):
            with launch.authority_launch_transaction(
                store=store,
                root=new_root_run_identity(),
                operation="resume",
                launch_mode="host",
                worktree_path=tmp_path,
                active_store=active,
            ):
                pytest.fail("a concurrent unmarked launch acquired the authority lock")


def test_unmarked_launch_wraps_lock_open_failure_as_actionable_command_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, role=None)

    class UnopenableLock:
        def __enter__(self) -> None:
            raise OSError("permission denied")

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(launch, "authority_session_lock", lambda *_args, **_kwargs: UnopenableLock())

    with pytest.raises(
        ForgeOpError,
        match="could not coordinate launch.*authority lock.*permission denied",
    ):
        with launch.authority_launch_transaction(
            store=store,
            root=new_root_run_identity(),
            operation="start",
            launch_mode="host",
            worktree_path=tmp_path,
        ):
            pytest.fail("launch continued without its authority lock")


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
