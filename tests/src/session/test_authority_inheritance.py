"""Authority inheritance across shared and concrete derivation seams."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

import forge.session.authority as authority_module
import forge.session.manager as manager_module
from forge.core.state import FileLockTimeoutError
from forge.session.authority import read_authority_events
from forge.session.manager import SessionManager, _inherit_intent_fields
from forge.session.models import AuthorityIntent, SessionState, create_session_state
from forge.session.store import SessionStore
from tests.fixtures.session_state import publish_session


@pytest.mark.parametrize(
    ("parent_authority", "expected"),
    [
        (
            AuthorityIntent("advisory", "named_tools"),
            AuthorityIntent("advisory", "named_tools"),
        ),
        (AuthorityIntent("producer"), None),
        (None, None),
    ],
)
def test_shared_derivation_inherits_only_advisory(
    parent_authority: AuthorityIntent | None, expected: AuthorityIntent | None
) -> None:
    parent = create_session_state("parent", authority=parent_authority)
    child = create_session_state("child")

    _inherit_intent_fields(child, parent)

    assert child.intent.authority == expected
    if expected is not None and parent_authority is not None:
        assert child.intent.authority is not parent_authority


def test_codex_child_inherits_advisory_and_explicit_producer_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    (project / ".git").mkdir(parents=True)
    (project / ".forge").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    monkeypatch.chdir(project)
    manager = SessionManager()
    manager.start_session(
        "planner",
        worktree_path=str(project),
        authority=AuthorityIntent("advisory", "named_tools"),
        authority_explicit=True,
    )

    inherited = manager.start_session(
        "codex-child",
        worktree_path=str(project),
        runtime="codex",
        parent_session="planner",
    )
    explicit = manager.start_session(
        "producer-child",
        worktree_path=str(project),
        runtime="codex",
        parent_session="planner",
        authority=AuthorityIntent("producer"),
        authority_explicit=True,
    )

    assert inherited.intent.authority == AuthorityIntent("advisory", "named_tools")
    inherited_event = read_authority_events(str(project), "codex-child")[0]
    assert inherited_event.event_type == "authority_inherited"
    assert inherited_event.origin_surface == "session_derivation"
    assert inherited_event.runtime == "codex"
    assert explicit.intent.authority == AuthorityIntent("producer")
    explicit_event = read_authority_events(str(project), "producer-child")[0]
    assert explicit_event.event_type == "authority_configured"
    assert explicit_event.origin_surface == "external_cli"


@pytest.mark.parametrize("operation", ["fork", "fresh", "relaunch"])
def test_derivation_inherits_advisory_but_not_producer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    (project / ".git").mkdir(parents=True)
    (project / ".forge").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    monkeypatch.chdir(project)
    manager = SessionManager()
    for role in ("advisory", "producer"):
        parent = create_session_state(
            f"{role}-parent",
            worktree_path=str(project),
            authority=AuthorityIntent(role),
        )
        publish_session(manager.index_store, parent, project)

    def derive(parent_name: str, child_name: str) -> SessionState:
        if operation == "fork":
            return manager.fork_session(parent_name, child_name)[1]
        if operation == "fresh":
            return manager.resume_session(parent_name, child_name=child_name, resume_mode="native")[0]
        return manager.relaunch_session(parent_name, child_name=child_name)[1]

    advisory_child = derive("advisory-parent", "advisory-child")
    producer_child = derive("producer-parent", "producer-child")

    assert advisory_child.intent.authority == AuthorityIntent("advisory")
    assert read_authority_events(str(project), "advisory-child")[0].event_type == "authority_inherited"
    assert producer_child.intent.authority is None
    assert read_authority_events(str(project), "producer-child") == []
    assert SessionStore(str(project), "advisory-child").read().intent.authority == AuthorityIntent("advisory")
    assert SessionStore(str(project), "producer-child").read().intent.authority is None


@pytest.mark.parametrize("operation", ["fork", "fresh"])
def test_explicit_child_authority_wins_over_inherited_advisory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    project = tmp_path / "project"
    (project / ".forge").mkdir(parents=True)
    monkeypatch.chdir(project)
    manager = SessionManager()
    parent = create_session_state("parent", worktree_path=str(project), authority=AuthorityIntent("advisory"))
    publish_session(manager.index_store, parent, project)
    parent_store = SessionStore(str(project), "parent")
    before = parent_store.manifest_path.read_bytes()

    if operation == "fork":
        manager.fork_session(
            "parent",
            "child",
            authority=AuthorityIntent("producer"),
            authority_explicit=True,
        )
    else:
        manager.resume_session(
            "parent",
            child_name="child",
            resume_mode="native",
            authority=AuthorityIntent("producer"),
            authority_explicit=True,
        )

    assert SessionStore(str(project), "child").read().intent.authority == AuthorityIntent("producer")
    assert read_authority_events(str(project), "child")[0].event_type == "authority_configured"
    assert parent_store.manifest_path.read_bytes() == before


def test_creation_journal_failure_rolls_back_manifest_and_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    (project / ".git").mkdir(parents=True)
    (project / ".forge").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        manager_module,
        "_append_created_authority_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    manager = SessionManager()

    with pytest.raises(OSError, match="disk full"):
        manager.start_session(
            "rolled-back",
            worktree_path=str(project),
            authority=AuthorityIntent("producer"),
            authority_explicit=True,
        )

    assert not (project / ".forge" / "sessions" / "rolled-back").exists()
    assert manager.index_store.live_session_exists("rolled-back", forge_root=str(project)) is False


def test_marked_creation_holds_launch_lock_through_first_journal_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    (project / ".git").mkdir(parents=True)
    (project / ".forge").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    monkeypatch.chdir(project)
    monkeypatch.setattr(authority_module, "AUTHORITY_CONTROL_LOCK_TIMEOUT_S", 0.05)

    append_reached = threading.Event()
    allow_append = threading.Event()
    errors: list[BaseException] = []
    original_append = manager_module._append_created_authority_event

    def blocked_append(
        state: SessionState,
        store: SessionStore,
        *,
        operation: str,
        explicit: bool,
        lock_held: bool = False,
    ) -> None:
        append_reached.set()
        if not allow_append.wait(timeout=5):
            raise TimeoutError("test did not release authority append")
        original_append(
            state,
            store,
            operation=operation,
            explicit=explicit,
            lock_held=lock_held,
        )

    monkeypatch.setattr(manager_module, "_append_created_authority_event", blocked_append)
    manager = SessionManager()

    def create() -> None:
        try:
            manager.start_session(
                "serialized",
                worktree_path=str(project),
                authority=AuthorityIntent("producer"),
                authority_explicit=True,
            )
        except BaseException as exc:
            errors.append(exc)

    creator = threading.Thread(target=create)
    creator.start()
    assert append_reached.wait(timeout=5)

    store = SessionStore(str(project), "serialized")
    assert store.exists()
    with pytest.raises(FileLockTimeoutError):
        with authority_module.authority_session_lock(store.session_dir):
            pytest.fail("published session became launchable before its first event")

    allow_append.set()
    creator.join(timeout=5)
    assert not creator.is_alive()
    assert errors == []
    assert [event.event_type for event in read_authority_events(str(project), "serialized")] == ["authority_configured"]
