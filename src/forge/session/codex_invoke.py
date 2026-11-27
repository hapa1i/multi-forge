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
import struct
import subprocess
import sys
from collections.abc import Mapping, Sequence

from forge.core.invoker.codex import CodexSandbox
from forge.core.invoker.codex import _build_codex_proxy_env as _build_codex_proxy_env
from forge.core.invoker.codex import sanitize_codex_child_env
from forge.core.reactive.env import (
    FORGE_AUTHORITY_MARKER_VAR,
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_RUN_ID_VAR,
    RunIdentity,
)
from forge.core.runtime.codex_feedback import prepare_executor_launch
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.core.runtime.codex_proxy_launch import (
    CodexProxyLaunch,
    openrouter_launch_defaults,
)
from forge.core.runtime.codex_proxy_launch import passthrough_model as passthrough_model
from forge.core.runtime.codex_proxy_launch import provider_overrides

logger = logging.getLogger(__name__)

_FORGE_SESSION_VAR = "FORGE_SESSION"
_FORGE_FORGE_ROOT_VAR = "FORGE_FORGE_ROOT"
# Linux rejects any single exec argument longer than MAX_ARG_STRLEN: 32 pages, counting its NUL.
_MAX_ARG_STRLEN_PAGES = 32
# Room for the selected executable path, executor identity and authority marker added at launch.
_ARG_MAX_HEADROOM_BYTES = 16 * 1024


def max_initial_prompt_bytes(*, argv: Sequence[str], env: Mapping[str, str]) -> int | None:
    """Return the largest UTF-8 prompt this host can pass as the TUI's positional argument.

    ``argv`` excludes the prompt. Count the sanitized child environment, native options,
    NUL terminators and pointer arrays explicitly; only bounded launch metadata uses headroom.
    ``None`` means the host reports no argument limit.
    """
    limits: list[int] = []
    if sys.platform.startswith("linux"):
        limits.append(_MAX_ARG_STRLEN_PAGES * os.sysconf("SC_PAGE_SIZE") - 1)
    arg_max = os.sysconf("SC_ARG_MAX")
    if arg_max > 0:
        environment = sum(len(os.fsencode(key)) + len(os.fsencode(value)) + 2 for key, value in env.items())
        arguments = sum(len(os.fsencode(arg)) + 1 for arg in argv)
        # One prompt pointer and two array terminators, plus the prompt's own NUL byte.
        pointers = (len(argv) + len(env) + 3) * struct.calcsize("P")
        limits.append(arg_max - environment - arguments - pointers - 1 - _ARG_MAX_HEADROOM_BYTES)
    return min(limits) if limits else None


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
    authority_marker: str | None = None,
    extra_args: Sequence[str] = (),
    proxy_launch: CodexProxyLaunch | None = None,
) -> int:
    """Run the ``codex`` TUI in the foreground; return its exit code.

    ``run_identity`` is required, not minted here: the caller's transfer-curation
    usage event (emitted under ``_temporary_run_env``) and this TUI must share one
    run-tree root -- a mint-when-absent default would silently fork the tree.
    ``resume_thread_id`` reattaches via ``codex resume <thread_id>``; it is never
    combined with ``initial_prompt`` (a reattach has no first message to deliver).
    ``extra_args`` are launch-only Codex options; they precede the positional thread
    id or prompt because Codex stops option parsing at the first positional.

    ``FORGE_SESSION`` + ``FORGE_FORGE_ROOT`` are set so trust-enrolled Codex hooks
    (``codex-session-start``, ``codex-policy-check``) resolve this session's store
    (both probe-verified to reach the hook env, stage 50c).
    """
    argv, env = build_codex_interactive_launch(
        preflight=preflight,
        session_name=session_name,
        forge_root=forge_root,
        run_identity=run_identity,
        sandbox=sandbox,
        resume_thread_id=resume_thread_id,
        initial_prompt=initial_prompt,
        authority_marker=authority_marker,
        extra_args=extra_args,
        proxy_launch=proxy_launch,
        cwd=cwd,
    )
    logger.debug("Launching interactive codex (cwd=%s, resume=%s)", cwd, resume_thread_id)
    argv = prepare_executor_launch(argv, env, cwd=cwd)
    result = subprocess.run(argv, env=env, cwd=cwd, stdin=None, stdout=None, stderr=None)
    return result.returncode


def build_codex_interactive_launch(
    *,
    preflight: CodexPreflight,
    session_name: str,
    forge_root: str,
    run_identity: RunIdentity,
    sandbox: CodexSandbox = "workspace-write",
    resume_thread_id: str | None = None,
    initial_prompt: str | None = None,
    authority_marker: str | None = None,
    extra_args: Sequence[str] = (),
    proxy_launch: CodexProxyLaunch | None = None,
    cwd: str | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Build the same arguments and child environment for pre-launch sizing and invocation."""
    if resume_thread_id is not None and initial_prompt is not None:
        raise ValueError("resume_thread_id and initial_prompt are mutually exclusive")

    # --sandbox placement is per-form: `codex resume` declares its own -s/--sandbox
    # (codex 0.139.0 `codex resume --help`), and a root-level flag is not guaranteed to
    # propagate into the subcommand's flow -- pass it where each form documents it.
    env = sanitize_codex_child_env(preflight, proxy_launch=proxy_launch)
    argv: list[str] = ["codex"]
    if proxy_launch is not None:
        argv.extend(proxy_launch.provider_args(run_identity, extra_args, env=env, cwd=cwd or os.getcwd()))
    if resume_thread_id is not None:
        argv += ["resume", "--sandbox", sandbox, *extra_args, resume_thread_id]
    else:
        argv += ["--sandbox", sandbox, *extra_args]
        if initial_prompt is not None:
            # The positional prompt is visible to same-host process listings (ps,
            # /proc/<pid>/cmdline). For sensitive context on a shared host, prefer
            # --context-delivery hook (out-of-band additionalContext); see session.md.
            # Callers check max_initial_prompt_bytes() first: exec rejects larger prompts with E2BIG.
            argv.append(initial_prompt)

    env[_FORGE_SESSION_VAR] = session_name
    env[_FORGE_FORGE_ROOT_VAR] = forge_root
    from forge.session.store import SessionStore
    from forge.session.workers import SESSION_INSTANCE_ENV

    store = SessionStore(forge_root, session_name)
    instance_id = store.review_identity() if store.exists() else None
    env.pop(SESSION_INSTANCE_ENV, None)
    if instance_id is not None:
        env[SESSION_INSTANCE_ENV] = instance_id
    env[FORGE_RUN_ID_VAR] = run_identity.run_id
    env[FORGE_ROOT_RUN_ID_VAR] = run_identity.root_run_id
    env.pop(FORGE_PARENT_RUN_ID_VAR, None)  # an interactive launch is its own root
    env.pop(FORGE_AUTHORITY_MARKER_VAR, None)
    if authority_marker is not None:
        env[FORGE_AUTHORITY_MARKER_VAR] = authority_marker

    return argv, env


def invoke_codex_bare_proxy(
    *,
    base_url: str,
    sandbox: CodexSandbox = "workspace-write",
    model: str | None = None,
    passthrough: Sequence[str] = (),
    direct_openrouter: bool = False,
    cwd: str | None = None,
) -> int:
    """Run the codex TUI foreground through a Forge proxy; return its exit code.

    Sessionless and fully scrubbed: no FORGE_SESSION, no native codex/OpenAI auth (the
    proxy owns upstream auth; codex authenticates only to the loopback proxy). The
    terminal is inherited -- the TUI owns stdin/stdout/stderr.
    """
    cwd = cwd or os.getcwd()
    env = _build_codex_proxy_env()
    if direct_openrouter:
        passthrough = [
            *openrouter_launch_defaults(passthrough, env=env, cwd=cwd),
            *passthrough,
        ]
    argv = _build_codex_proxy_argv(base_url=base_url, sandbox=sandbox, model=model, passthrough=passthrough)
    logger.debug(
        "Launching proxy-backed codex (base_url=%s, sandbox=%s, model=%s)",
        base_url,
        sandbox,
        model,
    )
    result = subprocess.run(argv, env=env, cwd=cwd, stdin=None, stdout=None, stderr=None)
    return result.returncode


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
    select a model with a model flag or a top-level model config override.
    """
    argv = ["codex", "--sandbox", sandbox, *provider_overrides(base_url)]
    if model and passthrough_model(passthrough) is None:
        argv += ["-m", model]
    argv += list(passthrough)
    return argv
