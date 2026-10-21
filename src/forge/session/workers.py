"""Instance-bound admission for asynchronous session producers."""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

import dacite

from forge.core.paths import get_forge_home
from forge.core.process import is_pid_alive
from forge.core.state import atomic_write_json

from .exceptions import ForgeSessionError, SessionNotFoundError
from .index import IndexStore

SESSION_INSTANCE_ENV = "FORGE_SESSION_INSTANCE"
SIDECAR_LEASE_ENV = "FORGE_SIDECAR_WORKER_LEASE"
SIDECAR_LEASE_MOUNT = "/run/forge/session-workers"
_SIDECAR_LEASE_LABEL = "sidecar runtime"
_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _WorkerLease:
    schema_version: int
    forge_root: str
    session_name: str
    instance_id: str
    pid: int
    label: str


def capture_session_instance(forge_root: str | Path, name: str, *, index_store: IndexStore | None = None) -> str:
    """Capture a producer's generation, explicitly migrating a live legacy row."""
    if os.environ.get("FORGE_SIDECAR") == "1":
        token = os.environ.get(SESSION_INSTANCE_ENV, "")
        _require_sidecar_lease(forge_root, name, token)
        return token
    index = index_store or IndexStore()
    root = str(Path(forge_root).resolve())
    entry = index.peek_session(name, root)
    if entry is not None and entry.instance_id is not None:
        return entry.instance_id
    return index.migrate_session_identity(name, root)


def _lease_dir(instance_id: str) -> Path:
    if len(instance_id) != 32 or any(c not in "0123456789abcdef" for c in instance_id):
        raise ValueError("Invalid session worker instance identity")
    return get_forge_home() / "session-workers" / instance_id


@contextmanager
def session_worker_lease(
    forge_root: str | Path,
    name: str,
    *,
    expected_instance_id: str,
    label: str,
    index_store: IndexStore | None = None,
) -> Iterator[None]:
    """Admit a worker and protect its provider writes without holding a global lock.

    Cleanup checks these leases under publication authority and refuses live
    workers. The lease is published under that same authority before work starts.
    A detached worker must carry the originating generation into this call.
    """
    if os.environ.get("FORGE_SIDECAR") == "1":
        _require_sidecar_lease(forge_root, name, expected_instance_id)
        yield
        return
    path = _create_worker_lease(forge_root, name, expected_instance_id, label, index_store)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def run_session_producer_txn(
    forge_root: str | Path,
    name: str,
    *,
    expected_instance_id: str,
    callback: Callable[[], None],
) -> bool:
    """Persist under host publication authority or its live sidecar delegation."""
    if os.environ.get("FORGE_SIDECAR") == "1":
        _require_sidecar_lease(forge_root, name, expected_instance_id)
        callback()
        return True
    return IndexStore().run_session_instance_txn(
        name, str(forge_root), expected_instance_id=expected_instance_id, callback=callback
    )


@contextmanager
def sidecar_session_lease(forge_root: str | Path, name: str, *, expected_instance_id: str) -> Iterator[Path]:
    """Delegate host admission until Docker proves that the container has exited.

    Mount the returned path's directory read-only, so removing the host lease is
    visible to hooks. A failed Docker client or interrupted launcher leaves the
    lease for explicit recovery; a container PID cannot establish host liveness.
    """
    path = _create_worker_lease(forge_root, name, expected_instance_id, _SIDECAR_LEASE_LABEL, None)
    exited = False
    try:
        yield path
        exited = _sidecar_exit_confirmed(name)
    finally:
        if exited:
            path.unlink(missing_ok=True)
        else:
            _log.warning("Sidecar exit was not verified; retained session worker lease %s", path)


def _sidecar_exit_confirmed(name: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    try:
        for line in result.stdout.splitlines():
            container = json.loads(line)
            if not isinstance(container, dict):
                return False
            names, state = container.get("Names"), container.get("State")
            if not isinstance(names, str) or not names or not isinstance(state, str) or not state:
                return False
            if f"forge-{name}" in names.split(",") and state not in {"exited", "dead"}:
                return False
    except (ValueError, TypeError):
        return False
    return True


def _require_sidecar_lease(forge_root: str | Path, name: str, instance_id: str) -> None:
    from .store import SessionStore

    root = str(Path(forge_root).resolve())
    lease_path = os.environ.get(SIDECAR_LEASE_ENV)
    host_root = os.environ.get("FORGE_SIDECAR_HOST_FORGE_ROOT")
    local_root = os.environ.get("FORGE_FORGE_ROOT")
    if (
        not lease_path
        or not host_root
        or not local_root
        or root != str(Path(local_root).resolve())
        or os.environ.get("FORGE_SESSION") != name
        or os.environ.get(SESSION_INSTANCE_ENV) != instance_id
        or re.fullmatch(r"[0-9a-f]{32}", instance_id) is None
    ):
        raise SessionNotFoundError(name)
    try:
        path = Path(lease_path)
        if (
            path.parent != Path(SIDECAR_LEASE_MOUNT)
            or path.parent.is_symlink()
            or re.fullmatch(r"[0-9a-f]{32}\.json", path.name) is None
        ):
            raise ValueError("Invalid delegated worker lease path")
        lease = _read_worker_lease(path)
        store = SessionStore(root, name)
        state = store.read()
        manifest_root = state.forge_root or (state.worktree.path if state.worktree else None)
        if (
            lease.schema_version != 1
            or lease.label != _SIDECAR_LEASE_LABEL
            or lease.forge_root != host_root
            or lease.session_name != name
            or lease.instance_id != instance_id
            or state.name != name
            or manifest_root != host_root
            or store.review_identity() != instance_id
        ):
            raise ValueError("Delegated worker lease does not match the mounted session")
    except (OSError, ValueError, dacite.DaciteError, ForgeSessionError) as error:
        raise SessionNotFoundError(name) from error


def _create_worker_lease(
    forge_root: str | Path,
    name: str,
    expected_instance_id: str,
    label: str,
    index_store: IndexStore | None,
) -> Path:
    root = str(Path(forge_root).resolve())
    lease = _WorkerLease(1, root, name, expected_instance_id, os.getpid(), label)
    path = _lease_dir(expected_instance_id) / f"{uuid4().hex}.json"
    admitted = (index_store or IndexStore()).run_session_instance_txn(
        name,
        root,
        expected_instance_id=expected_instance_id,
        callback=lambda: atomic_write_json(path, asdict(lease)),
    )
    if not admitted:
        raise SessionNotFoundError(name)
    return path


def _read_worker_lease(path: Path) -> _WorkerLease:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f"Invalid session worker lease: {path}")
        return dacite.from_dict(_WorkerLease, json.load(stream), config=dacite.Config(strict=True))


def find_active_session_workers(forge_root: str | Path, name: str, instance_id: str) -> tuple[str, ...]:
    """Read live producer leases without repairing or discarding unknown state."""
    root = str(Path(forge_root).resolve())
    directory = _lease_dir(instance_id)
    if directory.is_symlink():
        raise ValueError(f"Session worker lease directory is a symlink: {directory}")
    if not directory.exists():
        return ()
    active: list[str] = []
    for path in sorted(directory.iterdir()):
        if not path.name.endswith(".json"):
            continue
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            continue
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError(f"Invalid session worker lease: {path}")
            lease = dacite.from_dict(_WorkerLease, json.load(stream), config=dacite.Config(strict=True))
        if (
            lease.schema_version != 1
            or lease.forge_root != root
            or lease.session_name != name
            or lease.instance_id != instance_id
            or type(lease.pid) is not int
            or not 0 < lease.pid <= (1 << 31) - 1
        ):
            raise ValueError(f"Invalid session worker lease ownership: {path}")
        if is_pid_alive(lease.pid):
            active.append(f"{lease.label} (pid {lease.pid}; lease {path})")
        else:
            active.append(
                f"{lease.label}: worker exited without releasing lease {path}; "
                "inspect native subprocesses before explicitly removing the abandoned lease"
            )
    return tuple(active)
