"""Sidecar hooks borrow exact host admission without a container-local index."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from forge.core.workqueue import enqueue_shadow_marker
from forge.session.exceptions import ForgeSessionError, SessionNotFoundError
from forge.session.index import IndexStore
from forge.session.manager import SessionManager
from forge.session.workers import (
    SESSION_INSTANCE_ENV,
    SIDECAR_LEASE_ENV,
    _sidecar_exit_confirmed,
    capture_session_instance,
    find_active_session_workers,
    session_worker_lease,
    sidecar_session_lease,
)
from tests.fixtures.session_state import publish_session_from_fields


def _delegate(monkeypatch: pytest.MonkeyPatch, host: Path, local: Path, token: str, lease: Path) -> None:
    shutil.copytree(host / ".forge", local / ".forge")
    monkeypatch.setenv("FORGE_SIDECAR", "1")
    monkeypatch.setenv("FORGE_SESSION", "worker")
    monkeypatch.setenv("FORGE_FORGE_ROOT", str(local))
    monkeypatch.setenv("FORGE_SIDECAR_HOST_FORGE_ROOT", str(host))
    monkeypatch.setenv(SESSION_INSTANCE_ENV, token)
    monkeypatch.setenv(SIDECAR_LEASE_ENV, str(lease))
    monkeypatch.setattr("forge.session.workers.SIDECAR_LEASE_MOUNT", str(lease.parent))
    # No index exists in the container; neither capture nor persistence may consult it.
    monkeypatch.setattr("forge.session.workers.IndexStore", Mock(side_effect=AssertionError("container index access")))
    monkeypatch.setattr("forge.session.workers.is_pid_alive", Mock(side_effect=AssertionError("container pid probe")))


def test_sidecar_delegation_preserves_queue_host_paths_without_local_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host, local = tmp_path / "host", tmp_path / "mounted"
    entry = publish_session_from_fields(IndexStore(), "worker", host, host)
    token = entry.instance_id
    assert token is not None
    monkeypatch.setattr("forge.session.workers._sidecar_exit_confirmed", lambda _name: True)

    with sidecar_session_lease(host, "worker", expected_instance_id=token) as lease:
        with monkeypatch.context() as container:
            _delegate(container, host, local, token, lease)
            assert capture_session_instance(local, "worker") == token
            with session_worker_lease(local, "worker", expected_instance_id=token, label="Stop hook"):
                marker = enqueue_shadow_marker(
                    session_id="uuid",
                    session_name="worker",
                    worktree_path=host,
                    forge_root=str(host),
                    admission_forge_root=str(local),
                    expected_instance_id=token,
                )
            assert marker is not None
            assert json.loads(marker.read_text())["payload"]["forge_root"] == str(host)
        assert lease.exists()

    assert not lease.exists()


@pytest.mark.parametrize(
    "mismatch",
    ["missing", "token", "name", "root", "label", "manifest_root", "manifest_name", "manifest_owner", "no_env", "path"],
)
def test_sidecar_delegation_refuses_unbound_or_replaced_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    host, local = tmp_path / "host", tmp_path / "mounted"
    entry = publish_session_from_fields(IndexStore(), "worker", host, host)
    token = entry.instance_id
    assert token is not None
    monkeypatch.setattr("forge.session.workers._sidecar_exit_confirmed", lambda _name: True)
    with sidecar_session_lease(host, "worker", expected_instance_id=token) as lease:
        with monkeypatch.context() as container:
            _delegate(container, host, local, token, lease)
            if mismatch == "missing":
                lease.unlink()
            elif mismatch == "no_env":
                container.delenv(SIDECAR_LEASE_ENV)
            elif mismatch == "path":
                container.setattr("forge.session.workers.SIDECAR_LEASE_MOUNT", str(tmp_path / "other"))
            elif mismatch.startswith("manifest_"):
                manifest = local / ".forge/sessions/worker/forge.session.json"
                if mismatch == "manifest_owner":
                    container.setattr("forge.session.store.SessionStore.review_identity", lambda _self: "0" * 32)
                else:
                    data = json.loads(manifest.read_text())
                    data["forge_root" if mismatch == "manifest_root" else "name"] = "other"
                    manifest.write_text(json.dumps(data))
            else:
                data = json.loads(lease.read_text())
                data[
                    {"token": "instance_id", "name": "session_name", "root": "forge_root", "label": "label"}[mismatch]
                ] = ("0" * 32 if mismatch == "token" else "other")
                lease.write_text(json.dumps(data))
            with pytest.raises(SessionNotFoundError):
                with session_worker_lease(local, "worker", expected_instance_id=token, label="late Stop"):
                    pytest.fail("unowned sidecar producer admitted")


def test_host_cleanup_refuses_delegated_sidecar_lease(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    host = tmp_path / "host"
    index = IndexStore()
    entry = publish_session_from_fields(index, "worker", host, host)
    token = entry.instance_id
    assert token is not None
    monkeypatch.setattr("forge.session.workers._sidecar_exit_confirmed", lambda _name: True)
    with sidecar_session_lease(host, "worker", expected_instance_id=token):
        with pytest.raises(ForgeSessionError, match="Session workers are still running"):
            SessionManager(index_store=index).delete_session("worker", forge_root=str(host))
        assert index.peek_session("worker", str(host)) is not None


@pytest.mark.parametrize("interrupt", [False, True])
def test_uncertain_sidecar_exit_retains_host_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt: bool
) -> None:
    host = tmp_path / "host"
    entry = publish_session_from_fields(IndexStore(), "worker", host, host)
    token = entry.instance_id
    assert token is not None
    monkeypatch.setattr("forge.session.workers._sidecar_exit_confirmed", lambda _name: False)
    try:
        with sidecar_session_lease(host, "worker", expected_instance_id=token):
            if interrupt:
                raise KeyboardInterrupt
    except KeyboardInterrupt:
        pass
    assert len(find_active_session_workers(host, "worker", token)) == 1


@pytest.mark.parametrize(
    ("returncode", "states", "expected"),
    [
        (0, "", True),
        (0, '{"Names":"forge-worker","State":"exited"}\n', True),
        (0, '{"Names":"forge-worker","State":"running"}\n', False),
        (0, '{"Names":"forge-worker","State":"created"}\n', False),
        (0, '{"Names":"forge-other","State":"running"}\n', True),
        (0, '{"Unknown":"future"}\n', False),
        (0, "unreadable\n", False),
        (1, "", False),
    ],
)
def test_sidecar_exit_requires_successful_docker_census(
    monkeypatch: pytest.MonkeyPatch, returncode: int, states: str, expected: bool
) -> None:
    monkeypatch.setattr(
        "forge.session.workers.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, returncode, stdout=states),
    )
    assert _sidecar_exit_confirmed("worker") is expected
