"""Interactive Codex TUI launcher (codex_frontend Phase 5).

Foreground sibling of ``session/claude/invoke.py`` for the Codex runtime: launches the
``codex`` TUI with the terminal inherited (the TUI owns stdin/stdout/stderr), so there
is no JSONL stream to parse -- the caller reconciles thread identity post-exit from the
observation receipt or rollout discovery (``core/ops/codex_interactive.py``).
Deliberately NOT routed through ``CodexHeadlessInvoker``, and emits no usage event: the
TUI reports no usage Forge can attribute (mirrors the reserved ``claude_interactive``
route).
"""

from __future__ import annotations

import logging
import subprocess

from forge.core.invoker.codex import CodexSandbox, sanitize_codex_child_env
from forge.core.reactive.env import (
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_RUN_ID_VAR,
    RunIdentity,
)
from forge.core.runtime.codex_preflight import CodexPreflight

logger = logging.getLogger(__name__)

_FORGE_SESSION_VAR = "FORGE_SESSION"
_FORGE_FORGE_ROOT_VAR = "FORGE_FORGE_ROOT"


def invoke_codex_interactive(
    *,
    preflight: CodexPreflight,
    session_name: str,
    forge_root: str,
    cwd: str,
    run_identity: RunIdentity,
    sandbox: CodexSandbox = "workspace-write",
    resume_thread_id: str | None = None,
    initial_prompt: str | None = None,
) -> int:
    """Run the ``codex`` TUI in the foreground; return its exit code.

    ``run_identity`` is required, not minted here: the caller's transfer-curation
    usage event (emitted under ``_temporary_run_env``) and this TUI must share one
    run-tree root -- a mint-when-absent default would silently fork the tree.
    ``resume_thread_id`` reattaches via ``codex resume <thread_id>``; it is never
    combined with ``initial_prompt`` (a reattach has no first message to deliver).

    ``FORGE_SESSION`` + ``FORGE_FORGE_ROOT`` are set so trust-enrolled Codex hooks
    (``codex-session-start``, ``codex-policy-check``) resolve this session's store
    (both probe-verified to reach the hook env, stage 50c).
    """
    if resume_thread_id is not None and initial_prompt is not None:
        raise ValueError("resume_thread_id and initial_prompt are mutually exclusive")

    # --sandbox placement is per-form: `codex resume` declares its own -s/--sandbox
    # (codex 0.139.0 `codex resume --help`), and a root-level flag is not guaranteed to
    # propagate into the subcommand's flow -- pass it where each form documents it.
    argv: list[str] = ["codex"]
    if resume_thread_id is not None:
        argv += ["resume", "--sandbox", sandbox, resume_thread_id]
    else:
        argv += ["--sandbox", sandbox]
        if initial_prompt is not None:
            argv.append(initial_prompt)

    env = sanitize_codex_child_env(preflight)
    env[_FORGE_SESSION_VAR] = session_name
    env[_FORGE_FORGE_ROOT_VAR] = forge_root
    env[FORGE_RUN_ID_VAR] = run_identity.run_id
    env[FORGE_ROOT_RUN_ID_VAR] = run_identity.root_run_id
    env.pop(FORGE_PARENT_RUN_ID_VAR, None)  # an interactive launch is its own root

    logger.debug("Launching interactive codex (cwd=%s, resume=%s)", cwd, resume_thread_id)
    result = subprocess.run(argv, env=env, cwd=cwd, stdin=None, stdout=None, stderr=None)
    return result.returncode
