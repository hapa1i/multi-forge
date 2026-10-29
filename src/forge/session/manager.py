"""High-level session operations coordinating stores.

SessionManager provides the business logic for session lifecycle operations,
coordinating between SessionStore and IndexStore.

The CLI layer should be thin and delegate to this class for all operations.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar, cast

from forge.core.naming import generate_unique_name
from forge.core.state import now_iso
from forge.install.project_compat import (
    ProjectCompatibilityError,
    enforce_project_compatibility,
    enforce_project_compatibility_toml,
)

from .artifacts import (
    latest_transcript_artifact_path,
)
from .config import (
    DEFAULT_PROXY_BASE_URL,
    DEFAULT_PROXY_TEMPLATE,
    LAUNCH_MODE_HOST,
    LAUNCH_MODE_SIDECAR,
)
from .exceptions import (
    CannotForkCodexParentError,
    CannotForkIncognitoError,
    ContextBudgetExceededError,
    ForgeSessionError,
    ManifestCorruptedError,
    ManifestValidationError,
    SessionExistsError,
    SessionNotFoundError,
)
from .index import IndexStore
from .launchability import require_session_worktree
from .models import (
    AdoptionConfirmed,
    AuthorityIntent,
    CodexConfirmed,
    Derivation,
    LaunchIntent,
    ModelRouteIntent,
    SessionIndexEntry,
    SessionState,
    SidecarLaunchIntent,
    create_session_state,
    inherited_authority,
)
from .prev_sessions import child_path, child_path_rel, ensure_child, generated_path
from .store import SessionStore
from .transfer import (
    ResumeStrategy,
    TransferResult,
    assemble_transfer_context,
    estimate_transcript_tokens,
    parse_transfer_context_strategy,
    resolve_transfer_transcript_source,
)
from .validation import validate_name

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorktreeCleanupPlan:
    """Whether a requested session deletion can remove its worktree."""

    remove: bool
    reason: str
    co_residents: tuple[str, ...] = ()


def fork_target_matches_replacement(
    *,
    existing_state: SessionState | None,
    parent_name: str,
    target_forge_root: str | Path,
    expected_worktree_path: str | Path,
    expected_branch: str,
    expected_is_worktree: bool,
    expected_owns_worktree: bool,
) -> bool:
    """Return whether durable target identity permits narrow stale replacement.

    Runtime liveness is intentionally excluded: read-only planning uses the
    non-repairing active-store seam, while mutation rechecks through the
    self-healing seam immediately before replacement.
    """
    if existing_state is None or not existing_state.is_fork or existing_state.parent_session != parent_name:
        return False
    if (
        existing_state.forge_root is not None
        and Path(existing_state.forge_root).resolve() != Path(target_forge_root).resolve()
    ):
        return False

    worktree = existing_state.worktree
    if worktree is None or Path(worktree.path).resolve() != Path(expected_worktree_path).resolve():
        return False
    if worktree.branch != expected_branch or worktree.is_worktree != expected_is_worktree:
        return False
    if expected_is_worktree and getattr(worktree, "owns_worktree", True) != expected_owns_worktree:
        return False
    return True


def _delete_session_manifest(store: SessionStore) -> None:
    """Delete one session manifest while discarding the store's bool result."""
    store.delete_locked()


def _cleanup_unclaimed_worktree(
    index: IndexStore, path: Path, *, branch: str | None, repository: Path | None
) -> list[str]:
    """Compensate creation only while no published or orphan session owns the checkout."""
    from .cleanup_dependencies import discover_session_states
    from .worktree import cleanup_worktree

    checkout = path.resolve()

    def cleanup(entries: list[tuple[str, SessionIndexEntry]]) -> list[str]:
        for name, entry in entries:
            if Path(entry.worktree_path).resolve().is_relative_to(checkout) or Path(
                entry.root
            ).resolve().is_relative_to(checkout):
                return [f"Worktree {checkout} is now referenced by session {name}; inspect it before cleanup"]
        for root, name, state in discover_session_states(index, str(checkout)):
            location = Path(state.worktree.path if state.worktree else root).resolve()
            if location.is_relative_to(checkout) or Path(root).resolve().is_relative_to(checkout):
                return [f"Worktree {checkout} is now referenced by session {name}; inspect it before cleanup"]
        result = cleanup_worktree(
            worktree_path=checkout,
            branch=branch,
            delete_branch_flag=True,
            force=True,
            repo_root=repository,
        )
        return list(result.errors)

    return index.run_session_entries_txn(cleanup)


def _inherited_launch_intent(parent_state: SessionState) -> LaunchIntent | None:
    """Return the launch intent a derived session should inherit."""
    if parent_state.intent.launch is not None:
        return deepcopy(parent_state.intent.launch)

    if parent_state.confirmed.is_sandboxed:
        return LaunchIntent(
            mode=LAUNCH_MODE_SIDECAR,
            sidecar=SidecarLaunchIntent(),
        )

    return None


def _inherit_intent_fields(child_state: SessionState, parent_state: SessionState) -> None:
    """Copy intent fields that derived sessions inherit from their parent."""
    for field_name in (
        "subprocess_proxy",
        "policy",
        "memory",
        "system_prompt",
        "verification",
        "consumer_lanes",
    ):
        parent_val = getattr(parent_state.intent, field_name, None)
        if parent_val is not None:
            setattr(child_state.intent, field_name, deepcopy(parent_val))
    inherited_launch = _inherited_launch_intent(parent_state)
    if inherited_launch is not None:
        child_state.intent.launch = inherited_launch
    child_state.intent.authority = inherited_authority(parent_state.intent.authority)


def _append_created_authority_event(
    state: SessionState,
    store: SessionStore,
    *,
    operation: str,
    explicit: bool,
    lock_held: bool = False,
) -> None:
    """Commit the required configuration event for a newly published marked session."""
    if state.intent.authority is None:
        return
    from .authority import (
        append_authority_event,
        authority_session_lock,
        new_authority_event,
    )

    event = new_authority_event(
        state,
        event_type="authority_configured" if explicit else "authority_inherited",
        run_id=None,
        origin_surface="external_cli" if explicit else "session_derivation",
        operation=operation,
        outcome="success",
    )
    if lock_held:
        append_authority_event(str(store.forge_root), event)
        return
    with authority_session_lock(store.session_dir):
        append_authority_event(str(store.forge_root), event)


def _publish_created_session(
    index_store: IndexStore,
    state: SessionState,
    store: SessionStore,
    project_root: str,
    *,
    checkout_root: str | None,
    forge_root: str | None,
    relative_path: str | None,
    operation: str,
    authority_explicit: bool,
    require_uuid_unbound: bool = False,
) -> str:
    """Publish a session and return its instance identity for subsequent guarded work."""
    from .authority import authority_session_lock

    creation_lock = authority_session_lock(store.session_dir) if state.intent.authority is not None else nullcontext()
    instance_id: str | None = None

    def publish_manifest() -> None:
        nonlocal instance_id
        store.create_exclusive(state)
        instance_id = store.review_identity()

    with creation_lock:
        index_store.create_session_txn(
            state,
            project_root,
            checkout_root=checkout_root,
            forge_root=forge_root,
            relative_path=relative_path,
            require_uuid_unbound=require_uuid_unbound,
            write_manifest=publish_manifest,
        )
        try:
            assert instance_id is not None
            if not index_store.run_session_instance_txn(
                state.name,
                str(store.forge_root),
                expected_instance_id=instance_id,
                callback=lambda: _append_created_authority_event(
                    state, store, operation=operation, explicit=authority_explicit, lock_held=True
                ),
            ):
                raise ForgeSessionError(f"Session '{state.name}' changed before its creation record was written")
        except Exception:
            assert instance_id is not None
            index_store.delete_session_txn(
                state.name,
                forge_root=str(store.forge_root),
                expected_instance_id=instance_id,
                delete_manifest=lambda: _delete_session_manifest(store),
            )
            raise
    return instance_id


_SessionOperation = TypeVar("_SessionOperation", bound=Callable[..., Any])


def _with_parent_lease(parent_field: str = "parent_name") -> Callable[[_SessionOperation], _SessionOperation]:
    """Keep a derivation source alive through context preparation and child publication."""

    def decorate(operation: _SessionOperation) -> _SessionOperation:
        @wraps(operation)
        def guarded(manager: SessionManager, *args: Any, **kwargs: Any) -> Any:
            parent_name = kwargs.get(parent_field)
            if parent_name is None and parent_field == "parent_name" and args:
                parent_name = args[0]
            if parent_name is None:
                return operation(manager, *args, **kwargs)
            root = kwargs.get("forge_root")
            if parent_field == "parent_session":
                from forge.core.ops.context import find_forge_root

                worktree = kwargs.get("worktree_path")
                search = Path(worktree) if worktree and not kwargs.get("create_worktree") else Path.cwd()
                discovered = find_forge_root(search)
                root = str(discovered) if discovered is not None else None
            entry = manager.index_store.get_session(parent_name, forge_root=root)
            parent_root = entry.forge_root or entry.worktree_path
            instance_id = manager.index_store.migrate_session_identity(parent_name, parent_root)
            from .workers import session_worker_lease

            with session_worker_lease(
                parent_root,
                parent_name,
                expected_instance_id=instance_id,
                label="derive-session",
                index_store=manager.index_store,
            ):
                return operation(manager, *args, **kwargs)

        return cast(_SessionOperation, guarded)

    return decorate


class SessionManager:
    """High-level session operations coordinating stores.

    This class provides the business logic layer between CLI commands
    and the underlying storage components.

    Attributes:
        index_store: Global session index manager.
    """

    def __init__(
        self,
        index_store: IndexStore | None = None,
    ) -> None:
        """Initialize the session manager.

        Args:
            index_store: Custom IndexStore instance. Creates default if None.
        """
        self.index_store = index_store or IndexStore()

    # -------------------------------------------------------------------------
    # Query Operations
    # -------------------------------------------------------------------------

    def list_sessions(
        self,
        include_incognito: bool = True,
        *,
        project_root_filter: str | None = None,
        forge_root_filter: str | None = None,
    ) -> list[tuple[str, SessionIndexEntry]]:
        """List sessions from the index, optionally filtered by scope.

        Args:
            include_incognito: Whether to include incognito sessions.
            project_root_filter: If set, only return entries matching this project_root.
            forge_root_filter: If set, only return entries matching this forge_root.

        Returns:
            List of (name, entry) tuples sorted by recency.
        """
        return self.index_store.list_sessions(
            include_incognito=include_incognito,
            project_root_filter=project_root_filter,
            forge_root_filter=forge_root_filter,
        )

    def get_session(self, name: str, forge_root: str | None = None) -> SessionState:
        """Get a session state by name, optionally scoped to a forge_root.

        Args:
            name: Session display name.
            forge_root: Scope to this project. Strict resolution when None.
        """
        entry = self.index_store.get_session(name, forge_root=forge_root)
        store = SessionStore(entry.forge_root or entry.worktree_path, name)

        if not store.exists():
            raise SessionNotFoundError(name)

        return store.read()

    def switch_session(self, name: str, forge_root: str | None = None) -> SessionState:
        """Load a session and update its last_accessed_at timestamp.

        Args:
            name: Session display name.
            forge_root: Scope to this project. Strict resolution when None.
        """
        entry = self.index_store.get_session(name, forge_root=forge_root)

        store = SessionStore(entry.forge_root or entry.worktree_path, name)
        if not store.exists():
            raise SessionNotFoundError(name)

        state = store.read()

        worktree_path = state.worktree.path if state.worktree is not None else entry.worktree_path
        require_session_worktree(name, worktree_path, action="launch")

        timestamp = now_iso()

        store.update(timeout_s=5.0, mutate=lambda m: setattr(m, "last_accessed_at", timestamp))

        entry_forge_root = entry.forge_root or entry.worktree_path
        self.index_store.update_session(name, last_accessed_at=timestamp, forge_root=entry_forge_root)

        return state

    def session_exists(self, name: str, forge_root: str | None = None) -> bool:
        """Check if a session exists, optionally scoped to a forge_root.

        Args:
            name: Session display name.
            forge_root: Scope to this project. Strict resolution when None.
        """
        return self.index_store.session_exists(name, forge_root=forge_root)

    def get_session_entry(self, name: str, forge_root: str | None = None) -> SessionIndexEntry:
        """Get a session index entry by name, optionally scoped.

        Args:
            name: Session display name.
            forge_root: Scope to this project. Strict resolution when None.
        """
        return self.index_store.get_session(name, forge_root=forge_root)

    def get_session_store(self, name: str, forge_root: str | None = None) -> SessionStore:
        """Get a SessionStore for a session by name.

        Args:
            name: Session name to look up.

        Returns:
            SessionStore instance for the session's worktree.

        Raises:
            SessionNotFoundError: If session doesn't exist.
            InvalidSessionNameError: If name is invalid.
        """
        entry = self.index_store.get_session(name, forge_root=forge_root)
        return SessionStore(entry.forge_root or entry.worktree_path, name)

    def resolve_project_root(self, worktree_path: str | Path) -> str:
        """Resolve the project root for a worktree path.

        For regular checkouts, this is the same as worktree_path.
        For git worktrees, this finds the main repository.

        Args:
            worktree_path: Path to the worktree.

        Returns:
            Absolute path to the project root.
        """
        from .worktree import get_main_repo_root

        try:
            return str(get_main_repo_root(Path(worktree_path)))
        except (ForgeSessionError, OSError):
            # GitNotFoundError (no git), GitWorktreeError (not a repo), OSError (fs)
            return str(Path(worktree_path).resolve())

    # -------------------------------------------------------------------------
    # Lifecycle Operations
    # -------------------------------------------------------------------------

    @_with_parent_lease("parent_session")
    def start_session(
        self,
        name: str,
        *,
        worktree_path: str | None = None,
        create_worktree: bool = False,
        branch: str | None = None,
        proxy_template: str | None = None,
        proxy_base_url: str | None = None,
        direct: bool = False,
        is_incognito: bool = False,
        launch_mode: str = LAUNCH_MODE_HOST,
        sidecar_mounts: list[str] | None = None,
        sidecar_image: str | None = None,
        direct_model: str | None = None,
        model_route: ModelRouteIntent | None = None,
        claude_session_id: str | None = None,
        codex_confirmed: CodexConfirmed | None = None,
        adoption: AdoptionConfirmed | None = None,
        confirmed_by: str | None = None,
        runtime: str = "claude_code",
        parent_session: str | None = None,
        require_uuid_unbound: bool = False,
        authority: AuthorityIntent | None = None,
        authority_explicit: bool = False,
        instance_sink: Callable[[str], None] | None = None,
    ) -> SessionState:
        """Create and register a new session.

        Creates the session state, updates the index, and sets the
        active session pointer. Does NOT invoke Claude - the CLI should
        call invoke_claude separately.

        Args:
            name: Human-friendly session name.
            worktree_path: Path to worktree (defaults to cwd).
            create_worktree: If True, create a new git worktree.
            branch: Git branch name (defaults to session name if create_worktree).
            proxy_template: Proxy template (defaults to config default when not direct).
            proxy_base_url: Proxy base URL (defaults to config default when not direct).
            direct: If True, create a direct Anthropic session with no proxy intent.
            is_incognito: Whether session auto-deletes on exit.
            launch_mode: How Forge should relaunch this session later.
            sidecar_mounts: Raw sidecar mount specs to persist for relaunch.
            sidecar_image: Optional sidecar image override to persist for relaunch.
            direct_model: Optional Claude Code env-ready direct model pin.
            model_route: Optional normalized interactive model-route selection.
            claude_session_id: Pre-seed the bound Claude conversation.
            codex_confirmed: Pre-seed `confirmed.codex`. Codex adoption passes it here
                rather than writing it afterwards so the thread id is committed by the
                same call that publishes the session: it reaches the index row (whose
                write lock enforces uniqueness), and no window exists in which an
                indexed Codex session carries `confirmed.codex = None`.
            adoption: Pre-seed `confirmed.adoption` for the same reason.
            confirmed_by: Pre-seed `confirmed.confirmed_by`/`confirmed_at`.
            runtime: Runtime registry id for launcher dispatch ("claude_code" | "codex").
            parent_session: Derivation source recorded on the state (codex start path;
                Claude resume/fork paths record it via their own child-creation flows).
            require_uuid_unbound: Re-check conversation uniqueness inside the index
                write lock, for whichever of `claude_session_id` / `codex_confirmed`
                is given. Only meaningful when binding a **pre-existing** conversation
                (`forge session adopt`); the ordinary start paths mint a fresh id that
                cannot collide.
            authority: Optional authority to apply before the first launch.
            authority_explicit: Whether authority came from an external creation flag.
            instance_sink: Receives the created instance identity for guarded follow-up writes.

        Returns:
            The created session state with candidate UUID.

        Raises:
            SessionExistsError: If session name already exists.
            UuidAlreadyBoundError: If require_uuid_unbound and the conversation is taken.
            InvalidSessionNameError: If name is invalid.
            FileNotFoundError: If no git repository found.
            BranchExistsError: If branch already exists (when create_worktree=True).
            WorktreePathExistsError: If worktree path exists (when create_worktree=True).
            InvalidBranchNameError: If explicit branch name is invalid.
        """
        if authority_explicit and authority is None:
            raise ForgeSessionError("explicit child authority requires a role")
        if authority_explicit and os.environ.get("FORGE_SESSION"):
            raise ForgeSessionError("authority-bearing session creation is only available outside a managed session")

        # Compute forge_root early for scoped collision check.
        # For worktree sessions, use launch CWD (before worktree creation).
        # For non-worktree sessions, use explicit worktree_path if provided.
        from forge.core.ops.context import find_forge_root

        launch_cwd = Path.cwd().resolve()
        _early_search = Path(worktree_path).resolve() if worktree_path and not create_worktree else launch_cwd
        _early_forge_root = find_forge_root(_early_search)
        _early_fr_str = str(_early_forge_root) if _early_forge_root else None

        if parent_session is not None and not authority_explicit:
            parent_state = self.get_session(parent_session, forge_root=_early_fr_str)
            authority = inherited_authority(parent_state.intent.authority)

        # live_session_exists, not session_exists: a bare row is crash residue that
        # create_session_txn prunes and reuses, so rejecting on it would refuse a
        # direct retry. This check only fails fast before worktree creation; the
        # transaction is what actually decides the name.
        if self.index_store.live_session_exists(name, forge_root=_early_fr_str):
            raise SessionExistsError(name)

        created_worktree = False
        worktree_branch: str | None = branch
        main_repo_root: Path | None = None

        def _rollback_worktree(*, resolved_worktree_path: str | None) -> list[str]:
            if not created_worktree or resolved_worktree_path is None:
                return []

            try:
                return _cleanup_unclaimed_worktree(
                    self.index_store,
                    Path(resolved_worktree_path),
                    branch=worktree_branch,
                    repository=main_repo_root,
                )
            except Exception as e:
                logger.debug("Worktree rollback cleanup failed (non-critical): %s", e)
                return [str(e)]

        if create_worktree:
            from .worktree import copy_runtime_config
            from .worktree import create_worktree as git_create_worktree
            from .worktree import get_main_repo_root

            main_repo_root = get_main_repo_root()

            try:
                # Create worktree first (external side effect).
                wt_result = git_create_worktree(
                    session_name=name,
                    branch=branch,
                    cwd=main_repo_root,
                )
                created_worktree = True
                worktree_path = wt_result.worktree_path
                worktree_branch = wt_result.branch

                # A tracked compatibility pin may differ in the new checkout.
                # Check the target Forge root before copying config or writing
                # any session state, and let the surrounding rollback remove
                # the checkout and branch on refusal.
                if _early_forge_root is not None:
                    try:
                        target_relative = _early_forge_root.relative_to(main_repo_root)
                    except ValueError:
                        target_relative = Path(".")
                    enforce_project_compatibility(Path(worktree_path) / target_relative)

                # Copy runtime config (best-effort; does not raise).
                copy_runtime_config(main_repo_root, Path(worktree_path))

            except Exception:
                # No Forge state has been written yet. Best-effort cleanup of any
                # created worktree/branch.
                _rollback_worktree(resolved_worktree_path=worktree_path)
                raise

        if worktree_path is None:
            worktree_path = str(Path.cwd().resolve())
        else:
            worktree_path = str(Path(worktree_path).resolve())

        # Rule 1: sessions require `forge extension enable` (.forge/ must exist).
        # For worktree sessions, use the launch CWD (captured before worktree
        # creation) — the user's nested project dir, not the bare checkout.
        from forge.core.ops.context import find_forge_root

        forge_root_search = launch_cwd if created_worktree else Path(worktree_path)
        resolved_forge_root = find_forge_root(forge_root_search)
        if resolved_forge_root is None:
            if created_worktree:
                _rollback_worktree(resolved_worktree_path=worktree_path)
            from .exceptions import ForgeNotEnabledError

            raise ForgeNotEnabledError(str(forge_root_search))

        # For worktree sessions with nested Forge projects, remap forge_root
        # into the new worktree. Root-level projects (forge_root == repo root)
        # keep the original forge_root so manifests stay under the main .forge/.
        if created_worktree and main_repo_root is not None:
            try:
                relative = resolved_forge_root.relative_to(main_repo_root)
            except ValueError:
                relative = Path(".")
            if str(relative) != ".":
                # Nested project: remap to equivalent position in new worktree
                forge_root_str = str(Path(worktree_path) / relative)
            else:
                # Root-level project: keep parent's forge_root
                forge_root_str = str(resolved_forge_root)
        else:
            forge_root_str = str(resolved_forge_root)

        # D5: Multiple sessions per worktree are allowed (per-session directories).
        # Only check that THIS session name doesn't already have a manifest.
        store = SessionStore(forge_root_str, name)
        if store.exists():
            if created_worktree:
                _rollback_worktree(resolved_worktree_path=worktree_path)
            raise SessionExistsError(name)

        # project_root is the workspace anchor (design.md §3): the git-common-dir
        # root, identical for every linked worktree of a repo, so sessions started
        # in sibling worktrees group together under `--scope workspace`. When Forge
        # created the worktree we already have it; otherwise derive it via
        # resolve_project_root() (get_main_repo_root, graceful non-git fallback) —
        # NOT find_project_root(), which returns the worktree's own root for a
        # manually-created linked worktree and silently breaks workspace grouping.
        if main_repo_root is not None:
            project_root: str | Path = main_repo_root
        else:
            project_root = self.resolve_project_root(worktree_path)
        # checkout_root = git --show-toplevel (not CWD). For worktree-created sessions
        # main_repo_root is the logical repo, not the checkout; use get_repo_root() instead.
        from .worktree import get_repo_root

        try:
            checkout_root_str: str | None = str(get_repo_root(Path(worktree_path)))
        except Exception:
            checkout_root_str = worktree_path  # Fallback if not in a git repo

        # relative_path = forge_root relative to checkout_root
        relative_path_str: str | None = None
        if forge_root_str and checkout_root_str:
            try:
                relative_path_str = str(Path(forge_root_str).relative_to(checkout_root_str))
            except ValueError:
                logger.warning(
                    "forge_root %s is not relative to checkout_root %s; defaulting to '.'",
                    forge_root_str,
                    checkout_root_str,
                )
                relative_path_str = "."

        if direct:
            template = None
            base_url = None
        else:
            template = proxy_template or DEFAULT_PROXY_TEMPLATE
            base_url = proxy_base_url or DEFAULT_PROXY_BASE_URL

        # UUID pre-seeded if provided; SessionStart hook validates it
        state = create_session_state(
            name=name,
            proxy_template=template,
            proxy_base_url=base_url,
            parent_session=parent_session,
            is_incognito=is_incognito,
            worktree_path=worktree_path,
            worktree_branch=worktree_branch,
            launch_mode=launch_mode,
            sidecar_mounts=sidecar_mounts,
            sidecar_image=sidecar_image,
            direct_model=direct_model,
            model_route=deepcopy(model_route),
            runtime=runtime,
            authority=deepcopy(authority),
        )

        if claude_session_id:
            state.confirmed.claude_session_id = claude_session_id

        if codex_confirmed is not None:
            state.confirmed.codex = codex_confirmed
        if adoption is not None:
            state.confirmed.adoption = adoption
        if confirmed_by is not None:
            state.confirmed.confirmed_by = confirmed_by
            state.confirmed.confirmed_at = now_iso()

        if create_worktree and state.worktree:
            state.worktree.is_worktree = True

        state.forge_root = forge_root_str

        # Commit phase: write Forge state only after external worktree creation succeeded.
        store = SessionStore(forge_root_str, name)

        try:
            # One transaction, row then manifest, under the index lock. The
            # live_session_exists check above runs outside any lock, so two
            # concurrent creates of one name both reach here; the transaction
            # picks the winner and the loser gets SessionExistsError without
            # touching the winner's state.
            instance_id = _publish_created_session(
                self.index_store,
                state,
                store,
                str(project_root),
                checkout_root=checkout_root_str,
                forge_root=forge_root_str,
                relative_path=relative_path_str,
                require_uuid_unbound=require_uuid_unbound,
                operation=("incognito" if is_incognito else "resume" if parent_session else "start"),
                authority_explicit=authority_explicit,
            )

            if instance_sink is not None:
                instance_sink(instance_id)
            return state

        except Exception as error:
            # Forge state publication rolls itself back. Only an externally created
            # and still-unclaimed worktree may be unwound.
            cleanup_errors = _rollback_worktree(resolved_worktree_path=worktree_path)
            if cleanup_errors:
                raise ForgeSessionError(f"{error}. Cleanup refused: {'; '.join(cleanup_errors)}") from error
            raise

    @_with_parent_lease()
    def resume_session(
        self,
        parent_name: str,
        *,
        child_name: str | None = None,
        strategy: str = "structured",
        depth: int | None = 1,
        context_limit: int | None = None,
        token_estimate_multiplier: float = 1.0,
        resume_mode: str = "transfer",
        forge_root: str | None = None,
        memory_flag: bool | None = None,
        authority: AuthorityIntent | None = None,
        authority_explicit: bool = False,
        instance_sink: Callable[[str], None] | None = None,
    ) -> tuple[SessionState, TransferResult]:
        """Create a new session derived from a parent with context assembly.

        Creates a new child session in the parent's worktree with context assembled
        from the parent's history. This is used when context approaches limits and
        the user wants to continue work with a fresh context window.

        When ``resume_mode="native"``, context assembly is skipped entirely. The
        caller is expected to launch Claude with ``--resume --fork-session`` to
        carry full conversation history natively. No system_prompt_file is generated.

        Does NOT invoke Claude - the CLI should call invoke_claude separately.

        Args:
            parent_name: Parent session name to derive from.
            child_name: Name for the child session (auto-generated if None).
            strategy: Context assembly strategy (minimal/structured/full/ai-curated).
            depth: How many ancestors to traverse (1 = parent only, None = all).
            context_limit: Context limit for budget check (required for full strategy).
            token_estimate_multiplier: Optional model-specific multiplier for heuristic budget checks.
            resume_mode: "transfer" (assemble context file) or "native" (skip assembly).

        Returns:
            Tuple of (child session state, transfer result).

        Raises:
            SessionNotFoundError: If parent session doesn't exist.
            SessionExistsError: If child_name already exists.
            InvalidSessionNameError: If name is invalid.
            ContextBudgetExceededError: If full strategy exceeds context limit.
            ValueError: If transfer mode receives an unsupported strategy.
        """
        if authority_explicit and authority is None:
            raise ForgeSessionError("explicit child authority requires a role")
        if authority_explicit and os.environ.get("FORGE_SESSION"):
            raise ForgeSessionError("authority-bearing session creation is only available outside a managed session")
        if resume_mode not in {"transfer", "native"}:
            raise ValueError(f"Unsupported resume_mode: {resume_mode}")

        parent_entry = self.index_store.get_session(parent_name, forge_root=forge_root)
        parent_forge_root = parent_entry.forge_root or parent_entry.worktree_path
        parent_store = SessionStore(parent_forge_root, parent_name)
        if not parent_store.exists():
            raise SessionNotFoundError(parent_name)

        parent_state = parent_store.read()
        from forge.policy.semantic.identity import validate_inherited_claude_trigger

        validate_inherited_claude_trigger(parent_state)
        parent_worktree_path = (
            parent_state.worktree.path if parent_state.worktree is not None else parent_entry.worktree_path
        )
        require_session_worktree(parent_name, parent_worktree_path, action="resume")

        name_was_auto = child_name is None
        if name_was_auto:
            child_name = self._generate_resume_name(parent_name, forge_root=parent_forge_root)

        assert child_name is not None  # narrowing: either provided or generated
        validate_name(child_name)

        # See start_session: row-only residue must reach the transaction, not be
        # rejected here.
        if self.index_store.live_session_exists(child_name, forge_root=parent_forge_root):
            raise SessionExistsError(child_name)

        project_root = Path(self.resolve_project_root(parent_entry.worktree_path))
        parent_artifact_root = Path(parent_entry.forge_root or parent_entry.worktree_path)

        inherited_proxy = None
        if parent_state.confirmed.started_with_proxy:
            inherited_proxy = parent_state.confirmed.started_with_proxy.template

        timestamp = now_iso()

        # --- Native resume guard: when fork --into targets different
        # forge_roots, reject native resume here. Claude Code's --resume only works
        # within the same CWD's .claude/ project. For now, child always inherits
        # parent's forge_root, so this is a no-op.

        # --- Native mode: skip transfer, return early ---
        if resume_mode == "native":
            inh_warnings_native: list[str] = []
            child_state = self._create_resume_child(
                child_name=child_name,
                parent_name=parent_name,
                parent_state=parent_state,
                parent_entry=parent_entry,
                memory_flag=memory_flag,
                authority=authority,
                authority_explicit=authority_explicit,
                warnings_sink=inh_warnings_native,
            )
            # Resolve parent transcript path for traceability (best-effort)
            transcript_artifact_path = latest_transcript_artifact_path(parent_state)

            child_state.confirmed.derivation = Derivation(
                parent_session=parent_name,
                parent_transcript=transcript_artifact_path,
                inherited_proxy=inherited_proxy,
                resume_mode="native",
                strategy=None,
                depth=1,
                resumed_at=timestamp,
                lineage=[parent_name],
                context_file=None,
                parent_forge_root=parent_entry.forge_root or parent_entry.worktree_path,
                parent_project_root=parent_entry.project_root,
            )

            transfer_result = TransferResult(
                context_file=None,
                context_file_rel=None,
                transcript_artifact_path=transcript_artifact_path,
                token_estimate=None,
                lineage=[parent_name],
                warnings=inh_warnings_native,
            )

            self._persist_resume_child(
                child_state=child_state,
                child_name=child_name,
                parent_name=parent_name,
                parent_entry=parent_entry,
                project_root=project_root,
                name_was_auto=name_was_auto,
                authority_explicit=authority_explicit,
                instance_sink=instance_sink,
            )
            return child_state, transfer_result

        # --- Transfer mode: assemble context from parent history ---
        resume_strategy = parse_transfer_context_strategy(strategy)

        if resume_strategy == ResumeStrategy.FULL and context_limit is not None:
            transcript_path, _artifact_path = resolve_transfer_transcript_source(
                parent_state,
                parent_artifact_root,
            )
            if transcript_path is not None and transcript_path.is_file():
                token_estimate = estimate_transcript_tokens(
                    transcript_path,
                    multiplier=token_estimate_multiplier,
                )
                if token_estimate > context_limit:
                    raise ContextBudgetExceededError(token_estimate, context_limit)

        def get_session_safe(session_name: str) -> SessionState | None:
            try:
                return self.get_session(session_name, forge_root=parent_forge_root)
            except SessionNotFoundError:
                return None

        transfer_result = assemble_transfer_context(
            parent_name=parent_name,
            parent_state=parent_state,
            forge_root=parent_artifact_root,
            strategy=resume_strategy,
            depth=depth,
            get_session=get_session_safe,
            child_name=child_name,
        )

        # claude_session_id stays None until the SessionStart hook fires
        inh_warnings_transfer: list[str] = []
        child_state = self._create_resume_child(
            child_name=child_name,
            parent_name=parent_name,
            parent_state=parent_state,
            parent_entry=parent_entry,
            memory_flag=memory_flag,
            authority=authority,
            authority_explicit=authority_explicit,
            warnings_sink=inh_warnings_transfer,
        )

        child_state.confirmed.derivation = Derivation(
            parent_session=parent_name,
            parent_transcript=transfer_result.transcript_artifact_path,
            inherited_proxy=inherited_proxy,
            resume_mode="transfer",
            strategy=resume_strategy.value,
            depth=len(transfer_result.lineage) if depth is None else depth,
            resumed_at=timestamp,
            lineage=transfer_result.lineage,
            context_file=transfer_result.context_file_rel,
            parent_forge_root=parent_entry.forge_root or parent_entry.worktree_path,
            parent_project_root=parent_entry.project_root,
        )

        final_child_name = self._persist_resume_child(
            child_state=child_state,
            child_name=child_name,
            parent_name=parent_name,
            parent_entry=parent_entry,
            project_root=project_root,
            name_was_auto=name_was_auto,
            authority_explicit=authority_explicit,
            instance_sink=instance_sink,
        )
        if final_child_name != child_name:
            transfer_result.context_file = child_path(parent_artifact_root, parent_name, final_child_name)
            transfer_result.context_file_rel = child_path_rel(parent_name, final_child_name)
        transfer_result.warnings.extend(inh_warnings_transfer)
        return child_state, transfer_result

    def _create_resume_child(
        self,
        *,
        child_name: str,
        parent_name: str,
        parent_state: SessionState,
        parent_entry: SessionIndexEntry,
        memory_flag: bool | None = None,
        warnings_sink: list[str] | None = None,
        authority: AuthorityIntent | None = None,
        authority_explicit: bool = False,
    ) -> SessionState:
        """Create a child SessionState for resume (shared by native and transfer)."""
        # A confirmed proxy describes an earlier launch; current routing intent
        # may already have been cleared or replaced by an explicit resume.
        proxy = parent_state.intent.proxy
        child_state = create_session_state(
            name=child_name,
            proxy_template=proxy.template if proxy else None,
            proxy_base_url=proxy.base_url if proxy else None,
            is_incognito=parent_state.is_incognito,
            worktree_path=parent_entry.worktree_path,
            worktree_branch=(parent_state.worktree.branch if parent_state.worktree else None),
        )

        _inherit_intent_fields(child_state, parent_state)
        if authority_explicit:
            child_state.intent.authority = deepcopy(authority)

        child_state.parent_session = parent_name
        child_state.is_fork = False  # Same worktree, context continuation (not a fork)
        child_state.forge_root = parent_entry.forge_root or parent_state.forge_root

        from .memory_inheritance import apply_memory_inheritance

        inh_warnings = apply_memory_inheritance(
            parent_state=parent_state,
            child_state=child_state,
            memory_flag=memory_flag,
        )
        if warnings_sink is not None:
            warnings_sink.extend(inh_warnings)

        return child_state

    def _persist_resume_child(
        self,
        *,
        child_state: SessionState,
        child_name: str,
        parent_name: str,
        parent_entry: SessionIndexEntry,
        project_root: Path,
        name_was_auto: bool,
        authority_explicit: bool,
        instance_sink: Callable[[str], None] | None = None,
    ) -> str:
        """Write child session to disk and index (shared by native and transfer).

        Race protection: if an auto-generated name collides in the commit
        transaction (concurrent resume) -- from either its index-side row check or
        its manifest callback -- retry once with a fresh timestamp suffix.

        Returns the final persisted child name, which may differ from the
        original auto-generated name after a retry.
        """
        parent_forge_root = parent_entry.forge_root or parent_entry.worktree_path
        for attempt in range(2):
            child_store = SessionStore(parent_forge_root, child_name)
            try:
                # Claim and publish under one index lock, row then manifest. With a
                # deterministic auto-name (<parent>-resumed), a concurrent resume can be
                # racing for the same one; the transaction picks the winner and tells this
                # loser it never owned the name. Both claims can still report the collision
                # -- the index row check and create_exclusive -- and both surface as
                # SessionExistsError, so both feed the one retry below.
                instance_id = _publish_created_session(
                    self.index_store,
                    child_state,
                    child_store,
                    str(project_root),
                    checkout_root=parent_entry.checkout_root,
                    forge_root=parent_entry.forge_root,
                    relative_path=parent_entry.relative_path,
                    operation="resume",
                    authority_explicit=authority_explicit,
                )
            except SessionExistsError:
                # Only the curated transfer snapshot (children/<child>.md, written by
                # assemble_transfer_context before this call) may be an orphan to reclaim,
                # and only when no live session owns the name.
                if not name_was_auto or attempt > 0:
                    raise

                # live_session_exists: a bare row is residue, not a live owner, and
                # treating it as one would suppress the snapshot reclaim below.
                winner_owns = child_store.exists() or self.index_store.live_session_exists(
                    child_name, forge_root=parent_entry.forge_root
                )
                derivation = child_state.confirmed.derivation
                if derivation is not None and derivation.resume_mode == "transfer" and not winner_owns:
                    orphan_context = child_path(Path(parent_forge_root), parent_name, child_name)
                    generated_context = generated_path(Path(parent_forge_root), parent_name)
                    try:
                        if (
                            orphan_context.is_file()
                            and generated_context.is_file()
                            and orphan_context.read_bytes() == generated_context.read_bytes()
                        ):
                            orphan_context.unlink()
                    except OSError:
                        logger.debug(
                            "Could not remove orphaned retry context file %s",
                            orphan_context,
                            exc_info=True,
                        )

                child_name = self._generate_resume_name(parent_name, forge_root=parent_forge_root)
                validate_name(child_name)
                child_state.name = child_name
                if derivation is not None and derivation.resume_mode == "transfer":
                    ensure_child(Path(parent_forge_root), parent_name, child_name)
                    derivation.context_file = child_path_rel(parent_name, child_name)
                continue

            if instance_sink is not None:
                instance_sink(instance_id)
            break

        return child_name

    def _load_existing_fork_target(
        self,
        *,
        fork_name: str,
        target_forge_root: str,
    ) -> tuple[SessionStore, SessionIndexEntry | None, SessionState | None, str | None]:
        """Return the existing manifest/index state for a fork target.

        Uses the index self-healing path so stale index-only entries do not
        block retries.
        """
        target_store = SessionStore(target_forge_root, fork_name)

        try:
            target_entry = self.index_store.get_session(fork_name, forge_root=target_forge_root)
        except SessionNotFoundError:
            target_entry = None

        target_state: SessionState | None = None
        target_instance_id: str | None = None
        if target_store.exists():
            target_instance_id = target_store.review_identity()
            try:
                target_state = target_store.read()
            except (ManifestCorruptedError, ManifestValidationError):
                target_state = None
            if target_store.review_identity() != target_instance_id or (
                target_entry is not None
                and target_entry.instance_id is not None
                and target_entry.instance_id != target_instance_id
            ):
                raise ForgeSessionError(f"Session '{fork_name}' changed before replacement; retained its new owner")

        return target_store, target_entry, target_state, target_instance_id

    def _can_force_replace_fork_target(
        self,
        *,
        fork_name: str,
        parent_name: str,
        target_forge_root: str,
        existing_state: SessionState | None,
        expected_worktree_path: str,
        expected_branch: str,
        expected_is_worktree: bool,
        expected_owns_worktree: bool,
    ) -> bool:
        """Return True when --force is replacing the stale child it created.

        Replacement is intentionally narrow: the existing session must already
        be a fork from this parent, point at the same target checkout/branch,
        and be inactive.
        """
        if not fork_target_matches_replacement(
            existing_state=existing_state,
            parent_name=parent_name,
            target_forge_root=target_forge_root,
            expected_worktree_path=expected_worktree_path,
            expected_branch=expected_branch,
            expected_is_worktree=expected_is_worktree,
            expected_owns_worktree=expected_owns_worktree,
        ):
            return False

        try:
            from .active import ActiveSessionStore

            if ActiveSessionStore().get_session(fork_name, forge_root=target_forge_root) is not None:
                return False
        except Exception as e:
            logger.debug("Unable to verify active state for fork target '%s': %s", fork_name, e)
            return False

        return True

    @_with_parent_lease()
    def fork_session(
        self,
        parent_name: str,
        fork_name: str | None = None,
        *,
        direct: bool = False,
        is_incognito: bool = False,
        create_worktree: bool = False,
        branch: str | None = None,
        into_path: str | None = None,
        forge_root: str | None = None,
        force: bool = False,
        memory_flag: bool | None = None,
        resume_mode: str | None = None,
        warnings_sink: list[str] | None = None,
        authority: AuthorityIntent | None = None,
        authority_explicit: bool = False,
        instance_sink: Callable[[str], None] | None = None,
    ) -> tuple[SessionState, SessionState]:
        """Fork an existing session.

        By default the fork shares the parent's directory so Claude's
        ``--resume --fork-session`` can find the conversation (conversations
        are project-scoped).  Pass ``create_worktree=True`` for code
        isolation in a separate git worktree, or ``into_path`` to land
        in an existing worktree directory.

        Args:
            parent_name: Session name to fork from.
            fork_name: Name for the fork (auto-generated if None).
            is_incognito: Whether the fork should auto-delete on exit.
            create_worktree: Create a git worktree for the fork (default False).
            branch: Override branch name (only used when create_worktree=True).
            into_path: Fork into an existing worktree directory (normalized checkout root).
            force: Replace only a conflicting target that is provably the same
                stale fork (same parent + same target) and inactive. Hard
                constraints still apply: BranchInUseError,
                BranchNotMergedError, and non-worktree paths.

        Returns:
            Tuple of (parent_manifest, fork_manifest).

        Raises:
            SessionNotFoundError: If parent doesn't exist.
            CannotForkIncognitoError: If parent is incognito.
            CannotForkCodexParentError: If parent is a Codex session (fork is Claude-only).
            SessionExistsError: If fork_name already exists (and not force).
            BranchExistsError: If branch already exists (create_worktree only, not force).
            WorktreePathExistsError: If worktree path exists (create_worktree only, not force).
            BranchInUseError: If branch is checked out elsewhere (force only).
            BranchNotMergedError: If branch has unmerged work (force only).
        """
        if authority_explicit and authority is None:
            raise ForgeSessionError("explicit child authority requires a role")
        if authority_explicit and os.environ.get("FORGE_SESSION"):
            raise ForgeSessionError("authority-bearing session creation is only available outside a managed session")
        parent = self.get_session(parent_name, forge_root=forge_root)
        from forge.policy.semantic.identity import validate_inherited_claude_trigger

        validate_inherited_claude_trigger(parent)
        parent_entry = self.index_store.get_session(parent_name, forge_root=forge_root)
        parent_forge_root = parent_entry.forge_root or parent_entry.worktree_path

        parent_worktree_path_str = parent.worktree.path if parent.worktree is not None else parent_entry.worktree_path
        require_session_worktree(parent_name, parent_worktree_path_str, action="fork")

        if parent.is_incognito:
            raise CannotForkIncognitoError(parent_name)

        # fork is Claude-only: the post-fork resume keys on the parent's claude_session_id,
        # which a Codex session never has, and _inherited_launch_intent would copy runtime=codex
        # into the child. Reject here -- before any child manifest/worktree is created -- so no
        # caller (not just the CLI preflight) can leave orphaned child state. See review finding #1.
        parent_launch = parent.intent.launch
        if parent_launch is not None and parent_launch.runtime == "codex":
            raise CannotForkCodexParentError(parent_name)

        # Validate the parent artifact collection before worktree creation or
        # target replacement. The shared selector is strict durable-state input;
        # discovering corruption after those side effects would leak Git state.
        parent_transcript_artifact_path = latest_transcript_artifact_path(parent)

        if fork_name is None:
            existing = {name for name, _ in self.list_sessions(forge_root_filter=parent_forge_root)}
            fork_name = generate_unique_name(existing)

        parent_worktree_path = Path(parent.worktree.path) if parent.worktree else Path.cwd()
        parent_relative = parent_entry.relative_path or "."

        target_forge_root: str | None = None
        target_store: SessionStore | None = None
        target_entry: SessionIndexEntry | None = None
        target_state: SessionState | None = None
        target_instance_id: str | None = None
        replace_stale_target_state = False
        created_worktree = False
        rollback_worktree_path: str | None = None
        rollback_worktree_branch: str | None = None
        rollback_repo_root: Path | None = None
        replacement_start_point: str | None = None
        removed_target_root: str | None = None

        def _rollback_created_worktree() -> list[str]:
            if not created_worktree or rollback_worktree_path is None:
                return []
            try:
                cleanup_errors = _cleanup_unclaimed_worktree(
                    self.index_store,
                    Path(rollback_worktree_path),
                    branch=rollback_worktree_branch,
                    repository=rollback_repo_root,
                )
                if cleanup_errors:
                    logger.warning(
                        "Fork rollback cleanup incomplete for '%s': %s",
                        rollback_worktree_path,
                        "; ".join(cleanup_errors),
                    )
                return cleanup_errors
            except Exception as e:
                logger.warning(
                    "Fork rollback cleanup failed for '%s': %s",
                    rollback_worktree_path,
                    e,
                )
                return [str(e)]

        try:
            if into_path is not None:
                # Fork into an existing worktree (--into): land at the equivalent
                # forge_root position in the target checkout.
                from .worktree import get_main_repo_root

                target_checkout_root = into_path  # Already normalized to checkout root by CLI
                target_forge_root = str(Path(target_checkout_root) / parent_relative)

                # Validate: target must have Forge enabled at that position
                if not (Path(target_forge_root) / ".forge").is_dir():
                    raise ForgeSessionError(
                        f"No Forge project at {target_forge_root}. "
                        f"Run 'forge extension enable' in {target_forge_root} first, "
                        "or use --worktree to create a new checkout with auto-enable."
                    )

                enforce_project_compatibility(target_forge_root)

                fork_worktree_path = target_checkout_root
                fork_branch: str | None = branch  # CLI resolves branch from git
                project_root = str(get_main_repo_root(Path(into_path)))
                is_into = True

                assert target_forge_root is not None
                target_store, target_entry, target_state, target_instance_id = self._load_existing_fork_target(
                    fork_name=fork_name,
                    target_forge_root=target_forge_root,
                )
                target_conflict_exists = target_store.exists() or target_entry is not None
                if target_conflict_exists:
                    if not force:
                        raise SessionExistsError(fork_name)

                    replace_stale_target_state = self._can_force_replace_fork_target(
                        fork_name=fork_name,
                        parent_name=parent_name,
                        target_forge_root=target_forge_root,
                        existing_state=target_state,
                        expected_worktree_path=fork_worktree_path,
                        expected_branch=fork_branch or fork_name,
                        expected_is_worktree=True,
                        expected_owns_worktree=False,
                    )
                    if not replace_stale_target_state:
                        raise SessionExistsError(fork_name)
            elif create_worktree:
                from .worktree import (
                    copy_runtime_config,
                )
                from .worktree import create_worktree as git_create_worktree
                from .worktree import (
                    get_main_repo_root,
                    preflight_create_worktree,
                    read_file_at_revision,
                    resolve_commit,
                    resolve_worktree_path,
                    sanitize_branch_name,
                )

                repo_root = get_main_repo_root(parent_worktree_path)
                target_worktree_path = resolve_worktree_path(repo_root, fork_name)
                target_forge_root = str(target_worktree_path / parent_relative)
                target_branch = branch or sanitize_branch_name(fork_name)
                target_store, target_entry, target_state, target_instance_id = self._load_existing_fork_target(
                    fork_name=fork_name,
                    target_forge_root=target_forge_root,
                )
                target_conflict_exists = target_store.exists() or target_entry is not None
                if target_conflict_exists:
                    if not force:
                        raise SessionExistsError(fork_name)

                    replace_stale_target_state = self._can_force_replace_fork_target(
                        fork_name=fork_name,
                        parent_name=parent_name,
                        target_forge_root=target_forge_root,
                        existing_state=target_state,
                        expected_worktree_path=str(target_worktree_path),
                        expected_branch=target_branch,
                        expected_is_worktree=True,
                        expected_owns_worktree=True,
                    )
                    if not replace_stale_target_state:
                        raise SessionExistsError(fork_name)

                    # Force replacement destroys the existing checkout and its
                    # auto-derived branch. Refuse against both that checkout's pin
                    # and the exact HEAD commit that will seed its replacement
                    # before authorizing the destructive Git step.
                    enforce_project_compatibility(target_forge_root)
                    replacement_start_point = resolve_commit(repo_root)
                    prospective_pin = read_file_at_revision(
                        Path(parent_relative) / ".forge" / "project.toml",
                        revision=replacement_start_point,
                        cwd=repo_root,
                    )
                    if prospective_pin is not None:
                        enforce_project_compatibility_toml(
                            prospective_pin,
                            path=Path(target_forge_root) / ".forge" / "project.toml",
                        )
                    from .deletion import apply_session_deletion, plan_session_deletion

                    replacement = plan_session_deletion(
                        self.index_store,
                        fork_name,
                        forge_root=target_forge_root,
                        delete_worktree=True,
                        delete_branch=True,
                        force=True,
                    )
                    if replacement.state != target_state or replacement.instance_id != target_instance_id:
                        raise ForgeSessionError(
                            f"Session '{fork_name}' changed before replacement; retained its new owner"
                        )
                    if replacement.worktree_path != str(target_worktree_path):
                        raise ForgeSessionError(
                            f"Cannot replace fork '{fork_name}': its worktree is shared or no longer owned"
                        )
                    preflight_create_worktree(
                        fork_name,
                        branch,
                        repo_root,
                        force=True,
                        replace_owned_stale_state=True,
                    )
                    # Delete while the original manifest can still authorize the
                    # content and checkout. A later creator must face a fresh,
                    # non-forcing Git create instead of another destructive retry.
                    apply_session_deletion(self.index_store, replacement)
                    removed_target_root = target_forge_root
                    replace_stale_target_state = False
                wt_result = git_create_worktree(
                    session_name=fork_name,
                    branch=branch,
                    cwd=repo_root,
                    start_point=replacement_start_point,
                )
                created_worktree = True
                rollback_worktree_path = wt_result.worktree_path
                rollback_worktree_branch = wt_result.branch
                rollback_repo_root = repo_root
                target_forge_root = str(Path(wt_result.worktree_path) / parent_relative)
                enforce_project_compatibility(target_forge_root)
                copy_runtime_config(repo_root, Path(wt_result.worktree_path))

                fork_worktree_path = wt_result.worktree_path
                fork_branch = wt_result.branch
                project_root = str(repo_root)
                is_into = False
            else:
                target_forge_root = parent_forge_root
                fork_worktree_path = str(parent_worktree_path)
                fork_branch = parent.worktree.branch if parent.worktree else None
                # Workspace anchor: git-common-dir root (groups sibling worktrees),
                # not the per-worktree root find_project_root() would return.
                project_root = self.resolve_project_root(fork_worktree_path)
                is_into = False
                assert target_forge_root is not None
                target_store, target_entry, target_state, target_instance_id = self._load_existing_fork_target(
                    fork_name=fork_name,
                    target_forge_root=target_forge_root,
                )
                target_conflict_exists = target_store.exists() or target_entry is not None
                if target_conflict_exists:
                    if not force:
                        raise SessionExistsError(fork_name)

                    replace_stale_target_state = self._can_force_replace_fork_target(
                        fork_name=fork_name,
                        parent_name=parent_name,
                        target_forge_root=target_forge_root,
                        existing_state=target_state,
                        expected_worktree_path=fork_worktree_path,
                        expected_branch=fork_branch or fork_name,
                        expected_is_worktree=False,
                        expected_owns_worktree=False,
                    )
                    if not replace_stale_target_state:
                        raise SessionExistsError(fork_name)

            if direct:
                fork_proxy_template = None
                fork_proxy_base_url = None
            else:
                fork_proxy_template = parent.intent.proxy.template if parent.intent.proxy else None
                fork_proxy_base_url = parent.intent.proxy.base_url if parent.intent.proxy else None

            fork_state = create_session_state(
                name=fork_name,
                proxy_template=fork_proxy_template,
                proxy_base_url=fork_proxy_base_url,
                parent_session=parent_name,
                is_fork=True,
                is_incognito=is_incognito,
                worktree_path=fork_worktree_path,
                worktree_branch=fork_branch,
            )

            _inherit_intent_fields(fork_state, parent)
            if authority_explicit:
                fork_state.intent.authority = deepcopy(authority)
            # Direct mode: force host launch (sidecar requires a proxy)
            if direct and fork_state.intent.launch and fork_state.intent.launch.mode != LAUNCH_MODE_HOST:
                fork_state.intent.launch.mode = LAUNCH_MODE_HOST
                fork_state.intent.launch.sidecar = None

            if (create_worktree or is_into) and fork_state.worktree:
                fork_state.worktree.is_worktree = True
            if is_into and fork_state.worktree:
                fork_state.worktree.owns_worktree = False

            # Compute identity fields for the fork target.
            fork_forge_root: str | None
            fork_relative_path: str | None
            if is_into:
                assert target_forge_root is not None
                fork_forge_root = target_forge_root
                fork_checkout_root = fork_worktree_path
                fork_relative_path = parent_entry.relative_path or "."
            elif create_worktree:
                # Fresh worktree has no .forge/; propagate parent's relative position.
                parent_relative = parent_entry.relative_path or "."
                fork_forge_root = str(Path(fork_worktree_path) / parent_relative)
                fork_checkout_root = fork_worktree_path
                fork_relative_path = parent_relative
            else:
                # Same-worktree fork: auto-detect
                from forge.core.ops.context import find_forge_root

                fork_forge_root_path = find_forge_root(Path(fork_worktree_path))
                fork_forge_root = str(fork_forge_root_path) if fork_forge_root_path else None
                fork_checkout_root = fork_worktree_path
                fork_relative_path = None
                if fork_forge_root and fork_checkout_root:
                    try:
                        fork_relative_path = str(Path(fork_forge_root).relative_to(fork_checkout_root))
                    except ValueError:
                        fork_relative_path = "."

            fork_state.forge_root = fork_forge_root

            from .memory_inheritance import apply_memory_inheritance

            inh_warnings = apply_memory_inheritance(
                parent_state=parent,
                child_state=fork_state,
                memory_flag=memory_flag,
            )

            # Opt-in native-relocate (worktree/--into only) overrides the transfer default. Cross-CWD
            # forks default to transfer; same-directory forks default to native UNLESS the caller asks
            # for transfer (resume_mode == "transfer", auto-switched or explicit), which opts them into
            # a same-directory transfer fork. Recording the baseline here keeps derivation correct even
            # if command core's best-effort _persist_fork_transfer_derivation refinement later fails.
            if resume_mode == "native-relocate" and (create_worktree or is_into):
                fork_resume_mode = "native-relocate"
            elif create_worktree or is_into or resume_mode == "transfer":
                fork_resume_mode = "transfer"
            else:
                fork_resume_mode = "native"
            # For transfer-mode forks the per-child file is created lazily at launch
            # (see _generate_parent_transfer_context). We pre-record the reference
            # here so GC knows the fork's child file belongs to this session, even
            # if launch happens later.
            fork_context_file_rel = child_path_rel(parent_name, fork_name) if fork_resume_mode == "transfer" else None
            # native-relocate copies the parent transcript into the child's encoded dir; record the
            # parent UUID so cleanup can remove that copy (dir-scoped to the child, never the parent's).
            fork_relocated_parent = (
                parent.confirmed.claude_session_id if fork_resume_mode == "native-relocate" else None
            )
            fork_state.confirmed.derivation = Derivation(
                parent_session=parent_name,
                parent_transcript=parent_transcript_artifact_path,
                inherited_proxy=fork_proxy_template,
                resume_mode=fork_resume_mode,
                strategy=None,
                depth=1,
                resumed_at=now_iso(),
                lineage=[parent_name],
                context_file=fork_context_file_rel,
                relocated_parent_session_id=fork_relocated_parent,
                parent_forge_root=parent_entry.forge_root or parent_entry.worktree_path,
                parent_project_root=parent_entry.project_root,
            )

            fork_store = SessionStore(fork_forge_root or fork_worktree_path, fork_name)
            # Same-checkout forks retain the checkout while replacing their
            # stale state. Worktree forks already completed shared cleanup.
            if replace_stale_target_state:
                effective_fork_root = fork_forge_root or fork_worktree_path
                try:
                    if target_instance_id is not None:
                        self.delete_session(
                            fork_name,
                            delete_worktree=False,
                            delete_branch=False,
                            force=True,
                            forge_root=effective_fork_root,
                            expected_instance_id=target_instance_id,
                        )
                    else:
                        from .deletion import (
                            apply_session_deletion,
                            plan_session_deletion,
                        )

                        replacement = plan_session_deletion(
                            self.index_store,
                            fork_name,
                            forge_root=effective_fork_root,
                            delete_worktree=False,
                            force=True,
                        )
                        if replacement.state != target_state or replacement.instance_id != target_instance_id:
                            raise ForgeSessionError(
                                f"Session '{fork_name}' changed before replacement; retained its new owner"
                            )
                        apply_session_deletion(self.index_store, replacement)
                except SessionNotFoundError:
                    pass
                else:
                    removed_target_root = effective_fork_root

                # Publication below is exclusive. A replacement that claimed the
                # freed name must survive; do not perform a second name-only delete.
                if SessionStore(effective_fork_root, fork_name).exists():
                    raise SessionExistsError(fork_name)

            if warnings_sink is not None:
                warnings_sink.extend(inh_warnings)

            # Both branches reach here with no manifest: a stale target was just
            # deleted above, and a fresh fork_name has none. create_exclusive keeps
            # that true under concurrency, and the transaction's row check makes
            # the loser fail before it can touch the winner's manifest.
            instance_id = _publish_created_session(
                self.index_store,
                fork_state,
                fork_store,
                project_root,
                checkout_root=fork_checkout_root,
                forge_root=fork_forge_root,
                relative_path=fork_relative_path,
                operation="incognito" if is_incognito else "fork",
                authority_explicit=authority_explicit,
            )

            if instance_sink is not None:
                instance_sink(instance_id)
            return parent, fork_state

        except Exception as error:
            # Only compensate this invocation's new worktree, and only while no
            # newer session owns it. Completed deletion has no content backup.
            cleanup_errors = _rollback_created_worktree() if create_worktree else []
            if removed_target_root is not None:
                message = (
                    f"{error}. Previous fork '{fork_name}' at {removed_target_root} and its Forge content "
                    "were already removed before replacement failed. "
                    "Inspect 'forge session list --scope all' before retrying the fork. "
                    "Recover previous Forge content from a backup if needed."
                )
                if cleanup_errors:
                    message += f" Cleanup refused: {'; '.join(cleanup_errors)}"
                raise ForgeSessionError(message) from error
            if cleanup_errors:
                status = "Rollback incomplete" if isinstance(error, ProjectCompatibilityError) else "Cleanup refused"
                raise ForgeSessionError(f"{error}. {status}: {'; '.join(cleanup_errors)}") from error
            raise

    @_with_parent_lease()
    def relaunch_session(
        self,
        parent_name: str,
        *,
        child_name: str | None = None,
        forge_root: str | None = None,
    ) -> tuple[SessionState, SessionState]:
        """Create a child session for relaunching a previously-used parent.

        Lightweight derivation: inherits intent/overrides/proxy, sets
        parent_session lineage. Does NOT pre-seed claude_session_id
        (launch-owned). Does NOT assemble context (unlike resume_session).

        The caller should launch Claude with ``--resume --fork-session``
        using the parent's claude_session_id so the conversation carries
        over into a distinct new Claude UUID.

        Args:
            parent_name: Session to relaunch.
            child_name: Name for the child (auto-generated if None).

        Returns:
            Tuple of (parent_state, child_state).

        Raises:
            SessionNotFoundError: If parent doesn't exist.
        """
        parent = self.get_session(parent_name, forge_root=forge_root)
        from forge.policy.semantic.identity import validate_inherited_claude_trigger

        validate_inherited_claude_trigger(parent, preserve_overrides=True)
        parent_entry = self.index_store.get_session(parent_name, forge_root=forge_root)
        parent_forge_root = parent_entry.forge_root or parent_entry.worktree_path

        parent_worktree_path = parent.worktree.path if parent.worktree is not None else parent_entry.worktree_path
        require_session_worktree(parent_name, parent_worktree_path, action="launch")

        if child_name is None:
            child_name = self._generate_relaunch_name(forge_root=parent_forge_root)

        # See start_session: row-only residue must reach the transaction, not be
        # rejected here.
        if self.index_store.live_session_exists(child_name, forge_root=parent_forge_root):
            raise SessionExistsError(child_name)

        parent_worktree_path = parent_entry.worktree_path
        project_root = parent_entry.project_root

        proxy_template = parent.intent.proxy.template if parent.intent.proxy else None
        proxy_base_url = parent.intent.proxy.base_url if parent.intent.proxy else None

        child_state = create_session_state(
            name=child_name,
            proxy_template=proxy_template,
            proxy_base_url=proxy_base_url,
            parent_session=parent_name,
            is_fork=True,
            is_incognito=parent.is_incognito,
            worktree_path=parent_worktree_path,
            worktree_branch=parent.worktree.branch if parent.worktree else None,
        )

        child_state.overrides = deepcopy(parent.overrides)
        _inherit_intent_fields(child_state, parent)

        child_state.forge_root = parent_entry.forge_root or parent.forge_root

        child_store = SessionStore(parent_entry.forge_root or parent_worktree_path, child_name)
        # No rollback block: the transaction removes its own row, and the manifest
        # write is its last durable action, so a failure leaves neither behind.
        _publish_created_session(
            self.index_store,
            child_state,
            child_store,
            project_root,
            checkout_root=parent_entry.checkout_root,
            forge_root=parent_entry.forge_root,
            relative_path=parent_entry.relative_path,
            operation="resume",
            authority_explicit=False,
        )

        return parent, child_state

    def _generate_relaunch_name(self, *, forge_root: str) -> str:
        """Generate a unique name for a relaunched session (project-scoped)."""
        existing = {name for name, _ in self.list_sessions(forge_root_filter=forge_root)}
        return generate_unique_name(existing)

    def _generate_resume_name(self, parent_name: str, forge_root: str | None = None) -> str:
        """Generate a unique name for a resumed session (project-scoped).

        Checks the manifest as well as the index: the manifest is what actually
        reserves a name (see SessionStore.create_exclusive), and an index row can
        be pruned or lag behind one. Consulting only the index would hand the
        collision retry the same taken name it just failed on.
        """
        base_name = f"{parent_name}-resumed"
        if not self._name_is_taken(base_name, forge_root=forge_root):
            return base_name

        from datetime import datetime

        suffix = datetime.now().strftime("%H%M%S")
        return f"{parent_name}-resumed-{suffix}"

    def _name_is_taken(self, name: str, *, forge_root: str | None) -> bool:
        """Whether a session name is claimed by a manifest or an index row."""
        if forge_root and SessionStore(forge_root, name).exists():
            return True
        return self.index_store.session_exists(name, forge_root=forge_root)

    def _find_co_resident_sessions(
        self,
        worktree_path: str,
        exclude: tuple[str, str],
        *,
        sessions: Iterable[tuple[str, SessionIndexEntry]] | None = None,
    ) -> list[str]:
        """Find other sessions living in the same worktree directory.

        Actual cleanup defaults to the self-healing list. Pre-confirmation planners
        supply a non-mutating, manifest-backed snapshot instead.
        """
        normalized = str(Path(worktree_path).resolve())
        exclude_name, exclude_forge_root = exclude
        normalized_exclude_root = str(Path(exclude_forge_root).resolve())
        session_entries = sessions if sessions is not None else self.index_store.list_sessions()
        return [
            name
            for name, entry in session_entries
            if str(Path(entry.worktree_path).resolve()) == normalized
            and (name, str(Path(entry.root).resolve())) != (exclude_name, normalized_exclude_root)
        ]

    def plan_worktree_cleanup(
        self,
        name: str,
        state: SessionState,
        *,
        delete_worktree: bool,
        forge_root: str,
        sessions: Iterable[tuple[str, SessionIndexEntry]] | None = None,
    ) -> WorktreeCleanupPlan:
        """Plan cleanup from the current index or a simulated remaining-session snapshot."""
        worktree = state.worktree
        if worktree is None:
            return WorktreeCleanupPlan(remove=False, reason="not_worktree")
        return self._plan_worktree_cleanup_fields(
            name,
            delete_worktree=delete_worktree,
            path=worktree.path,
            is_worktree=worktree.is_worktree,
            owns_worktree=getattr(worktree, "owns_worktree", True),
            forge_root=forge_root,
            sessions=self.index_store.peek_sessions() if sessions is None else sessions,
        )

    def _plan_worktree_cleanup_fields(
        self,
        name: str,
        *,
        delete_worktree: bool,
        path: str,
        is_worktree: bool,
        owns_worktree: bool,
        forge_root: str,
        sessions: Iterable[tuple[str, SessionIndexEntry]] | None = None,
    ) -> WorktreeCleanupPlan:
        if not delete_worktree:
            return WorktreeCleanupPlan(remove=False, reason="requested_keep")
        if not is_worktree:
            return WorktreeCleanupPlan(remove=False, reason="not_worktree")
        exclude = (name, forge_root)
        if sessions is None:
            co_residents = tuple(self._find_co_resident_sessions(path, exclude=exclude))
        else:
            co_residents = tuple(self._find_co_resident_sessions(path, exclude=exclude, sessions=sessions))
        if co_residents:
            return WorktreeCleanupPlan(remove=False, reason="shared", co_residents=co_residents)
        if not owns_worktree:
            return WorktreeCleanupPlan(remove=False, reason="not_owned")
        return WorktreeCleanupPlan(remove=True, reason="owned")

    def delete_session(
        self,
        name: str,
        *,
        delete_worktree: bool = True,
        delete_branch: bool = False,
        force: bool = False,
        forge_root: str | None = None,
        expected_instance_id: str | None = None,
    ) -> None:
        """Remove the session and its unreferenced Forge content, preserving native files."""
        from .deletion import apply_session_deletion, plan_session_deletion

        plan = plan_session_deletion(
            self.index_store,
            name,
            forge_root=forge_root,
            delete_worktree=delete_worktree,
            delete_branch=delete_branch,
            force=force,
        )
        if expected_instance_id is not None and plan.instance_id != expected_instance_id:
            raise ForgeSessionError(f"Session '{name}' changed before cleanup; retained its replacement")
        apply_session_deletion(self.index_store, plan)

    def purge_session(
        self,
        name: str,
        *,
        delete_worktree: bool = True,
        delete_branch: bool = False,
        force: bool = False,
        forge_root: str | None = None,
        expected_instance_id: str | None = None,
    ) -> None:
        """Remove admitted Forge content and verified native files for an inactive session."""
        from .deletion import apply_session_deletion, plan_session_deletion

        plan = plan_session_deletion(
            self.index_store,
            name,
            forge_root=forge_root,
            purge=True,
            delete_worktree=delete_worktree,
            delete_branch=delete_branch,
            force=force,
        )
        if expected_instance_id is not None and plan.instance_id != expected_instance_id:
            raise ForgeSessionError(f"Session '{name}' changed before cleanup; retained its replacement")
        apply_session_deletion(self.index_store, plan)
