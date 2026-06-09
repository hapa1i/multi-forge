"""Cross-runtime bridge: hand a Claude session's curated transfer to a headless Codex run.

Command-core op (UI-agnostic; returns structured data, raises ``ForgeOpError``) behind a
future ``forge ... --runtime codex`` surface (the user-facing command is Phase 6). It
composes the Phase 5 build-group parts into the "plan in Claude -> implement in Codex" hop
(Slice 5e):

    parent session
      -> ai-curated transfer (``target_runtime=codex``)
      -> compose initial message (transfer prepended to the task)
      -> ``codex exec`` (``CodexHeadlessInvoker``)

all under **one run tree**, so ``forge activity`` / ``read_usage_events(root_run_id=...)``
attribute the curation step and the Codex run together.

Two deliberate properties:

- **Delivery is the initial ``codex exec`` message**, not a Codex ``SessionStart`` hook:
  per-hook trust can't be confirmed (Slice 5a), so hook delivery is deferred to Phase 6.
- **Curated transfer is the only context bridge**: cross-runtime reasoning signatures are
  non-portable, so the distilled transfer -- not native resume -- is what crosses.
"""

from __future__ import annotations

import os
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
from forge.core.runtime.codex_preflight import CodexPreflightError, assert_codex_ready
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


@dataclass(frozen=True)
class CodexBridgeResult:
    """Outcome of a Claude->Codex bridge run."""

    parent: str
    child: str  # the per-run transfer child key
    transfer_path: Path  # the curated transfer snapshot fed to Codex
    root_run_id: str  # the run tree the curation + codex events share
    codex: HeadlessResult  # the Codex run's own outcome (success/error is here, not raised)
    curation_ran: bool  # the transfer produced a full ai-curated body (vs a deterministic fallback)


def compose_codex_initial_message(transfer_body: str, task: str) -> str:
    """Prepend the curated transfer to the task as one ``codex exec`` initial message.

    The curated transfer is delivered in-band (no Codex ``SessionStart`` hook; see module
    docstring). The framing tells Codex the section is curated context from a prior runtime
    -- reasoning state does not transfer across runtimes, so this distilled context is the
    authoritative bridge.
    """
    return (
        "# Handoff context (curated transfer from a prior planning session)\n"
        "\n"
        "The section below is curated context -- decisions, current state, relevant files, and\n"
        "open questions -- distilled from a planning session in another agent runtime. Reasoning\n"
        "state does not transfer across runtimes, so treat this as your authoritative context.\n"
        "\n"
        f"{transfer_body.strip()}\n"
        "\n"
        "# Your task\n"
        "\n"
        f"{task.strip()}\n"
    )


@contextmanager
def _temporary_run_env(identity: RunIdentity, session: str) -> Generator[None, None, None]:
    """Make ``identity`` + ``session`` the ambient run-tree env for the block.

    The Codex request-builder (``prepare_codex_request`` -> ``stamp_run_identity``) and
    ``emit_direct_llm_usage`` both read the run-tree triple (and ``FORGE_SESSION``) from
    ``os.environ``, so setting them here is what places the curation event and the
    ``codex exec`` run under one root. Saves and restores the prior values -- including
    absence -- on exit, even on exception, so this core op never leaks run identity into
    the rest of the process.
    """
    keys = (FORGE_RUN_ID_VAR, FORGE_ROOT_RUN_ID_VAR, FORGE_PARENT_RUN_ID_VAR, _FORGE_SESSION_VAR)
    saved = {key: os.environ.get(key) for key in keys}
    try:
        os.environ[FORGE_RUN_ID_VAR] = identity.run_id
        os.environ[FORGE_ROOT_RUN_ID_VAR] = identity.root_run_id
        os.environ.pop(FORGE_PARENT_RUN_ID_VAR, None)  # a fresh root has no parent
        os.environ[_FORGE_SESSION_VAR] = session
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


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
) -> CodexBridgeResult:
    """Hand ``parent``'s curated transfer to a headless ``codex exec`` run implementing ``task``.

    Mints a fresh run tree, assembles a Codex-targeted curated transfer from the parent
    session, prepends it to the task as the ``codex exec`` initial message, and runs Codex
    in ``cwd`` (expected to be a git worktree) -- so the curation ``core.llm`` event and the
    ``codex_exec`` event share one root.

    Raises ``ForgeOpError`` for an unknown strategy, a missing parent, or a non-ready Codex
    runtime (with setup guidance). The Codex run's own success/failure is reported on the
    returned ``CodexBridgeResult.codex`` rather than raised. A curation fallback (e.g. no
    curation credential, so ai-curated degrades to structured) is not an error: Codex still
    runs and ``curation_ran`` reports it.
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

    # Fail closed if Codex can't run (mirrors validate_proxy_startup); the message names
    # the setup path. Runs `codex doctor` (~20s) once -- the bridge is a real launch.
    try:
        preflight = assert_codex_ready()
    except CodexPreflightError as e:
        raise ForgeOpError(f"Codex runtime not ready: {e}") from e

    root = new_root_run_identity()
    sess = session or parent
    # Unique per run: ``ensure_child`` "leaves an existing child alone" (a durability
    # guarantee for user-curated Claude resume), so a fixed key would feed Codex a stale
    # snapshot on re-runs. The run id makes each bridge run its own immutable snapshot.
    child = f"{parent}-codex-{root.run_id[-6:]}"

    with _temporary_run_env(root, sess):
        transfer = assemble_transfer_context(
            parent_name=parent,
            parent_state=parent_state,
            forge_root=forge_root,
            strategy=resume_strategy,
            depth=depth,
            get_session=_get,
            child_name=child,
            target_runtime="codex",
        )
        composed = compose_child_context(forge_root, parent, child)
        frontmatter, body, _ = parse_transfer_frontmatter(composed)
        full_prompt = compose_codex_initial_message(body, task)

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

    # schema=="full" is stamped only for a successful ai-curated body (design appendix
    # §M.1); any deterministic fallback is "compatibility-fallback".
    curation_ran = frontmatter is not None and frontmatter.get("schema") == "full"

    return CodexBridgeResult(
        parent=parent,
        child=child,
        transfer_path=transfer.context_file or child_path(forge_root, parent, child),
        root_run_id=root.root_run_id,
        codex=result,
        curation_ran=curation_ran,
    )
