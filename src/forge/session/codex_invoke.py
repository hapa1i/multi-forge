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
import os
import subprocess
from collections.abc import Sequence

from forge.core.invoker.codex import (
    _CODEX_CHILD_STRIP_VARS,
    CodexSandbox,
    sanitize_codex_child_env,
)
from forge.core.reactive.env import (
    FORGE_DEPTH_VAR,
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_PROXY_WIRE_SHAPE_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_RUN_ID_VAR,
    RunIdentity,
    get_forge_depth,
)
from forge.core.runtime.codex_preflight import CodexPreflight

logger = logging.getLogger(__name__)

_FORGE_SESSION_VAR = "FORGE_SESSION"
_FORGE_FORGE_ROOT_VAR = "FORGE_FORGE_ROOT"

# Sessionless proxy-launch env scrub: the session-managed identity AND the native OpenAI
# account/routing vars, on top of the shared codex child strip set. Because the proxy owns
# upstream auth, _build_codex_proxy_env (unlike sanitize_codex_child_env) re-establishes NO
# native codex auth -- codex authenticates only to the loopback proxy via the token below.
_CODEX_BARE_PROXY_STRIP_VARS: tuple[str, ...] = (
    *_CODEX_CHILD_STRIP_VARS,  # CODEX_*/ANTHROPIC_*/FORGE_SUBPROCESS_* (shared core)
    _FORGE_SESSION_VAR,
    _FORGE_FORGE_ROOT_VAR,
    "FORGE_FORK_NAME",
    "FORGE_PARENT_SESSION",
    FORGE_RUN_ID_VAR,
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_PROXY_WIRE_SHAPE_VAR,
    # No native OpenAI account leakage. OPENAI_API_KEY is load-bearing (a stale inherited key
    # breaks the first turn); the rest are defense-in-depth -- the custom forge_proxy provider
    # supplies its own base_url, so OPENAI_BASE_URL can't reroute, but stripping the whole
    # account/routing set honors the no-leak promise.
    "OPENAI_API_KEY",
    "OPENAI_ORGANIZATION",
    "OPENAI_ORG_ID",
    "OPENAI_PROJECT",
    "OPENAI_BASE_URL",
)

# Codex reads the loopback bearer from this env var (-c ...env_key="FORGE_CODEX_PROXY_TOKEN").
# Any non-empty value works: the proxy owns the real upstream credential and does not validate
# this inbound token; codex just needs *a* token to populate the Authorization header.
_FORGE_CODEX_PROXY_TOKEN_VAR = "FORGE_CODEX_PROXY_TOKEN"
_FORGE_CODEX_PROXY_TOKEN_VALUE = "forge-loopback"


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
            # The positional prompt is visible to same-host process listings (ps,
            # /proc/<pid>/cmdline). For sensitive context on a shared host, prefer
            # --context-delivery hook (out-of-band additionalContext); see session.md.
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


def invoke_codex_bare_proxy(
    *,
    base_url: str,
    sandbox: CodexSandbox = "workspace-write",
    model: str | None = None,
    passthrough: Sequence[str] = (),
    cwd: str | None = None,
) -> int:
    """Run the codex TUI foreground through a Forge proxy; return its exit code.

    Sessionless and fully scrubbed: no FORGE_SESSION, no native codex/OpenAI auth (the
    proxy owns upstream auth; codex authenticates only to the loopback proxy). The
    terminal is inherited -- the TUI owns stdin/stdout/stderr.
    """
    argv = _build_codex_proxy_argv(base_url=base_url, sandbox=sandbox, model=model, passthrough=passthrough)
    env = _build_codex_proxy_env()
    logger.debug("Launching proxy-backed codex (base_url=%s, sandbox=%s, model=%s)", base_url, sandbox, model)
    result = subprocess.run(argv, env=env, cwd=cwd or os.getcwd(), stdin=None, stdout=None, stderr=None)
    return result.returncode


def _build_codex_proxy_env() -> dict[str, str]:
    """Build the scrubbed env for a sessionless proxy-backed codex launch.

    Strips the session/run-tree identity and the OpenAI account/routing vars, advances
    FORGE_DEPTH (codex can shell out to ``forge``), and sets the loopback proxy token.
    Establishes NO native codex auth -- that is the session-managed path's job.
    """
    env = os.environ.copy()
    for var in _CODEX_BARE_PROXY_STRIP_VARS:
        env.pop(var, None)
    env[FORGE_DEPTH_VAR] = str(get_forge_depth(env) + 1)
    env[_FORGE_CODEX_PROXY_TOKEN_VAR] = _FORGE_CODEX_PROXY_TOKEN_VALUE
    return env


def _build_codex_proxy_argv(
    *,
    base_url: str,
    sandbox: CodexSandbox,
    model: str | None,
    passthrough: Sequence[str],
) -> list[str]:
    """Build the list-mode argv registering a custom forge_proxy provider over the loopback proxy.

    The ``-c`` overrides point codex at ``{base_url}/v1`` with ``wire_api="responses"``; a
    custom provider means codex needs no OpenAI login. Inner double-quotes are literal tokens
    (list-mode argv, no shell) -- matching the proven shell-quoted probe. Never pass
    ``--strict-config``. ``model`` auto-defaults ``-m`` only when the user did not already
    pass ``-m``/``--model`` (user intent wins).
    """
    proxy_v1 = f"{base_url.rstrip('/')}/v1"
    argv: list[str] = [
        "codex",
        "--sandbox",
        sandbox,
        "-c",
        "model_provider=forge_proxy",
        "-c",
        'model_providers.forge_proxy.name="Forge Proxy"',
        "-c",
        f'model_providers.forge_proxy.base_url="{proxy_v1}"',
        "-c",
        'model_providers.forge_proxy.wire_api="responses"',
        "-c",
        f'model_providers.forge_proxy.env_key="{_FORGE_CODEX_PROXY_TOKEN_VAR}"',
    ]
    if model and not _passthrough_has_model(passthrough):
        argv += ["-m", model]
    argv += list(passthrough)
    return argv


def _passthrough_has_model(passthrough: Sequence[str]) -> bool:
    """Whether the user already supplied a model flag, so the auto-default ``-m`` is suppressed."""
    return any(arg in ("-m", "--model") or arg.startswith("--model=") for arg in passthrough)
