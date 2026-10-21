"""Read-only cleanup admission and instance-bound, retryable session deletion."""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import dacite

from forge.core.runtime.codex_review_source import directory_fd, read_regular
from forge.install.project_compat import enforce_project_compatibility
from forge.search.cleanup import indexed_transcript_paths

from .active import ActiveSessionStore
from .cleanup_content import (
    ForgeContentPlan,
    apply_forge_content,
    forge_content_leases,
    plan_forge_content,
    validate_forge_content,
    validate_forge_content_scope,
)
from .cleanup_dependencies import (
    discover_session_states,
    find_cleanup_dependencies,
    manifest_digest,
    session_entries,
)
from .cleanup_git import CleanupGitIdentity, capture_cleanup_git, validate_cleanup_git
from .cleanup_state import cleanup_state_path
from .exceptions import ForgeSessionError, SessionNotFoundError
from .identity import resolve_key_strict
from .index import IndexStore
from .models import SessionState
from .purge_native import (
    NativePurgePlan,
    NativeRuntime,
    check_native_inactivity,
    plan_native_purge,
    revalidate_native_file,
    unlink_native_file,
    validate_native_purge_scope,
)
from .store import SessionStore
from .validation import validate_name

MAX_RETRY_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class SessionDeletionPlan:
    """One immutable cleanup selection, also saved outside removable worktrees."""

    name: str
    forge_root: str
    instance_id: str | None
    manifest_sha256: str
    mode: Literal["delete", "purge"]
    state: SessionState
    content: ForgeContentPlan
    native: NativePurgePlan | None
    delete_worktree: bool
    delete_branch: bool
    force: bool
    worktree_path: str | None = None
    worktree_device: int | None = None
    worktree_inode: int | None = None
    repository_root: str | None = None
    git_identity: CleanupGitIdentity | None = None
    branch: str | None = None
    refusals: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    retry: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the private durable retry representation."""
        value = asdict(self)
        value["schema_version"] = 1
        return value

    def preview_dict(self) -> dict[str, Any]:
        """Expose cleanup scope without echoing the session's manifest content."""
        return {
            "schema_version": 1,
            "name": self.name,
            "forge_root": self.forge_root,
            "instance_id": self.instance_id,
            "mode": self.mode,
            "retry": self.retry,
            "manifest_directory": str(SessionStore(self.forge_root, self.name).session_dir),
            "manifest_directory_scope": "entire-directory",
            "content": self.content.to_dict(),
            "native": self.native.to_dict() if self.native else None,
            "worktree_path": self.worktree_path,
            "branch": self.branch,
            "refusals": list(self.refusals),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SessionDeletionPlan:
        """Reject newer, malformed or incorrectly scoped retry inventories."""
        raw = dict(value)
        if raw.pop("schema_version", None) != 1:
            raise ValueError("Unsupported session cleanup inventory version")
        raw["content"] = ForgeContentPlan.from_dict(raw["content"])
        if raw["native"] is not None:
            raw["native"] = NativePurgePlan.from_dict(raw["native"])
        plan = dacite.from_dict(cls, raw, config=dacite.Config(strict=True, cast=[tuple]))
        validate_name(plan.name)
        root = Path(plan.forge_root)
        if not root.is_absolute() or root != root.resolve():
            raise ValueError("Cleanup inventory has a noncanonical Forge root")
        if plan.state.name != plan.name or (
            plan.content.session_name != plan.name or plan.content.forge_root != plan.forge_root
        ):
            raise ValueError("Cleanup inventory has inconsistent session ownership")
        if plan.mode not in {"delete", "purge"} or (plan.native is not None) != (plan.mode == "purge"):
            raise ValueError("Cleanup inventory has inconsistent native deletion scope")
        if plan.instance_id is None or not plan.instance_id:
            raise ValueError("Cleanup inventory is missing its session instance")
        if not re.fullmatch(r"[0-9a-f]{32}", plan.instance_id):
            raise ValueError("Cleanup inventory has an invalid session instance")
        if not re.fullmatch(r"[0-9a-f]{64}", plan.manifest_sha256):
            raise ValueError("Cleanup inventory has an invalid manifest digest")
        if plan.refusals or plan.content.refusals or (plan.native and plan.native.refusals):
            raise ValueError("A refused cleanup inventory cannot authorize a retry")
        if plan.state.forge_root is not None and Path(plan.state.forge_root).resolve() != root:
            raise ValueError("Cleanup inventory state belongs to another Forge root")
        if plan.branch is not None and (
            not plan.delete_branch
            or plan.state.worktree is None
            or plan.branch != plan.state.worktree.branch
            or plan.git_identity is None
        ):
            raise ValueError("Cleanup inventory branch differs from its session")
        if plan.worktree_path is not None:
            worktree_path = Path(plan.worktree_path)
            if not worktree_path.is_absolute() or worktree_path != worktree_path.resolve():
                raise ValueError("Cleanup inventory has a noncanonical worktree")
            if plan.state.worktree is None or plan.worktree_path != plan.state.worktree.path:
                raise ValueError("Cleanup inventory worktree differs from its session")
            if not plan.delete_worktree or not plan.state.worktree.is_worktree or not plan.state.worktree.owns_worktree:
                raise ValueError("Cleanup inventory does not own its worktree")
            if plan.worktree_inode is not None and (not plan.repository_root or not plan.git_identity):
                raise ValueError("Cleanup inventory is missing its worktree Git identity")
        if plan.repository_root is not None:
            repository = Path(plan.repository_root)
            if not repository.is_absolute() or repository != repository.resolve():
                raise ValueError("Cleanup inventory has a noncanonical repository root")
        if plan.native:
            validate_native_purge_scope(plan.native, plan.state)
        validate_forge_content_scope(plan.content, plan.state)
        return replace(plan, retry=True)


def plan_session_deletion(
    index: IndexStore,
    name: str,
    *,
    forge_root: str | None = None,
    purge: bool = False,
    delete_worktree: bool = True,
    delete_branch: bool = False,
    force: bool = False,
) -> SessionDeletionPlan:
    """Select content and refusals without repairing manifests, indexes or queues."""
    from .manager import SessionManager
    from .worktree import is_worktree_dirty

    validate_name(name)
    rows = index.read().sessions
    root = str(Path(forge_root).resolve()) if forge_root else None
    key = resolve_key_strict(rows, name, root)
    if key is not None:
        root = str(Path(rows[key].root).resolve())
    if root is None:
        raise SessionNotFoundError(name)
    retry_path = cleanup_state_path(root, name)
    if retry_path.exists() or retry_path.is_symlink():
        plan = _read_retry(retry_path)
        if (plan.name, plan.forge_root) != (name, root):
            raise ForgeSessionError("Cleanup retry inventory belongs to another session")
        if (plan.mode, plan.delete_worktree, plan.delete_branch, plan.force) != (
            "purge" if purge else "delete",
            delete_worktree,
            delete_branch,
            force,
        ):
            raise ForgeSessionError(
                f"An interrupted {plan.mode} owns this session; retry with its original worktree, branch and force options"
            )
        retry_refusals = (*_admission_refusals(index, plan), *_retry_refusals(plan))
        return replace(plan, refusals=tuple(dict.fromkeys(retry_refusals)))
    if key is None:
        raise ForgeSessionError(f"Session '{name}' has no published record; inspect 'forge session repair' first")
    enforce_project_compatibility(root)
    store = SessionStore(root, name)
    if not store.exists():
        raise ForgeSessionError(
            f"Session '{name}' has no manifest; run 'forge session list --scope all' to prune its stale index row, "
            "then preview 'forge clean' for remaining orphan content"
        )
    manifest_sha256 = _manifest_digest(store)
    state = store.read()
    owner = store.review_identity()
    if rows[key].instance_id is not None and owner != rows[key].instance_id:
        raise ForgeSessionError(f"Session '{name}' has inconsistent ownership; restore its original owner file")
    if _manifest_digest(store) != manifest_sha256:
        raise ForgeSessionError(f"Session '{name}' changed during preview; retry")
    content = plan_forge_content(state, forge_root=Path(root))
    native = plan_native_purge(state) if purge else None
    notes = list(content.notes)
    if not purge:
        notes.append("Native Claude transcripts, subagent logs and Codex rollouts are retained.")
    manager = SessionManager()
    manager.index_store = index
    worktree = manager.plan_worktree_cleanup(
        name,
        state,
        delete_worktree=delete_worktree,
        forge_root=root,
        sessions=session_entries(index),
    )
    worktree_path = None
    device = inode = None
    repository_root = None
    git_identity = None
    branch = None
    refusals = list(content.refusals) + (list(native.refusals) if native else [])
    if worktree.remove and state.worktree:
        worktree_path = state.worktree.path
        branch = state.worktree.branch if delete_branch else None
        path = Path(worktree_path)
        if path.exists():
            from .git import get_main_repo_root

            if path.is_symlink():
                refusals.append(f"Worktree path is a symlink: {path}")
            else:
                identity = path.stat()
                device, inode = identity.st_dev, identity.st_ino
                repository_root = str(get_main_repo_root(path))
                try:
                    git_identity = capture_cleanup_git(path, Path(repository_root), branch)
                except (OSError, ValueError) as error:
                    refusals.append(str(error))
                if not force and is_worktree_dirty(path):
                    refusals.append(f"Worktree has uncommitted changes: {path}; preserve it or explicitly use --force")
        elif branch:
            refusals.append("Cannot verify the branch of a missing worktree; retry without --delete-branch")
        notes.append(f"Remove worktree: {worktree_path}. Retained native sessions may lose their original directory.")
    elif state.worktree and state.worktree.is_worktree:
        notes.append(f"Keep worktree ({worktree.reason}): {state.worktree.path}")
    plan = SessionDeletionPlan(
        name=name,
        forge_root=root,
        instance_id=rows[key].instance_id or owner,
        manifest_sha256=manifest_sha256,
        mode="purge" if purge else "delete",
        state=state,
        content=content,
        native=native,
        delete_worktree=delete_worktree,
        delete_branch=delete_branch,
        force=force,
        worktree_path=worktree_path,
        worktree_device=device,
        worktree_inode=inode,
        repository_root=repository_root,
        git_identity=git_identity,
        branch=branch,
        notes=tuple(notes),
    )
    refusals.extend(_admission_refusals(index, plan))
    return replace(plan, refusals=tuple(dict.fromkeys(refusals)))


def apply_session_deletion(index: IndexStore, plan: SessionDeletionPlan) -> tuple[str, ...]:
    """Revalidate and remove only the selected instance; keep retry state on failure."""
    if plan.refusals:
        raise ForgeSessionError("; ".join(plan.refusals))
    store = SessionStore(plan.forge_root, plan.name)
    retry_path = cleanup_state_path(plan.forge_root, plan.name)
    try:
        if not plan.retry:
            token = index.migrate_session_identity(
                plan.name,
                plan.forge_root,
                expected_manifest_sha256=plan.manifest_sha256,
                require_ownerless=plan.instance_id is None,
            )
            if plan.instance_id is not None and token != plan.instance_id:
                raise ValueError("Session instance changed since preview")
            plan = replace(plan, instance_id=token)
        assert plan.instance_id is not None
        removed: list[str] = []

        def cleanup_while_leased() -> None:
            refusals = _admission_refusals(index, plan, reviewer_leases_held=True)
            if refusals:
                raise ValueError("; ".join(refusals))
            if store.exists() and _manifest_digest(store) != plan.manifest_sha256:
                raise ValueError("Session manifest changed since preview; inspect the session before retrying")
            if store.exists() and store.read() != plan.state:
                raise ValueError("Cleanup inventory state differs from the current manifest")
            validate_forge_content(plan.content)
            if plan.native:
                for file in plan.native.files:
                    revalidate_native_file(file, allow_missing=plan.retry)
            _validate_worktree(plan)
            if not plan.retry:
                _save_retry(retry_path, plan)
            if plan.native:
                for file in plan.native.files:
                    if unlink_native_file(file):
                        removed.append(file.path)
            removed.extend(apply_forge_content(plan.content, _reviewer_leases_held=True))
            if plan.worktree_path:
                from .worktree import cleanup_worktree

                _validate_worktree(plan)
                result = cleanup_worktree(
                    Path(plan.worktree_path),
                    branch=plan.branch,
                    delete_branch_flag=plan.delete_branch,
                    force=plan.force,
                    repo_root=(Path(plan.repository_root) if plan.repository_root else None),
                )
                if result.errors:
                    raise ValueError("; ".join(result.errors))
                if result.worktree_removed:
                    removed.append(plan.worktree_path)
            ActiveSessionStore().clear_session(plan.name, forge_root=plan.forge_root)
            if store.session_dir.exists():
                try:
                    if _manifest_digest(store) != plan.manifest_sha256:
                        raise ValueError("Session manifest changed during cleanup")
                except FileNotFoundError:
                    if not plan.retry:
                        raise
                with directory_fd(store.session_dir):
                    pass
                store.delete_locked()
                removed.append(str(store.session_dir))

        def cleanup() -> None:
            validate_forge_content_scope(plan.content, plan.state)
            with forge_content_leases(plan.content):
                cleanup_while_leased()

        if not index.delete_session_txn(
            plan.name,
            plan.forge_root,
            expected_instance_id=plan.instance_id,
            delete_manifest=cleanup,
        ):
            # A crash after row removal can leave only the durable completion inventory.
            rows = index.read().sessions
            if not plan.retry or resolve_key_strict(rows, plan.name, plan.forge_root) is not None or store.exists():
                raise ValueError("Session instance changed or disappeared since preview; no replacement was removed")
            refusals = _admission_refusals(index, plan)
            if refusals:
                raise ValueError("; ".join(refusals))
            _verify_completed(plan)
        retry_path.unlink(missing_ok=True)
        return tuple(removed)
    except (OSError, ValueError, ForgeSessionError, dacite.DaciteError) as error:
        options = ["--yes", "--forge-root", plan.forge_root]
        if not plan.delete_worktree:
            options.append("--keep-worktree")
        if plan.delete_branch:
            options.append("--delete-branch")
        if plan.force:
            options.append("--force")
        command = shlex.join(["forge", "session", plan.mode, plan.name, *options])
        recovery = f"Retry with the same inventory using: {command}"
        raise ForgeSessionError(f"Session cleanup did not finish: {error}. {recovery}") from error


def _admission_refusals(
    index: IndexStore, plan: SessionDeletionPlan, *, reviewer_leases_held: bool = False
) -> tuple[str, ...]:
    from .workers import find_active_session_workers

    reasons: list[str] = []
    if not reviewer_leases_held:
        try:
            validate_forge_content_scope(plan.content, plan.state)
            with forge_content_leases(plan.content):
                pass
        except (OSError, ValueError) as error:
            reasons.append(str(error))
    active = ActiveSessionStore()
    try:
        if any(
            name == plan.name and str(Path(entry.forge_root or entry.worktree_path).resolve()) == plan.forge_root
            for name, entry in active.peek_sessions_strict()
        ):
            reasons.append("Session is active; exit its runtime before cleanup")
    except (
        OSError,
        ValueError,
        dacite.DaciteError,
        subprocess.SubprocessError,
    ) as error:
        reasons.append(f"Cannot verify active session registry {active.index_path}: {error}; restore it before cleanup")
    if plan.instance_id:
        workers = find_active_session_workers(plan.forge_root, plan.name, plan.instance_id)
        if workers:
            reasons.append("Session workers are still running: " + "; ".join(workers))
    dependencies = find_cleanup_dependencies(
        index,
        plan.state,
        forge_root=plan.forge_root,
        native_ids=({file.native_id for file in plan.native.files} if plan.native else None),
        content_paths=tuple(file.path for file in plan.content.files),
        allow_missing_target=plan.retry,
    )
    if dependencies:
        reasons.append("Existing sessions depend on this session: " + "; ".join(dependencies))
    if plan.native:
        runtimes: set[NativeRuntime] = {file.runtime for file in plan.native.files}
        for runtime in runtimes:
            reasons.extend(check_native_inactivity(runtime))
        # Rediscovery is a guard only: it may refuse new files or descendants,
        # never add a target to the approved inventory.
        current = plan_native_purge(plan.state)
        reasons.extend(current.refusals)
        if {file.path for file in current.files} - {file.path for file in plan.native.files}:
            reasons.append("Native content appeared after preview; no additional paths were authorized")
    if plan.worktree_path:
        from forge.core.runtime.codex_rollouts import codex_home

        from .claude.paths import get_claude_home

        worktree = Path(plan.worktree_path).resolve()
        if cleanup_state_path(plan.forge_root, plan.name).resolve().is_relative_to(worktree):
            reasons.append("Cleanup inventory must be outside the removed worktree; move FORGE_HOME before cleanup")
        native_locations = [
            ("Claude home", get_claude_home(), True),
            ("Codex home", codex_home(), True),
        ]
        if configured_claude := os.environ.get("CLAUDE_CONFIG_DIR"):
            native_locations.append(("CLAUDE_CONFIG_DIR", Path(configured_claude), True))
        states = discover_session_states(
            index,
            plan.forge_root,
            allow_missing=(plan.forge_root, plan.name) if plan.retry else None,
        )
        for root, name, state in [(plan.forge_root, plan.name, plan.state), *states]:
            native_locations.extend(_recorded_native_locations(state, root))
            if (root, name) == (plan.forge_root, plan.name):
                continue
            location = Path(state.worktree.path if state.worktree else root).resolve()
            if Path(root).is_relative_to(worktree) or location.is_relative_to(worktree):
                reasons.append(f"Worktree contains another session: {name} ({root})")
        for label, path, is_home in native_locations:
            if is_home and not path.expanduser().is_absolute():
                reasons.append(f"Cannot verify relative native home ({label}): {path}; use --keep-worktree")
                continue
            # Check both the recorded spelling and its target: removing a checkout
            # must not remove a native store or a link that locates retained bytes.
            locations = {Path(os.path.abspath(path.expanduser())), path.expanduser().resolve()}
            if any(
                location.is_relative_to(worktree) or (is_home and worktree.is_relative_to(location))
                for location in locations
            ):
                reasons.append(f"Worktree overlaps retained native storage ({label}): {path}; use --keep-worktree")
    return tuple(dict.fromkeys(reasons))


def _recorded_native_locations(state: SessionState, root: str) -> list[tuple[str, Path, bool]]:
    """Keep historical native paths safe even after the configured home changes."""
    confirmed = state.confirmed
    paths = [
        confirmed.transcript_path,
        confirmed.codex.rollout_path if confirmed.codex else None,
        confirmed.adoption.source_path if confirmed.adoption else None,
        confirmed.subagents.last_transcript_path if confirmed.subagents else None,
    ]
    sources = confirmed.artifacts.get("transcripts", [])
    if not isinstance(sources, list):
        raise ValueError(f"Cannot verify recorded native transcript sources for {state.name}")
    if confirmed.compaction:
        if not isinstance(confirmed.compaction.transcript_snapshots, list):
            raise ValueError(f"Cannot verify recorded native transcript snapshots for {state.name}")
        sources = [*sources, *confirmed.compaction.transcript_snapshots]
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError(f"Cannot verify recorded native transcript sources for {state.name}")
        paths.append(source.get("source_path"))
    locations: list[tuple[str, Path, bool]] = []
    for value in paths:
        if value is None:
            continue
        if not isinstance(value, str) or not value:
            raise ValueError(f"Cannot verify recorded native path for {state.name}")
        path = Path(value).expanduser()
        locations.append((f"{state.name} native source", path if path.is_absolute() else Path(root) / path, False))
    policy = state.intent.policy
    if policy and policy.supervisor and policy.supervisor.native_source:
        source = policy.supervisor.native_source
        locations.extend(
            [
                (f"{state.name} native supervisor home", Path(source.home), True),
                (f"{state.name} native supervisor rollout", Path(source.rollout_path), False),
            ]
        )
    return locations


def _manifest_digest(store: SessionStore) -> str:
    return manifest_digest(store)


def _retry_refusals(plan: SessionDeletionPlan) -> tuple[str, ...]:
    """Expose changed retry targets in the preview using apply's exact guards."""
    reasons: list[str] = []
    store = SessionStore(plan.forge_root, plan.name)
    try:
        if store.exists() and (_manifest_digest(store) != plan.manifest_sha256 or store.read() != plan.state):
            reasons.append("Session manifest changed since preview; inspect the session before retrying")
        validate_forge_content(plan.content)
    except (OSError, ValueError, ForgeSessionError) as error:
        reasons.append(str(error))
    if plan.native:
        for file in plan.native.files:
            try:
                revalidate_native_file(file, allow_missing=True)
            except (OSError, ValueError) as error:
                reasons.append(str(error))
    try:
        _validate_worktree(plan)
    except (OSError, ValueError, ForgeSessionError) as error:
        reasons.append(str(error))
    return tuple(reasons)


def _validate_worktree(plan: SessionDeletionPlan) -> None:
    if not plan.worktree_path:
        return
    path = Path(plan.worktree_path)
    if plan.git_identity is not None and plan.repository_root is not None:
        validate_cleanup_git(path, Path(plan.repository_root), plan.git_identity, plan.branch)
    elif path.exists():
        raise ValueError("Worktree has no verified Git identity")
    if not path.exists() and not path.is_symlink():
        return
    identity = path.lstat()
    if not stat.S_ISDIR(identity.st_mode) or (identity.st_dev, identity.st_ino) != (
        plan.worktree_device,
        plan.worktree_inode,
    ):
        raise ValueError("Worktree directory was replaced after preview")
    if not plan.force:
        from .worktree import is_worktree_dirty

        if is_worktree_dirty(path):
            raise ValueError(f"Worktree has uncommitted changes: {path}")


def _save_retry(path: Path, plan: SessionDeletionPlan) -> None:
    data = (json.dumps(plan.to_dict(), indent=2) + "\n").encode()
    if len(data) > MAX_RETRY_BYTES:
        raise ValueError("Cleanup inventory exceeds the supported size")
    with directory_fd(path.parent.parent) as home:
        try:
            os.mkdir(path.parent.name, mode=0o700, dir_fd=home)
        except FileExistsError:
            pass
    with directory_fd(path.parent) as parent:
        temporary = f".{path.name}.{uuid4().hex}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # Publish without replacing another cleanup's durable authority.
            os.link(
                temporary,
                path.name,
                src_dir_fd=parent,
                dst_dir_fd=parent,
                follow_symlinks=False,
            )
            os.unlink(temporary, dir_fd=parent)
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


def _read_retry(path: Path) -> SessionDeletionPlan:
    try:
        data = read_regular(path, limit=MAX_RETRY_BYTES)
        return SessionDeletionPlan.from_dict(json.loads(data))
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RecursionError,
        dacite.DaciteError,
    ) as error:
        raise ForgeSessionError(
            f"Cannot verify cleanup inventory {path}: {error}; restore the original inventory"
        ) from error


def _verify_completed(plan: SessionDeletionPlan) -> None:
    validate_forge_content(plan.content)
    if set(plan.content.search_keys) & indexed_transcript_paths(Path(plan.forge_root)):
        raise ValueError("Cleanup lost its index owner before search content was removed; restore the index")
    paths = [file.path for file in plan.content.files]
    paths.extend(directory.path for directory in plan.content.directories)
    paths.append(str(SessionStore(plan.forge_root, plan.name).session_dir))
    if plan.native:
        paths.extend(file.path for file in plan.native.files)
    paths.extend([plan.worktree_path] if plan.worktree_path else [])
    if any(Path(path).exists() or Path(path).is_symlink() for path in paths):
        raise ValueError("Cleanup lost its index owner before all selected content was removed; restore the index")
