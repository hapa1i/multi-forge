"""Cross-runtime bridge: hand a Claude session's curated transfer to a headless Codex run.

Command-core op (UI-agnostic; returns structured data, raises ``ForgeOpError``) behind the
``forge session start --runtime codex --resume-from <parent> --task`` surface
(``core/ops/codex_session.py``; the interactive variant reuses the assembly half via
``assemble_codex_transfer``). It composes the "plan in Claude -> implement in Codex" hop:

    parent session
      -> ai-curated transfer (``target_runtime=codex``)
      -> compose initial message (transfer prepended to the task)
      -> ``codex exec`` (``CodexHeadlessInvoker``)

all under **one run tree**, so ``forge activity`` / ``read_usage_events(root_run_id=...)``
attribute the curation step and the Codex run together.

Two deliberate properties:

- **Initial-message delivery is the zero-setup default**: the transfer is prepended to the
  first ``codex exec`` prompt. The post-enrollment upgrade (``--context-delivery hook``)
  stages the handoff for a trust-enrolled Codex ``SessionStart`` hook (``forge hook
  codex-session-start``) to inject as ``additionalContext`` -- because enrollment cannot be
  verified programmatically, hook delivery is opt-in and reconciled post-turn.
- **Curated transfer is the only context bridge**: cross-runtime reasoning signatures are
  non-portable, so the distilled transfer -- not native resume -- is what crosses.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from forge.core.invoker import (
    Attribution,
    CodexHeadlessInvoker,
    HeadlessResult,
    prepare_codex_request,
)
from forge.core.invoker.codex import CodexSandbox
from forge.core.reactive.env import (
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_RUN_ID_VAR,
    RunIdentity,
    new_root_run_identity,
)
from forge.core.runtime.codex_preflight import (
    CodexPreflight,
    CodexPreflightError,
    assert_codex_ready,
)
from forge.core.state.io import atomic_write_text
from forge.session import ForgeSessionError, SessionManager, SessionState
from forge.session.prev_sessions import child_path, compose_child_context
from forge.session.transfer import (
    ResumeStrategy,
    assemble_transfer_context,
    parse_transfer_frontmatter,
)

from .context import ExecutionContext
from .session import ForgeOpError

_FORGE_SESSION_VAR = "FORGE_SESSION"
_FORGE_FORGE_ROOT_VAR = "FORGE_FORGE_ROOT"


@dataclass(frozen=True)
class CodexBridgeResult:
    """Outcome of a Claude->Codex bridge run."""

    parent: str
    child: str  # the per-run transfer child key
    transfer_path: Path  # the curated transfer snapshot fed to Codex
    root_run_id: str  # the run tree the curation + codex events share
    codex: HeadlessResult  # the Codex run's own outcome (success/error is here, not raised)
    curation_ran: bool  # the transfer produced a full ai-curated body (vs a deterministic fallback)
    thread_id: str | None = None  # the `codex exec resume` id (stream `thread.started`)
    # Transfer facts the codex session op mirrors into Derivation (manager.resume_session shape).
    lineage: tuple[str, ...] = ()
    parent_transcript: str | None = None
    context_file_rel: str | None = None


def compose_codex_handoff_context(transfer_body: str) -> str:
    """Frame the curated transfer as handoff context for a Codex run.

    The framing tells Codex the section is curated context from a prior runtime --
    reasoning state does not transfer across runtimes, so this distilled context is the
    authoritative bridge. Shared by both delivery paths: prepended to the initial
    ``codex exec`` message (default), or staged for the ``codex-session-start`` hook to
    inject as ``additionalContext`` (opt-in, post-enrollment).
    """
    return (
        "# Handoff context (curated transfer from a prior planning session)\n"
        "\n"
        "The section below is curated context -- decisions, current state, relevant files, and\n"
        "open questions -- distilled from a planning session in another agent runtime. Reasoning\n"
        "state does not transfer across runtimes, so treat this as your authoritative context.\n"
        "\n"
        f"{transfer_body.strip()}\n"
    )


def compose_codex_initial_message(transfer_body: str, task: str) -> str:
    """Prepend the curated transfer to the task as one ``codex exec`` initial message.

    The zero-setup default delivery (see module docstring); byte-identical to the
    pre-Phase-4 output (golden-pinned).
    """
    return compose_codex_handoff_context(transfer_body) + "\n# Your task\n\n" + f"{task.strip()}\n"


def compose_codex_interactive_context(transfer_body: str) -> str:
    """Frame the curated transfer as the TUI's positional initial prompt (Phase 5).

    The positional ``[PROMPT]`` is a real first user message -- Codex acts on it before
    the human types -- so unlike the passive ``additionalContext`` hook path, this
    framing must pin the model's first turn: acknowledge and hold, no edits, no tools.
    Stage 87 (operator-gated) verifies the hold holds on a real TUI.
    """
    return (
        compose_codex_handoff_context(transfer_body)
        + "\n"
        + "# Hold for instructions\n"
        + "\n"
        + "The section above is context only -- there is no task yet. Acknowledge the\n"
        + "context in one short sentence and WAIT for the user's instruction. Do not\n"
        + "edit files, run commands, or use tools until the user asks.\n"
    )


@dataclass(frozen=True)
class CodexTransferAssembly:
    """A composed Codex-targeted transfer, ready for either delivery path."""

    transfer_path: Path  # the curated transfer snapshot (children/<child>.md)
    body: str  # composed transfer body (frontmatter stripped, notes overlay merged)
    curation_ran: bool  # the transfer produced a full ai-curated body (vs a fallback)
    lineage: tuple[str, ...]
    parent_transcript: str | None
    context_file_rel: str | None


def assemble_codex_transfer(
    *,
    ctx: ExecutionContext,
    parent: str,
    child: str,
    strategy: str = "ai-curated",
    depth: int = 1,
    output_root: Path | None = None,
) -> CodexTransferAssembly:
    """Assemble + compose a Codex-targeted curated transfer for ``child``.

    Pure assembly: no run-tree env management (callers own ``_temporary_run_env`` --
    its lock is non-reentrant) and no Codex invocation. The ai-curated strategy makes
    a ``core.llm`` call whose usage event lands under the AMBIENT run identity, so
    call this inside the same env context the eventual Codex run shares.

    Raises ``ForgeOpError`` for an unknown strategy or a missing parent.
    """
    forge_root = ctx.forge_root
    if forge_root is None:
        raise ForgeOpError("Not inside a Forge project (no .forge/ directory found).")
    try:
        resume_strategy = ResumeStrategy(strategy)
    except ValueError as e:
        valid = ", ".join(s.value for s in ResumeStrategy)
        raise ForgeOpError(f"Unknown strategy '{strategy}' (valid: {valid}).") from e
    manager = SessionManager()
    try:
        parent_state = manager.get_session(parent, forge_root=str(forge_root))
    except ForgeSessionError as e:
        raise ForgeOpError(f"Parent session '{parent}' not found: {e}") from e

    def _get(name: str) -> SessionState | None:
        try:
            return manager.get_session(name, forge_root=str(forge_root))
        except ForgeSessionError:
            return None

    transfer_root = output_root if output_root is not None else forge_root
    transfer = assemble_transfer_context(
        parent_name=parent,
        parent_state=parent_state,
        forge_root=forge_root,
        output_root=output_root,
        strategy=resume_strategy,
        depth=depth,
        get_session=_get,
        child_name=child,
        target_runtime="codex",
    )
    composed = compose_child_context(transfer_root, parent, child)
    frontmatter, body, _ = parse_transfer_frontmatter(composed)
    # schema=="full" is stamped only for a successful ai-curated body (design appendix
    # §M.1); any deterministic fallback is "compatibility-fallback".
    curation_ran = frontmatter is not None and frontmatter.get("schema") == "full"
    return CodexTransferAssembly(
        transfer_path=transfer.context_file or child_path(transfer_root, parent, child),
        body=body,
        curation_ran=curation_ran,
        lineage=tuple(transfer.lineage),
        parent_transcript=transfer.transcript_artifact_path,
        context_file_rel=transfer.context_file_rel,
    )


# Guards _temporary_run_env: os.environ is process-global, so two concurrent bridge
# runs would cross-contaminate run identities and session attribution. Non-blocking
# (fail, don't queue) -- a silently serialized bridge would hide the caller's bug.
_RUN_ENV_LOCK = threading.Lock()


@contextmanager
def _temporary_run_env(
    identity: RunIdentity, session: str, forge_root: str | None = None
) -> Generator[None, None, None]:
    """Make ``identity`` + ``session`` the ambient run-tree env for the block.

    The Codex request-builder (``prepare_codex_request`` -> ``stamp_run_identity``) and
    ``emit_direct_llm_usage`` both read the run-tree triple (and ``FORGE_SESSION``) from
    ``os.environ``, so setting them here is what places the curation event and the
    ``codex exec`` run under one root. ``forge_root`` additionally sets
    ``FORGE_FORGE_ROOT`` so Codex hook subprocesses (``codex-session-start``,
    ``codex-policy-check``) resolve the session store under the CHILD's forge_root --
    a worktree session's manifest is not findable from the payload cwd alone. Saves and
    restores the prior values -- including absence -- on exit, even on exception, so
    this core op never leaks run identity into the rest of the process.

    **Single-use-at-a-time**: ``os.environ`` is process-global state, so concurrent or
    nested use would attribute one bridge's events to another's run tree. Guarded by a
    non-blocking lock -- a second concurrent entry raises ``RuntimeError`` instead of
    silently corrupting attribution. A long-lived surface that wants parallel bridges
    (Phase 6) must replace this ambient-env contract, not relax the guard.
    """
    if not _RUN_ENV_LOCK.acquire(blocking=False):
        raise RuntimeError(
            "_temporary_run_env is already active in this process; "
            "bridge runs cannot overlap (run-tree env is process-global)."
        )
    keys = (
        FORGE_RUN_ID_VAR,
        FORGE_ROOT_RUN_ID_VAR,
        FORGE_PARENT_RUN_ID_VAR,
        _FORGE_SESSION_VAR,
        _FORGE_FORGE_ROOT_VAR,
    )
    saved = {key: os.environ.get(key) for key in keys}
    try:
        os.environ[FORGE_RUN_ID_VAR] = identity.run_id
        os.environ[FORGE_ROOT_RUN_ID_VAR] = identity.root_run_id
        os.environ.pop(FORGE_PARENT_RUN_ID_VAR, None)  # a fresh root has no parent
        os.environ[_FORGE_SESSION_VAR] = session
        if forge_root is not None:
            os.environ[_FORGE_FORGE_ROOT_VAR] = forge_root
        yield
    finally:
        try:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        finally:
            _RUN_ENV_LOCK.release()


def bridge_session_to_codex(
    *,
    ctx: ExecutionContext,
    parent: str,
    task: str,
    cwd: str,
    strategy: str = "ai-curated",
    model: str | None = None,
    sandbox: CodexSandbox = "workspace-write",
    depth: int = 1,
    session: str | None = None,
    timeout_seconds: int = 600,
    child: str | None = None,
    preflight: CodexPreflight | None = None,
    output_root: Path | None = None,
    staged_context_path: Path | None = None,
) -> CodexBridgeResult:
    """Hand ``parent``'s curated transfer to a headless ``codex exec`` run implementing ``task``.

    Mints a fresh run tree, assembles a Codex-targeted curated transfer from the parent
    session, prepends it to the task as the ``codex exec`` initial message, and runs Codex
    in ``cwd`` (expected to be a git worktree) -- so the curation ``core.llm`` event and the
    ``codex_exec`` event share one root. ``staged_context_path`` switches to hook delivery:
    the framed handoff is staged at that path for a trust-enrolled ``codex-session-start``
    hook to inject as ``additionalContext``, and the prompt carries ONLY the task -- the
    caller reconciles delivery from the receipt after the run.

    ``child`` overrides the per-run synthetic transfer-child key -- the codex session op
    passes the real session name so the snapshot is referenced by that session's
    ``Derivation.context_file`` (GC-protected) instead of accumulating as an orphan.
    ``preflight`` skips the internal ``assert_codex_ready()`` (~20s ``codex doctor``) when
    the caller already ran it once. ``output_root`` is the transfer write/read root when
    the child session's forge_root differs from ``ctx.forge_root`` (worktree sessions) --
    GC resolves the child's relative ``context_file`` under the child's indexed
    forge_root, so writing the snapshot anywhere else would orphan it.

    Raises ``ForgeOpError`` for an unknown strategy, a missing parent, or a non-ready Codex
    runtime (with setup guidance). The Codex run's own success/failure is reported on the
    returned ``CodexBridgeResult.codex`` rather than raised. A curation fallback (e.g. no
    curation credential, so ai-curated degrades to structured) is not an error: Codex still
    runs and ``curation_ran`` reports it.
    """
    forge_root = ctx.forge_root
    if forge_root is None:
        raise ForgeOpError("Not inside a Forge project (no .forge/ directory found).")

    # Revalidated inside assemble_codex_transfer; kept here so a bad strategy or
    # missing parent fails BEFORE the ~20s `codex doctor` preflight below.
    try:
        ResumeStrategy(strategy)
    except ValueError as e:
        valid = ", ".join(s.value for s in ResumeStrategy)
        raise ForgeOpError(f"Unknown strategy '{strategy}' (valid: {valid}).") from e
    try:
        SessionManager().get_session(parent, forge_root=str(forge_root))
    except ForgeSessionError as e:
        raise ForgeOpError(f"Parent session '{parent}' not found: {e}") from e

    # Fail closed if Codex can't run (mirrors validate_proxy_startup); the message names
    # the setup path. Runs `codex doctor` (~20s) once -- the bridge is a real launch --
    # unless the caller already ran it and passed the frozen result in.
    if preflight is None:
        try:
            preflight = assert_codex_ready()
        except CodexPreflightError as e:
            raise ForgeOpError(f"Codex runtime not ready: {e}") from e

    root = new_root_run_identity()
    sess = session or parent
    if child is None:
        # Unique per run: ``ensure_child`` "leaves an existing child alone" (a durability
        # guarantee for user-curated Claude resume), so a fixed key would feed Codex a stale
        # snapshot on re-runs. The run id makes each bridge run its own immutable snapshot.
        child = f"{parent}-codex-{root.run_id[-6:]}"
    transfer_root = output_root if output_root is not None else forge_root

    # The CHILD's forge_root (transfer_root): codex hook subprocesses resolve the
    # session store from FORGE_FORGE_ROOT, and a worktree session's manifest lives
    # under the child root, not the payload cwd's.
    with _temporary_run_env(root, sess, forge_root=str(transfer_root)):
        assembly = assemble_codex_transfer(
            ctx=ctx,
            parent=parent,
            child=child,
            strategy=strategy,
            depth=depth,
            output_root=output_root,
        )
        if staged_context_path is not None:
            atomic_write_text(staged_context_path, compose_codex_handoff_context(assembly.body))
            full_prompt = task  # raw, matching the resume-turn prompt contract
        else:
            full_prompt = compose_codex_initial_message(assembly.body, task)

        request = prepare_codex_request(
            prompt=full_prompt,
            preflight=preflight,
            attribution=Attribution(command="codex-bridge", workflow="transfer", session=sess),
            model=model,
            cwd=cwd,
            sandbox=sandbox,
            timeout_seconds=timeout_seconds,
            label="codex-bridge",
        )
        result = CodexHeadlessInvoker().run(request)

    return CodexBridgeResult(
        parent=parent,
        child=child,
        transfer_path=assembly.transfer_path,
        root_run_id=root.root_run_id,
        codex=result,
        curation_ran=assembly.curation_ran,
        thread_id=result.runtime_session_id,
        lineage=assembly.lineage,
        parent_transcript=assembly.parent_transcript,
        context_file_rel=assembly.context_file_rel,
    )
