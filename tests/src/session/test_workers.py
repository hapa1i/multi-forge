"""Worker leases preserve deletion admission across detached provider calls."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from dacite import UnexpectedDataError

from forge.session.cleanup_state import cleanup_state_path
from forge.session.exceptions import SessionNotFoundError
from forge.session.index import IndexStore
from forge.session.workers import (
    capture_session_instance,
    find_active_session_workers,
    session_worker_lease,
)
from tests.fixtures.session_state import (
    delete_published_session,
    publish_session_from_fields,
)


def test_worker_lease_exists_only_for_admitted_work(tmp_path: Path) -> None:
    root = tmp_path / "project"
    publish_session_from_fields(IndexStore(), "worker", root, root)
    token = capture_session_instance(root, "worker")

    with session_worker_lease(root, "worker", expected_instance_id=token, label="memory writer"):
        live = find_active_session_workers(root, "worker", token)
        assert len(live) == 1 and "memory writer" in live[0]

    assert find_active_session_workers(root, "worker", token) == ()


def test_detached_admission_cannot_follow_name_reuse(tmp_path: Path) -> None:
    root = tmp_path / "project"
    index = IndexStore()
    publish_session_from_fields(index, "worker", root, root)
    token = capture_session_instance(root, "worker")
    delete_published_session(index, "worker", root)
    publish_session_from_fields(index, "worker", root, root)

    with pytest.raises(SessionNotFoundError):
        with session_worker_lease(root, "worker", expected_instance_id=token, label="old writer"):
            pytest.fail("stale worker was admitted")


def test_worker_admission_does_not_recreate_removed_checkout(tmp_path: Path) -> None:
    root = tmp_path / "project"
    publish_session_from_fields(IndexStore(), "worker", root, root)
    token = capture_session_instance(root, "worker")
    shutil.rmtree(root)

    with pytest.raises(SessionNotFoundError):
        with session_worker_lease(root, "worker", expected_instance_id=token, label="late writer"):
            pytest.fail("late worker was admitted")

    assert not root.exists()


def test_pending_cleanup_refuses_worker_admission(tmp_path: Path) -> None:
    root = tmp_path / "project"
    publish_session_from_fields(IndexStore(), "worker", root, root)
    token = capture_session_instance(root, "worker")
    retry = cleanup_state_path(root, "worker")
    retry.parent.mkdir(parents=True, exist_ok=True)
    retry.write_text("{}")

    with pytest.raises(SessionNotFoundError):
        with session_worker_lease(root, "worker", expected_instance_id=token, label="late writer"):
            pytest.fail("worker crossed cleanup admission")


def test_abandoned_worker_lease_remains_an_explicit_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "project"
    publish_session_from_fields(IndexStore(), "worker", root, root)
    token = capture_session_instance(root, "worker")
    with session_worker_lease(root, "worker", expected_instance_id=token, label="writer"):
        monkeypatch.setattr("forge.session.workers.is_pid_alive", lambda _pid: False)
        refusal = find_active_session_workers(root, "worker", token)
        assert "exited without releasing lease" in refusal[0]
        assert "inspect native subprocesses" in refusal[0]


def test_corrupt_worker_lease_is_not_ignored(tmp_path: Path) -> None:
    root = tmp_path / "project"
    publish_session_from_fields(IndexStore(), "worker", root, root)
    token = capture_session_instance(root, "worker")
    with session_worker_lease(root, "worker", expected_instance_id=token, label="writer"):
        from forge.core.paths import get_forge_home

        lease = next((get_forge_home() / "session-workers" / token).glob("*.json"))
        data = json.loads(lease.read_text())
        data["future"] = True
        lease.write_text(json.dumps(data))
        with pytest.raises(UnexpectedDataError, match="future"):
            find_active_session_workers(root, "worker", token)
