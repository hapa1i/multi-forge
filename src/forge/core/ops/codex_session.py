"""Codex-runtime session ops (codex_frontend Phase 2).

Command-core (UI-agnostic) implementations behind ``forge session start --runtime codex
--resume-from <parent>`` and ``forge session resume <codex-session> --task ...``. Where
:func:`~forge.core.ops.codex_bridge.bridge_session_to_codex` is a stateless hop (no
manifest), these ops wrap it in a real Forge session lifecycle:

- a manifest with ``intent.launch.runtime = "codex"`` and a ``Derivation`` mirroring
  the Claude resume shape, so the transfer snapshot is GC-protected;
- hook-free ``confirmed.codex`` facts (``thread_id`` from the stream, rollout path by
  filesystem discovery, the preflight's secret-free auth posture) -- Codex hooks fire
  only from trust-enrolled homes, so the CLI records what hooks would have;
- continuation via ``codex exec resume <thread_id>`` (cross-CWD; probe stage 60/61).

``confirmed.launch`` is deliberately never written for Codex sessions: its fields (and
the status-line ``launch`` segment) describe the ANTHROPIC key posture of interactive
Claude, so ``direct + key:none`` would misread an authenticated Codex run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from forge.core.invoker import (
    Attribution,
    CodexHeadlessInvoker,
    HeadlessResult,
    prepare_codex_request,
)
from forge.core.invoker.codex import CodexSandbox
from forge.core.ops.codex_bridge import _temporary_run_env, bridge_session_to_codex
from forge.core.ops.context import ExecutionContext
from forge.core.ops.gc import referenced_transfer_context_paths
from forge.core.ops.session import ForgeOpError
from forge.core.reactive.env import new_root_run_identity
from forge.core.runtime.codex_preflight import (
    CodexPreflight,
    CodexPreflightError,
    assert_codex_ready,
)
from forge.core.runtime.codex_rollouts import find_rollout_path
from forge.core.state import now_iso
from forge.session import (
    ForgeSessionError,
    SessionManager,
    SessionNotFoundError,
    SessionState,
)
from forge.session.codex_handoff import (
    clear_pending_context,
    pending_context_path,
    read_receipt,
)
from forge.session.models import CodexConfirmed, Derivation, SessionIndexEntry
from forge.session.prev_sessions import child_notes_path, child_path
from forge.session.transfer import ResumeStrategy

logger = logging.getLogger(__name__)

ROLLOUT_SOURCE_DISCOVERED = "discovered_by_thread_id"
ROLLOUT_SOURCE_SESSION_START = "session_start_hook"

CODEX_RUNTIME = "codex"

# confirmed.codex.context_delivery values (CLI-written at post-turn reconciliation).
CONTEXT_DELIVERY_INITIAL = "initial_message"
CONTEXT_DELIVERY_HOOK = "session_start_hook"
CONTEXT_DELIVERY_UNDELIVERED = "hook_undelivered"

ContextDeliveryMode = Literal["initial-message", "hook"]

# Knowable-negative hook seams: hook delivery cannot work, so fail before any state
# exists. "enrollment_gated" proceeds -- enrollment itself is unverifiable pre-turn
# (the trusted_hash is not computable); the receipt reconciliation is the truth.
_HOOK_INCAPABLE_SEAMS = ("disabled", "unknown", "managed_suppressed", "untrusted")


@dataclass(frozen=True)
class CodexSessionStartResult:
    """Outcome of ``start_codex_session`` (session created; Codex ran once)."""

    session: str
    parent: str
    transfer_path: Path
    root_run_id: str
    codex: HeadlessResult
    curation_ran: bool
    thread_id: str | None
    rollout_path: str | None
    worktree_path: str | None
    context_delivery: str = CONTEXT_DELIVERY_INITIAL
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodexSessionResumeResult:
    """Outcome of ``continue_codex_session`` (one more turn on the same thread)."""

    session: str
    thread_id: str
    root_run_id: str
    codex: HeadlessResult
    rollout_path: str | None
    warnings: tuple[str, ...] = ()


def session_runtime(state: SessionState) -> str:
    """Return the session's runtime registry id (default ``claude_code``)."""
    launch = state.intent.launch
    return launch.runtime if launch is not None else "claude_code"


def resolve_codex_session(
    manager: SessionManager, name: str, *, forge_root: Path | None
) -> tuple[SessionIndexEntry, SessionState]:
    """Resolve a Codex session by name: current project first, then unscoped.

    Codex resume is cross-CWD by design (probe stage 60), so a scoped miss falls back
    to the global index. Raises ``ForgeOpError`` when the session is missing or not a
    Codex session. Shared by the headless ``continue_codex_session`` and the
    interactive ``reattach_codex_session`` so their refusal messages cannot drift.
    """
    lookup_forge_root = str(forge_root) if forge_root else None
    try:
        entry = manager.get_session_entry(name, forge_root=lookup_forge_root)
        state = manager.get_session(name, forge_root=lookup_forge_root)
    except SessionNotFoundError as e:
        if lookup_forge_root is None:
            raise ForgeOpError(f"Session '{name}' not found: {e}") from e
        # A scoped miss is cross-CWD-legitimate for Codex (probe stage 60): retry unscoped.
        try:
            entry = manager.get_session_entry(name, forge_root=None)
            state = manager.get_session(name, forge_root=None)
        except SessionNotFoundError as fallback:
            raise ForgeOpError(f"Session '{name}' not found: {fallback}") from fallback
        except ForgeSessionError as fallback:
            # A corrupt/invalid manifest is NOT a missing session: surface it as such so
            # the user repairs or deletes it, rather than seeing a misleading "not found".
            raise ForgeOpError(
                f"Session '{name}' could not be read (manifest may be corrupt): {fallback}"
            ) from fallback
    except ForgeSessionError as e:
        # Same distinction on the scoped read: a non-not-found error is corruption, not absence.
        raise ForgeOpError(f"Session '{name}' could not be read (manifest may be corrupt): {e}") from e

    if session_runtime(state) != CODEX_RUNTIME:
        raise ForgeOpError(f"Session '{name}' is not a Codex session (runtime={session_runtime(state)!r}).")
    return entry, state


def require_codex_thread_id(state: SessionState, name: str) -> str:
    """Return the recorded thread_id, or raise with the delete-and-retry guidance."""
    codex_state = state.confirmed.codex
    if codex_state is None or not codex_state.thread_id:
        raise ForgeOpError(
            f"Session '{name}' has no recorded Codex thread_id (its first turn never started a thread). "
            f"Run 'forge session delete {name}' and start it again."
        )
    return codex_state.thread_id


def start_codex_session(
    *,
    ctx: ExecutionContext,
    name: str,
    parent: str,
    task: str,
    strategy: str = "ai-curated",
    depth: int = 1,
    sandbox: CodexSandbox = "workspace-write",
    create_worktree: bool = False,
    branch: str | None = None,
    timeout_seconds: int = 600,
    context_delivery: ContextDeliveryMode = "initial-message",
) -> CodexSessionStartResult:
    """Create a Codex-runtime session derived from ``parent`` and run its first turn.

    Ordering puts the expensive/irreversible work last: validate (strategy, parent,
    preflight) before creating any state, then create the session, then run the
    bridge with the REAL session name as the transfer child key (the snapshot lands
    in ``Derivation.context_file`` and is GC-protected -- no synthetic children on
    this path).

    A failed Codex *turn* keeps the session (its outcome is on ``result.codex``,
    mirroring the bridge stance); an unexpected raise after creation rolls the
    session and this run's snapshot back, then re-raises.
    """
    forge_root = ctx.forge_root
    if forge_root is None:
        raise ForgeOpError("Not inside a Forge project (no .forge/ directory found).")

    valid_strategies = {s.value for s in ResumeStrategy}
    if strategy not in valid_strategies:
        raise ForgeOpError(f"Unknown strategy '{strategy}' (valid: {', '.join(sorted(valid_strategies))}).")

    if context_delivery not in ("initial-message", "hook"):
        raise ForgeOpError(f"Unknown context delivery '{context_delivery}' (valid: initial-message, hook).")

    manager = SessionManager()
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

    if context_delivery == "hook" and preflight.hook_seam in _HOOK_INCAPABLE_SEAMS:
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

    # The child session's indexed forge_root is where GC resolves its relative
    # context_file. It equals ctx.forge_root except for nested Forge projects in a
    # new worktree (manager remaps those). Read it from the returned state, NOT an
    # unscoped index lookup -- names are project-scoped, so a same-named session in
    # another project would make strict resolution raise AmbiguousSessionError and
    # strand the session we just created.
    child_forge_root = Path(state.forge_root) if state.forge_root else forge_root
    output_root = child_forge_root if child_forge_root != forge_root else None
    transfer_root = output_root if output_root is not None else forge_root

    warnings: list[str] = []
    try:
        _clear_stale_child_snapshot(transfer_root, parent, name, warnings)
    except Exception:
        # Nothing of ours is on disk yet: remove only the session. A referenced
        # pre-existing snapshot is another session's property -- never delete it.
        _rollback_created_session(manager, name, forge_root=str(child_forge_root), delete_branch=create_worktree)
        raise

    try:
        return _run_first_codex_turn(
            ctx=ctx,
            manager=manager,
            state=state,
            name=name,
            parent=parent,
            parent_entry_forge_root=parent_entry.forge_root or parent_entry.worktree_path,
            parent_project_root=parent_entry.project_root,
            task=task,
            strategy=strategy,
            depth=depth,
            sandbox=sandbox,
            timeout_seconds=timeout_seconds,
            preflight=preflight,
            child_forge_root=child_forge_root,
            output_root=output_root,
            warnings=warnings,
            context_delivery=context_delivery,
        )
    except Exception:
        # Past the guard, any snapshot at this key was written by this run.
        _rollback_created_session(
            manager,
            name,
            forge_root=str(child_forge_root),
            snapshot=child_path(transfer_root, parent, name),
            notes=child_notes_path(transfer_root, parent, name),
            delete_branch=create_worktree,
        )
        raise


def _run_first_codex_turn(
    *,
    ctx: ExecutionContext,
    manager: SessionManager,
    state: SessionState,
    name: str,
    parent: str,
    parent_entry_forge_root: str | None,
    parent_project_root: str | None,
    task: str,
    strategy: str,
    depth: int,
    sandbox: CodexSandbox,
    timeout_seconds: int,
    preflight: CodexPreflight,
    child_forge_root: Path,
    output_root: Path | None,
    warnings: list[str],
    context_delivery: ContextDeliveryMode,
) -> CodexSessionStartResult:
    """The post-creation half of ``start_codex_session`` (the caller owns rollback)."""
    store = manager.get_session_store(name, forge_root=str(child_forge_root))
    staged_context_path = pending_context_path(store.session_dir) if context_delivery == "hook" else None

    cwd = state.worktree.path if state.worktree else str(ctx.cwd)
    bridge = bridge_session_to_codex(
        ctx=ctx,
        parent=parent,
        task=task,
        cwd=cwd,
        strategy=strategy,
        sandbox=sandbox,
        depth=depth,
        session=name,
        timeout_seconds=timeout_seconds,
        child=name,
        preflight=preflight,
        output_root=output_root,
        staged_context_path=staged_context_path,
    )

    delivery_fact = CONTEXT_DELIVERY_INITIAL
    effective_thread_id = bridge.thread_id
    hook_rollout: str | None = None
    if context_delivery == "hook":
        delivery_fact, effective_thread_id, hook_rollout = _reconcile_hook_delivery(
            session_dir=store.session_dir,
            thread_id=bridge.thread_id,
            warnings=warnings,
        )

    if hook_rollout is not None:
        rollout_path: str | None = hook_rollout
        rollout_source: str | None = ROLLOUT_SOURCE_SESSION_START
    else:
        rollout = find_rollout_path(effective_thread_id) if effective_thread_id else None
        rollout_path = str(rollout) if rollout else None
        rollout_source = ROLLOUT_SOURCE_DISCOVERED if rollout else None

    timestamp = now_iso()
    derivation = Derivation(
        parent_session=parent,
        parent_transcript=bridge.parent_transcript,
        resume_mode="transfer",
        strategy=strategy,
        depth=depth,
        resumed_at=timestamp,
        lineage=list(bridge.lineage),
        context_file=bridge.context_file_rel,
        parent_forge_root=parent_entry_forge_root,
        parent_project_root=parent_project_root,
    )
    codex_confirmed = CodexConfirmed(
        thread_id=effective_thread_id,
        rollout_path=rollout_path,
        rollout_source=rollout_source,
        auth_method=preflight.auth_method,
        auth_source=preflight.auth_source,
        billing_mode=preflight.billing_mode,
        last_run_at=timestamp,
        context_delivery=delivery_fact,
    )

    def _mutate(m: SessionState) -> None:
        m.confirmed.derivation = derivation
        m.confirmed.codex = codex_confirmed
        m.confirmed.confirmed_at = timestamp
        m.confirmed.confirmed_by = "cli:codex-start"

    store.update(timeout_s=5.0, mutate=_mutate)

    if effective_thread_id is None:
        warnings.append(
            "Codex did not announce a thread_id; this session cannot be resumed. "
            f"Run 'forge session delete {name}' and retry."
        )

    return CodexSessionStartResult(
        session=name,
        parent=parent,
        transfer_path=bridge.transfer_path,
        root_run_id=bridge.root_run_id,
        codex=bridge.codex,
        curation_ran=bridge.curation_ran,
        thread_id=effective_thread_id,
        rollout_path=rollout_path,
        worktree_path=state.worktree.path if state.worktree else None,
        context_delivery=delivery_fact,
        warnings=tuple(warnings),
    )


def _reconcile_hook_delivery(
    *,
    session_dir: Path,
    thread_id: str | None,
    warnings: list[str],
) -> tuple[str, str | None, str | None]:
    """Reconcile the hook-delivery receipt after the first turn.

    Returns ``(context_delivery fact, effective thread_id, hook-sourced rollout path)``.
    The receipt is trustworthy for THIS turn: it can only be written while the staged
    file exists (one-shot, staged by this start), and rollback deletes the session dir.
    An absent or thread-mismatched receipt means the context never reached this thread
    -- the staged file is cleared so a later enrolled resume can never late-deliver it.
    """
    receipt = read_receipt(session_dir)
    # One-shot: the start turn is over, so the staged handoff must not survive it. Clear
    # it unconditionally (idempotent) -- the hook's consume normally removes it, but this
    # backstops a consume whose unlink failed, so a later enrolled resume or mid-session
    # SessionStart can never re-deliver the same context.
    clear_pending_context(session_dir)
    if receipt is None:
        return CONTEXT_DELIVERY_UNDELIVERED, thread_id, None
    if thread_id is None:
        # The stream missed thread.started but the hook saw the turn's thread: recover
        # the id so the session stays resumable (rollout discovery included).
        warnings.append(
            f"Codex stream announced no thread_id; recovered '{receipt.session_id}' from the delivery receipt."
        )
        return CONTEXT_DELIVERY_HOOK, receipt.session_id, receipt.transcript_path
    if receipt.session_id != thread_id:
        warnings.append(
            f"Delivery receipt thread ('{receipt.session_id}') does not match the stream thread "
            f"('{thread_id}'); treating the transfer context as undelivered."
        )
        return CONTEXT_DELIVERY_UNDELIVERED, thread_id, None
    # Delivered. The receipt's rollout path comes from codex's own payload, so it
    # supersedes glob discovery; cross-check and surface a disagreement.
    if receipt.transcript_path:
        discovered = find_rollout_path(thread_id)
        if discovered is not None and str(discovered) != receipt.transcript_path:
            warnings.append(
                f"Receipt rollout path ('{receipt.transcript_path}') differs from the discovered one "
                f"('{discovered}'); keeping the receipt's."
            )
    return CONTEXT_DELIVERY_HOOK, thread_id, receipt.transcript_path


def continue_codex_session(
    *,
    ctx: ExecutionContext,
    name: str,
    task: str,
    sandbox: CodexSandbox = "workspace-write",
    timeout_seconds: int = 600,
) -> CodexSessionResumeResult:
    """Run one more ``codex exec resume <thread_id>`` turn on an existing Codex session.

    Cross-CWD by design (probe stage 60): the turn runs in the session's recorded
    worktree, not the invocation directory. Requires a recorded ``thread_id`` -- a
    session whose first turn failed before ``thread.started`` cannot be resumed.
    """
    manager = SessionManager()
    entry, state = resolve_codex_session(manager, name, forge_root=ctx.forge_root)
    thread_id = require_codex_thread_id(state, name)

    try:
        preflight = assert_codex_ready()
    except CodexPreflightError as e:
        raise ForgeOpError(f"Codex runtime not ready: {e}") from e

    warnings: list[str] = []
    store = manager.get_session_store(name, forge_root=entry.forge_root)
    # One-shot invariant, defensively: a staged handoff that survived the start turn
    # (crash window) must never late-deliver into a resume turn from an enrolled home.
    if clear_pending_context(store.session_dir):
        warnings.append("Cleared a stale staged handoff (its start turn never delivered it).")

    root = new_root_run_identity()
    with _temporary_run_env(root, name, forge_root=entry.forge_root):
        request = prepare_codex_request(
            prompt=task,
            preflight=preflight,
            attribution=Attribution(command="codex-resume", session=name),
            cwd=state.worktree.path if state.worktree else str(ctx.cwd),
            sandbox=sandbox,
            timeout_seconds=timeout_seconds,
            label="codex-resume",
            resume_thread_id=thread_id,
        )
        result = CodexHeadlessInvoker().run(request)

    effective_thread_id = thread_id
    if result.runtime_session_id and result.runtime_session_id != thread_id:
        # Probe 60b pinned id stability across resume; drift means Codex re-bound the
        # thread. Record the live id (resume must keep working) and surface the drift.
        warnings.append(f"Codex thread_id drifted: {thread_id} -> {result.runtime_session_id} (recorded the new id).")
        effective_thread_id = result.runtime_session_id

    rollout = find_rollout_path(effective_thread_id)
    timestamp = now_iso()

    def _mutate(m: SessionState) -> None:
        codex = m.confirmed.codex or CodexConfirmed()
        codex.thread_id = effective_thread_id
        if rollout is not None:
            codex.rollout_path = str(rollout)
            codex.rollout_source = ROLLOUT_SOURCE_DISCOVERED
        # Auth posture is refreshed per run (CodexConfirmed contract): this turn ran
        # under THIS preflight's auth, not whatever the first turn recorded.
        codex.auth_method = preflight.auth_method
        codex.auth_source = preflight.auth_source
        codex.billing_mode = preflight.billing_mode
        codex.last_run_at = timestamp
        m.confirmed.codex = codex

    store.update(timeout_s=5.0, mutate=_mutate)

    return CodexSessionResumeResult(
        session=name,
        thread_id=effective_thread_id,
        root_run_id=root.root_run_id,
        codex=result,
        rollout_path=str(rollout) if rollout else None,
        warnings=tuple(warnings),
    )


def _clear_stale_child_snapshot(transfer_root: Path, parent: str, child: str, warnings: list[str]) -> None:
    """Remove an unreferenced pre-existing child snapshot (and its notes overlay).

    ``ensure_child`` never overwrites, so a snapshot left by a rolled-back or deleted
    run would silently feed stale context to Codex. ``start_session`` already failed
    on a name collision, so no session named ``child`` exists -- but ``context_file``
    may be recorded absolute, so a same-named session in a DIFFERENT forge_root could
    still reference this exact path: check the global reference set, and refuse rather
    than reuse foreign context. The paired notes overlay goes with the snapshot (GC
    ties their liveness; stale user notes must not compose into the new session).
    """
    snapshot = child_path(transfer_root, parent, child)
    if not snapshot.exists():
        return
    if str(snapshot.resolve()) in referenced_transfer_context_paths():
        raise ForgeOpError(
            f"Transfer snapshot {snapshot} already exists and is referenced by another "
            f"session's derivation. Choose a different session name."
        )
    snapshot.unlink()
    notes = child_notes_path(transfer_root, parent, child)
    if notes.exists():
        notes.unlink()
    warnings.append(f"Replaced a stale transfer snapshot left by a previous run: {snapshot}")


def _rollback_created_session(
    manager: SessionManager,
    name: str,
    *,
    forge_root: str,
    snapshot: Path | None = None,
    notes: Path | None = None,
    delete_branch: bool,
) -> None:
    """Best-effort rollback of the session (and this run's snapshot) on a failed start.

    GC would eventually flag the orphaned snapshot, but a retry with the same name
    must start clean (``ensure_child`` never overwrites), so it is removed here.
    ``snapshot``/``notes`` are passed only when this run owns them (past the
    stale-snapshot guard) -- a referenced foreign snapshot must never be deleted.
    ``forge_root`` scopes the delete to the session this run created: an unscoped
    delete would raise ``AmbiguousSessionError`` when another project has the name.
    """
    try:
        manager.delete_session(name, force=True, delete_branch=delete_branch, forge_root=forge_root)
    except Exception:
        logger.debug("Codex start rollback: delete_session failed (non-critical)", exc_info=True)
    for leftover in (snapshot, notes):
        if leftover is None:
            continue
        try:
            leftover.unlink(missing_ok=True)
        except OSError:
            logger.debug("Codex start rollback: snapshot cleanup failed (non-critical)", exc_info=True)
