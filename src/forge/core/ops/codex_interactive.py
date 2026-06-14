"""Interactive Codex-runtime session ops (codex_frontend Phase 5).

Command-core implementations behind the bare (no ``--task``) Codex forms of
``forge session start --runtime codex`` and ``forge session resume``: launch the
foreground ``codex`` TUI as a managed Forge session, and reattach an existing one via
``codex resume <thread_id>``.

The TUI owns stdout, so there is no JSONL stream to read ``thread.started`` from.
Thread identity is reconciled POST-EXIT instead, in precedence order:

1. **Receipts** from a trust-enrolled ``codex-session-start`` hook -- the delivery
   receipt (hook-delivery bridge starts) or the observation receipt (nothing-staged
   turns); both carry codex's own ``session_id``/``transcript_path``. The CLI clears
   stale receipts pre-launch, so a receipt always describes THIS launch.
2. **Filesystem discovery** (:func:`find_rollouts_since`): rollouts created after the
   pre-launch timestamp, narrowed by worktree cwd. Exactly one candidate is required
   -- on ambiguity the thread stays unrecorded (recording a concurrent stranger's
   thread would resume the wrong conversation).

Two timestamps are deliberate: ``operation_started_at`` (before transfer assembly --
the post-exit activity summary's ``since``, so the curation usage event lands inside
the window) vs the discovery timestamp (immediately before launch -- assembly can take
30s+ of LLM curation, and a wide window admits unrelated concurrent rollouts).

Interactive turns emit NO usage event (the TUI reports no usage Forge can attribute;
mirrors the reserved ``claude_interactive`` route). The bridge variant's transfer
curation still emits -- under the same run root the TUI inherits, so ``forge
activity`` shows them as one tree. Like the headless ops, ``confirmed.launch`` and
``claude_session_id`` stay unset (design.md section 3.5).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from forge.core.invoker.codex import CodexSandbox
from forge.core.ops.codex_bridge import (
    _temporary_run_env,
    assemble_codex_transfer,
    compose_codex_handoff_context,
    compose_codex_interactive_context,
)
from forge.core.ops.codex_session import (
    _HOOK_INCAPABLE_SEAMS,
    CODEX_RUNTIME,
    CONTEXT_DELIVERY_HOOK,
    CONTEXT_DELIVERY_INITIAL,
    CONTEXT_DELIVERY_UNDELIVERED,
    ContextDeliveryMode,
    _clear_stale_child_snapshot,
    _rollback_created_session,
    require_codex_thread_id,
    resolve_codex_session,
)
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import ForgeOpError
from forge.core.reactive.env import new_root_run_identity
from forge.core.runtime.codex_preflight import CodexPreflightError, assert_codex_ready
from forge.core.runtime.codex_rollouts import find_rollout_path, find_rollouts_since
from forge.core.state import now_iso
from forge.session import ForgeSessionError, SessionManager, SessionState
from forge.session.active import run_with_active_session
from forge.session.codex_handoff import (
    clear_observation_receipt,
    clear_pending_context,
    read_observation_receipt,
    read_receipt,
    stage_pending_context,
)
from forge.session.codex_invoke import invoke_codex_interactive
from forge.session.config import LAUNCH_MODE_HOST
from forge.session.exceptions import SessionFileNotFoundError
from forge.session.models import CodexConfirmed, Derivation, SessionIndexEntry
from forge.session.prev_sessions import child_notes_path, child_path
from forge.session.store import MANIFEST_FILENAME, SessionStore
from forge.session.transfer import ResumeStrategy

logger = logging.getLogger(__name__)

# Post-exit filesystem discovery: the thread_id comes FROM the rollout filename
# (time+cwd discovery), unlike "discovered_by_thread_id" where a stream-known id
# locates its file. A distinct literal so provenance stays honest.
ROLLOUT_SOURCE_POST_EXIT = "discovered_post_exit"

ROLLOUT_SOURCE_DISCOVERED = "discovered_by_thread_id"
ROLLOUT_SOURCE_SESSION_START = "session_start_hook"


@dataclass(frozen=True)
class CodexInteractiveLaunch:
    """Pre-launch announce payload (the CLI prints it before the TUI takes the terminal)."""

    session: str
    parent: str | None
    worktree_path: str | None
    transfer_path: Path | None
    context_delivery: str | None  # requested mode for bridge starts; None for bare/reattach
    reattach_thread_id: str | None = None


@dataclass(frozen=True)
class CodexInteractiveResult:
    """Outcome of an interactive Codex launch (start or reattach), reconciled post-exit."""

    session: str
    forge_root: str  # the session's indexed forge_root (worktree sessions differ from ctx's)
    exit_code: int
    thread_id: str | None
    rollout_path: str | None
    rollout_source: str | None
    context_delivery: str | None  # recorded transfer-delivery fact; None for bare/reattach
    curation_ran: bool | None  # None when no transfer was assembled (bare/reattach)
    operation_started_at: datetime  # the CLI's post-exit activity-summary `since`
    warnings: tuple[str, ...] = ()


def start_interactive_codex_session(
    *,
    ctx: ExecutionContext,
    name: str,
    parent: str | None = None,
    strategy: str = "ai-curated",
    depth: int = 1,
    sandbox: CodexSandbox = "workspace-write",
    create_worktree: bool = False,
    branch: str | None = None,
    context_delivery: ContextDeliveryMode = "initial-message",
    announce: Callable[[CodexInteractiveLaunch], None] | None = None,
    invoke: Callable[..., int] = invoke_codex_interactive,
) -> CodexInteractiveResult:
    """Create a Codex-runtime session and run it as a foreground ``codex`` TUI.

    Bare (``parent=None``): a parentless interactive session -- no transfer, no
    derivation, ``context_delivery`` recorded as None (the field is a
    transfer-delivery fact). Bridge (``parent`` set): the curated transfer rides the
    positional initial prompt with hold instructions (default), or is staged for a
    trust-enrolled ``codex-session-start`` hook (``context_delivery="hook"``; an
    absent receipt reconciles ``hook_undelivered`` -- the CLI fails loud, session
    kept).

    Rollback (session + this run's snapshot) applies ONLY to raises before the TUI
    launches; once the TUI ran, the session is the user's -- reconciliation records
    what it can and reports the rest as warnings.
    """
    operation_started_at = datetime.now(timezone.utc)
    forge_root = ctx.forge_root
    if forge_root is None:
        raise ForgeOpError("Not inside a Forge project (no .forge/ directory found).")
    if context_delivery not in ("initial-message", "hook"):
        raise ForgeOpError(f"Unknown context delivery '{context_delivery}' (valid: initial-message, hook).")

    manager = SessionManager()
    parent_entry: SessionIndexEntry | None = None
    if parent is not None:
        valid_strategies = {s.value for s in ResumeStrategy}
        if strategy not in valid_strategies:
            raise ForgeOpError(f"Unknown strategy '{strategy}' (valid: {', '.join(sorted(valid_strategies))}).")
        try:
            parent_entry = manager.get_session_entry(parent, forge_root=str(forge_root))
            manager.get_session(parent, forge_root=str(forge_root))
        except ForgeSessionError as e:
            raise ForgeOpError(f"Parent session '{parent}' not found: {e}") from e

    # Fail closed before any state exists (runs `codex doctor` ~20s, once).
    try:
        preflight = assert_codex_ready()
    except CodexPreflightError as e:
        raise ForgeOpError(f"Codex runtime not ready: {e}") from e

    if parent is not None and context_delivery == "hook" and preflight.hook_seam in _HOOK_INCAPABLE_SEAMS:
        raise ForgeOpError(
            f"--context-delivery hook needs a hook-capable Codex install "
            f"(hook seam: {preflight.hook_seam}). Fix the Codex hook configuration "
            f"or use the default initial-message delivery."
        )

    try:
        state = manager.start_session(
            name,
            create_worktree=create_worktree,
            branch=branch,
            direct=True,
            runtime=CODEX_RUNTIME,
            parent_session=parent,
        )
    except ForgeSessionError as e:
        raise ForgeOpError(str(e)) from e

    # Same child-root logic as start_codex_session: GC resolves the child's relative
    # context_file under ITS indexed forge_root (nested Forge projects in a worktree).
    child_forge_root = Path(state.forge_root) if state.forge_root else forge_root
    output_root = child_forge_root if child_forge_root != forge_root else None
    transfer_root = output_root if output_root is not None else forge_root
    cwd = state.worktree.path if state.worktree else str(ctx.cwd)

    warnings: list[str] = []
    if parent is not None:
        try:
            _clear_stale_child_snapshot(transfer_root, parent, name, warnings)
        except Exception:
            # Nothing of ours is on disk yet: remove only the session (a referenced
            # pre-existing snapshot is another session's property).
            _rollback_created_session(manager, name, forge_root=str(child_forge_root), delete_branch=create_worktree)
            raise

    root = new_root_run_identity()
    assembly = None
    initial_prompt: str | None = None
    try:
        store = manager.get_session_store(name, forge_root=str(child_forge_root))
        # Receipts must describe THIS launch only; the session dir is fresh, but the
        # clears are cheap insurance against any leftover state.
        clear_observation_receipt(store.session_dir)
        clear_pending_context(store.session_dir)
        if parent is not None:
            # The curation usage event lands under the SAME root the TUI inherits
            # (invoke takes run_identity=root below) -- one run tree.
            with _temporary_run_env(root, name, forge_root=str(transfer_root)):
                assembly = assemble_codex_transfer(
                    ctx=ctx,
                    parent=parent,
                    child=name,
                    strategy=strategy,
                    depth=depth,
                    output_root=output_root,
                )
            if context_delivery == "hook":
                stage_pending_context(store.session_dir, compose_codex_handoff_context(assembly.body))
            else:
                initial_prompt = compose_codex_interactive_context(assembly.body)

        # Tight discovery window: taken AFTER assembly (which can run 30s+ of LLM
        # curation) and immediately before the TUI spawns.
        discovery_started_at = datetime.now(timezone.utc)
        if announce is not None:
            announce(
                CodexInteractiveLaunch(
                    session=name,
                    parent=parent,
                    worktree_path=state.worktree.path if state.worktree else None,
                    transfer_path=assembly.transfer_path if assembly is not None else None,
                    context_delivery=context_delivery if parent is not None else None,
                )
            )
    except Exception:
        # Past the stale-snapshot guard, any snapshot at this key was written by this run.
        _rollback_created_session(
            manager,
            name,
            forge_root=str(child_forge_root),
            snapshot=child_path(transfer_root, parent, name) if parent is not None else None,
            notes=child_notes_path(transfer_root, parent, name) if parent is not None else None,
            delete_branch=create_worktree,
        )
        raise

    # The TUI launch: NO rollback past this point -- the session is the user's.
    exit_code = run_with_active_session(
        session_name=name,
        worktree_path=Path(cwd),
        launch_mode=LAUNCH_MODE_HOST,
        forge_root=str(child_forge_root),
        claude_session_id=None,
        runner=lambda: invoke(
            preflight=preflight,
            session_name=name,
            forge_root=str(child_forge_root),
            cwd=cwd,
            run_identity=root,
            sandbox=sandbox,
            initial_prompt=initial_prompt,
        ),
    )

    # Post-exit reconciliation: receipts first (codex-reported, exact), discovery last.
    receipt_thread: str | None = None
    receipt_rollout: str | None = None
    delivery_fact: str | None = None
    if parent is not None and context_delivery == "hook":
        delivery_fact, receipt_thread, receipt_rollout = _reconcile_interactive_hook_delivery(store.session_dir)
    elif parent is not None:
        delivery_fact = CONTEXT_DELIVERY_INITIAL

    observation = read_observation_receipt(store.session_dir)
    if receipt_thread is None and observation is not None:
        receipt_thread = observation.session_id
        receipt_rollout = observation.transcript_path

    if receipt_thread is not None:
        thread_id: str | None = receipt_thread
        rollout_path = receipt_rollout
        rollout_source = ROLLOUT_SOURCE_SESSION_START if receipt_rollout else None
        if rollout_path is None and thread_id:
            discovered = find_rollout_path(thread_id)
            if discovered is not None:
                rollout_path = str(discovered)
                rollout_source = ROLLOUT_SOURCE_DISCOVERED
    else:
        thread_id, rollout_path, rollout_source = _discover_thread_post_exit(
            discovery_started_at, cwd=cwd, warnings=warnings
        )

    timestamp = now_iso()
    derivation: Derivation | None = None
    if parent is not None and assembly is not None and parent_entry is not None:
        derivation = Derivation(
            parent_session=parent,
            parent_transcript=assembly.parent_transcript,
            resume_mode="transfer",
            strategy=strategy,
            depth=depth,
            resumed_at=timestamp,
            lineage=list(assembly.lineage),
            context_file=assembly.context_file_rel,
            parent_forge_root=parent_entry.forge_root or parent_entry.worktree_path,
            parent_project_root=parent_entry.project_root,
        )
    codex_confirmed = CodexConfirmed(
        thread_id=thread_id,
        rollout_path=rollout_path,
        rollout_source=rollout_source,
        auth_method=preflight.auth_method,
        auth_source=preflight.auth_source,
        billing_mode=preflight.billing_mode,
        last_run_at=timestamp,
        context_delivery=delivery_fact,
    )

    def _mutate(m: SessionState) -> None:
        if derivation is not None:
            m.confirmed.derivation = derivation
        m.confirmed.codex = codex_confirmed
        m.confirmed.confirmed_at = timestamp
        m.confirmed.confirmed_by = "cli:codex-interactive-start"

    _update_manifest_if_present(store, mutate=_mutate, warnings=warnings, session=name)

    if thread_id is None:
        warnings.append(
            f"No Codex thread recorded for this run; the session cannot be resumed. "
            f"Run 'forge session delete {name}' and start again."
        )

    return CodexInteractiveResult(
        session=name,
        forge_root=str(child_forge_root),
        exit_code=exit_code,
        thread_id=thread_id,
        rollout_path=rollout_path,
        rollout_source=rollout_source,
        context_delivery=delivery_fact,
        curation_ran=assembly.curation_ran if assembly is not None else None,
        operation_started_at=operation_started_at,
        warnings=tuple(warnings),
    )


def reattach_codex_session(
    *,
    ctx: ExecutionContext,
    name: str,
    sandbox: CodexSandbox = "workspace-write",
    announce: Callable[[CodexInteractiveLaunch], None] | None = None,
    invoke: Callable[..., int] = invoke_codex_interactive,
) -> CodexInteractiveResult:
    """Reattach to an existing Codex session as a foreground TUI (``codex resume``).

    Mirrors ``continue_codex_session``'s guards (shared helpers, so the refusal
    messages cannot drift) and its per-turn refreshes: auth posture and
    ``last_run_at`` from THIS run's preflight, thread drift recorded from the
    observation receipt when an enrolled hook saw the turn.
    """
    operation_started_at = datetime.now(timezone.utc)
    manager = SessionManager()
    entry, state = resolve_codex_session(manager, name, forge_root=ctx.forge_root)
    thread_id = require_codex_thread_id(state, name)

    try:
        preflight = assert_codex_ready()
    except CodexPreflightError as e:
        raise ForgeOpError(f"Codex runtime not ready: {e}") from e

    warnings: list[str] = []
    session_forge_root = entry.forge_root or entry.worktree_path
    store = manager.get_session_store(name, forge_root=entry.forge_root)
    # One-shot invariant, defensively: a staged handoff that survived the start turn
    # (crash window) must never late-deliver into a resume turn from an enrolled home.
    if clear_pending_context(store.session_dir):
        warnings.append("Cleared a stale staged handoff (its start turn never delivered it).")
    clear_observation_receipt(store.session_dir)

    cwd = state.worktree.path if state.worktree else str(ctx.cwd)
    root = new_root_run_identity()
    if announce is not None:
        announce(
            CodexInteractiveLaunch(
                session=name,
                parent=None,
                worktree_path=state.worktree.path if state.worktree else None,
                transfer_path=None,
                context_delivery=None,
                reattach_thread_id=thread_id,
            )
        )

    exit_code = run_with_active_session(
        session_name=name,
        worktree_path=Path(cwd),
        launch_mode=LAUNCH_MODE_HOST,
        forge_root=session_forge_root,
        claude_session_id=None,
        runner=lambda: invoke(
            preflight=preflight,
            session_name=name,
            forge_root=session_forge_root,
            cwd=cwd,
            run_identity=root,
            sandbox=sandbox,
            resume_thread_id=thread_id,
        ),
    )

    # Post-exit: an enrolled hook's observation receipt cross-checks the thread
    # (drift recorded, the continue_codex_session stance) and supersedes glob
    # discovery for the rollout path (codex-reported).
    effective_thread = thread_id
    rollout_path: str | None = None
    rollout_source: str | None = None
    observation = read_observation_receipt(store.session_dir)
    if observation is not None:
        if observation.session_id != thread_id:
            warnings.append(f"Codex thread_id drifted: {thread_id} -> {observation.session_id} (recorded the new id).")
            effective_thread = observation.session_id
        if observation.transcript_path:
            rollout_path = observation.transcript_path
            rollout_source = ROLLOUT_SOURCE_SESSION_START
    if rollout_path is None:
        discovered = find_rollout_path(effective_thread)
        if discovered is not None:
            rollout_path = str(discovered)
            rollout_source = ROLLOUT_SOURCE_DISCOVERED

    timestamp = now_iso()

    def _mutate(m: SessionState) -> None:
        codex = m.confirmed.codex or CodexConfirmed()
        codex.thread_id = effective_thread
        if rollout_path is not None:
            codex.rollout_path = rollout_path
            codex.rollout_source = rollout_source
        # Auth posture is refreshed per run (CodexConfirmed contract): this turn ran
        # under THIS preflight's auth, not whatever the first turn recorded.
        codex.auth_method = preflight.auth_method
        codex.auth_source = preflight.auth_source
        codex.billing_mode = preflight.billing_mode
        codex.last_run_at = timestamp
        m.confirmed.codex = codex

    _update_manifest_if_present(store, mutate=_mutate, warnings=warnings, session=name)

    return CodexInteractiveResult(
        session=name,
        forge_root=session_forge_root,
        exit_code=exit_code,
        thread_id=effective_thread,
        rollout_path=rollout_path,
        rollout_source=rollout_source,
        context_delivery=None,
        curation_ran=None,
        operation_started_at=operation_started_at,
        warnings=tuple(warnings),
    )


def _reconcile_interactive_hook_delivery(session_dir: Path) -> tuple[str, str | None, str | None]:
    """Reconcile hook delivery after an interactive bridge start.

    Interactive turns have no stream thread to cross-check against (the headless
    variant's job), so the delivery receipt IS the thread source: present means
    delivered (thread + codex-reported rollout); absent means undelivered, and the
    staged file is cleared (one-shot -- an enrolled resume must never late-deliver
    stale context mid-thread).
    """
    receipt = read_receipt(session_dir)
    # One-shot: clear the staged handoff unconditionally now the TUI has exited, so a
    # later reattach or mid-session SessionStart cannot re-deliver it (backstops a hook
    # consume whose unlink failed).
    clear_pending_context(session_dir)
    if receipt is None:
        return CONTEXT_DELIVERY_UNDELIVERED, None, None
    return CONTEXT_DELIVERY_HOOK, receipt.session_id, receipt.transcript_path


def _discover_thread_post_exit(
    since: datetime, *, cwd: str, warnings: list[str]
) -> tuple[str | None, str | None, str | None]:
    """Discover this run's thread from rollouts created after launch.

    Exactly one candidate is required; ambiguity refuses to guess (recording a
    concurrent stranger's thread would resume the wrong conversation).
    """
    candidates = find_rollouts_since(since, cwd=cwd)
    if len(candidates) == 1:
        return candidates[0].thread_id, str(candidates[0].path), ROLLOUT_SOURCE_POST_EXIT
    if not candidates:
        warnings.append("No Codex rollout appeared during this run; the thread could not be discovered.")
    else:
        warnings.append(
            f"{len(candidates)} Codex rollouts appeared during this run; "
            f"refusing to guess which one is this session's thread."
        )
    return None, None, None


def _update_manifest_if_present(
    store: SessionStore,
    *,
    mutate: Callable[[SessionState], None],
    warnings: list[str],
    session: str,
) -> bool:
    """Best-effort post-TUI manifest update without resurrecting deleted sessions."""
    if not store.exists():
        warnings.append(f"Session '{session}' was deleted while Codex was running; skipped post-exit manifest update.")
        return False
    try:
        store.update(timeout_s=5.0, mutate=mutate)
    except SessionFileNotFoundError:
        # A concurrent delete can land after exists() but before update() reads. The
        # lock layer creates the session dir to hold forge.session.json.lock; remove
        # that lock-only shell so delete remains delete.
        _remove_lock_only_session_dir(store.session_dir)
        warnings.append(f"Session '{session}' was deleted while Codex was running; skipped post-exit manifest update.")
        return False
    return True


def _remove_lock_only_session_dir(session_dir: Path) -> None:
    lock_name = f"{MANIFEST_FILENAME}.lock"
    try:
        entries = list(session_dir.iterdir())
    except FileNotFoundError:
        return
    except OSError:
        logger.debug("Could not inspect deleted session directory %s", session_dir, exc_info=True)
        return
    if any(entry.name != lock_name or not entry.is_file() for entry in entries):
        return
    # Empty entries means another actor already unlinked the lock; the bare shell is
    # still a partial resurrection, so it is removed the same way.
    try:
        for entry in entries:
            entry.unlink()
        session_dir.rmdir()
    except OSError:
        logger.debug("Could not remove lock-only deleted session directory %s", session_dir, exc_info=True)
