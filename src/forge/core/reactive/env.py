"""Environment builder for Claude subprocess invocation.

Provides ``build_claude_env()`` for constructing subprocess environments,
``FORGE_DEPTH`` helpers for recursion-guarding hook → subprocess chains, and
the run-tree identity (``FORGE_RUN_ID``/``FORGE_PARENT_RUN_ID``/
``FORGE_ROOT_RUN_ID``) used for usage attribution. Run identity is orthogonal
to depth: depth guards recursion, identity records who-spawned-whom.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

from forge.core.run_id import (
    ANTHROPIC_CUSTOM_HEADERS_VAR,
    FORGE_COMMAND_HEADER,
    FORGE_ROOT_RUN_ID_HEADER,
    FORGE_RUN_ID_HEADER,
    FORGE_SESSION_HEADER,
    derive_provider_session_id,
    mint_run_id,
    sanitize_label,
)

logger = logging.getLogger(__name__)

# Defense-in-depth: --bare prevents hook recursion in child processes,
# but FORGE_DEPTH still guards against subprocess spawning at depth >= 2.
FORGE_DEPTH_VAR = "FORGE_DEPTH"
FORGE_MAX_DEPTH = 2

# Run-tree identity (orthogonal to FORGE_DEPTH). Composes like depth: a root
# mints its own run_id and is its own root; a child inherits root_run_id and
# sets parent_run_id to the spawner's run_id. Used for usage attribution, not
# recursion guarding.
FORGE_RUN_ID_VAR = "FORGE_RUN_ID"
FORGE_PARENT_RUN_ID_VAR = "FORGE_PARENT_RUN_ID"
FORGE_ROOT_RUN_ID_VAR = "FORGE_ROOT_RUN_ID"

# Provider session/command correlation. FORGE_SESSION
# (the human session name, already set by the session-start path) and FORGE_COMMAND (the
# spawn's role) are hashed/sanitized into the X-Forge-Session / X-Forge-Command headers by
# _apply_correlation_headers. Local Forge<->proxy correlation only; dropped before the
# upstream call. session_start.py / codex_invoke.py keep their own "FORGE_SESSION" literal
# to stay import-light (leaf/hook discipline); the value is shared by convention.
FORGE_SESSION_VAR = "FORGE_SESSION"
FORGE_COMMAND_VAR = "FORGE_COMMAND"

CLAUDE_CODE_ATTRIBUTION_HEADER_VAR = "CLAUDE_CODE_ATTRIBUTION_HEADER"
FORGE_SUBPROCESS_PROXY_VAR = "FORGE_SUBPROCESS_PROXY"
FORGE_SUBPROCESS_BASE_URL_VAR = "FORGE_SUBPROCESS_BASE_URL"
FORGE_SUBPROCESS_PROXY_ID_VAR = "FORGE_SUBPROCESS_PROXY_ID"
FORGE_SUBPROCESS_TEMPLATE_VAR = "FORGE_SUBPROCESS_TEMPLATE"
FORGE_PROXY_WIRE_SHAPE_VAR = "FORGE_PROXY_WIRE_SHAPE"
FORGE_SIDECAR_VAR = "FORGE_SIDECAR"
FORGE_FORGE_ROOT_VAR = "FORGE_FORGE_ROOT"
FORGE_SIDECAR_HOST_FORGE_ROOT_VAR = "FORGE_SIDECAR_HOST_FORGE_ROOT"
FORGE_SIDECAR_HOST_WORKTREE_PATH_VAR = "FORGE_SIDECAR_HOST_WORKTREE_PATH"
FORGE_LAUNCH_MODE_VAR = "FORGE_LAUNCH_MODE"
FORGE_TEMPLATE_VAR = "FORGE_TEMPLATE"

ANTHROPIC_PASSTHROUGH_WIRE_SHAPE = "anthropic_passthrough"
OPENAI_TRANSLATED_WIRE_SHAPE = "openai_translated"

# --bare (Claude Code >= 2.1.81) disables OAuth/keychain auth, requiring
# ANTHROPIC_API_KEY in the environment. Only safe when the key is present.
_BARE_AUTH_KEY = "ANTHROPIC_API_KEY"


def can_use_bare(env: Mapping[str, str] | None = None) -> bool:
    """True if ``--bare`` is safe for headless subprocesses.

    ``--bare`` disables OAuth/keychain auth, so it requires
    ANTHROPIC_API_KEY. When an explicit ``env`` dict is given, checks
    only that dict (caller owns the env). When using os.environ
    (default), also falls back to the credential file via
    ``resolve_env_or_credential`` (which respects ``auth_ignore_env``).
    """
    if env is not None:
        return bool(env.get(_BARE_AUTH_KEY))

    from forge.core.auth.template_secrets import resolve_env_or_credential

    return bool(resolve_env_or_credential(_BARE_AUTH_KEY))


def get_forge_depth(env: Mapping[str, str] | None = None) -> int:
    """Read current FORGE_DEPTH from the given env (or os.environ).

    Invalid or missing values are treated as 0 (fail-open).
    """
    source = env if env is not None else os.environ
    raw = source.get(FORGE_DEPTH_VAR, "0")
    try:
        return max(0, int(raw))
    except (ValueError, TypeError):
        return 0


def should_spawn_subprocesses(env: Mapping[str, str] | None = None) -> bool:
    """True if current depth allows spawning ``claude -p`` subprocesses.

    Returns False when depth >= FORGE_MAX_DEPTH, meaning hooks should skip
    subprocess-spawning work (supervisor, memory writer, etc.) to prevent
    runaway recursion.
    """
    return get_forge_depth(env) < FORGE_MAX_DEPTH


@dataclass(frozen=True)
class RunIdentity:
    """Attribution identity for one Forge-spawned process in the run tree.

    ``run_id`` identifies this process; ``parent_run_id`` is the spawner's
    run_id (None at the root); ``root_run_id`` is the tree root. Composes like
    FORGE_DEPTH and is orthogonal to it — depth guards recursion, identity
    records who-spawned-whom for usage attribution.
    """

    run_id: str
    parent_run_id: str | None
    root_run_id: str

    def as_env(self) -> dict[str, str]:
        """Render the run-tree env vars (parent omitted when None)."""
        env = {FORGE_RUN_ID_VAR: self.run_id, FORGE_ROOT_RUN_ID_VAR: self.root_run_id}
        if self.parent_run_id:
            env[FORGE_PARENT_RUN_ID_VAR] = self.parent_run_id
        return env


def get_run_identity(env: Mapping[str, str] | None = None) -> RunIdentity | None:
    """Read the current process's run identity from ``env`` (or os.environ).

    Returns None when FORGE_RUN_ID is unset (the process is not part of a run
    tree). A missing root falls back to ``run_id`` (the process is its own root).
    """
    source = env if env is not None else os.environ
    run_id = source.get(FORGE_RUN_ID_VAR)
    if not run_id:
        return None
    return RunIdentity(
        run_id=run_id,
        parent_run_id=source.get(FORGE_PARENT_RUN_ID_VAR) or None,
        root_run_id=source.get(FORGE_ROOT_RUN_ID_VAR) or run_id,
    )


def new_root_run_identity() -> RunIdentity:
    """Mint a fresh root identity (no parent; it is its own root).

    Used by interactive frontends (session/bare launch) and the sidecar, which
    begin a new run tree rather than continuing the spawner's.
    """
    run_id = mint_run_id()
    return RunIdentity(run_id=run_id, parent_run_id=None, root_run_id=run_id)


def derive_child_run_identity(env: Mapping[str, str] | None = None) -> RunIdentity:
    """Compose a child identity from the spawner's env (root-inheriting).

    Mints a fresh run_id; ``parent_run_id`` is the spawner's run_id;
    ``root_run_id`` is inherited from the spawner (or the new run_id when the
    spawner has no identity, i.e. the child is itself a new root). Mirrors
    ``get_forge_depth``'s read-from-env model. A stale ``FORGE_PARENT_RUN_ID``
    in the source env is ignored — parent is always recomputed from the
    spawner's ``FORGE_RUN_ID``.
    """
    parent = get_run_identity(env)
    run_id = mint_run_id()
    if parent is None:
        return RunIdentity(run_id=run_id, parent_run_id=None, root_run_id=run_id)
    return RunIdentity(run_id=run_id, parent_run_id=parent.run_id, root_run_id=parent.root_run_id)


def stamp_run_identity(env: dict[str, str], *, derive: bool = True) -> None:
    """Stamp the run-tree triple (FORGE_RUN_ID/PARENT/ROOT) into ``env`` in place.

    Runtime-neutral: shared by ``build_claude_env`` and the Codex request-builder, so a
    ``codex exec`` child joins the same run tree as its Claude parent (Phase 5 "one run
    tree"). When ``derive`` is True, derive a child identity from the spawner's
    ``FORGE_RUN_ID`` already in ``env`` (parent = spawner, root inherited); when False,
    leave the triple the caller supplied untouched (the process IS the root). Proxy
    correlation headers and ``FORGE_DEPTH`` are deliberately NOT stamped here -- those
    are Claude-proxy and recursion-guard concerns the caller owns.
    """
    if not derive:
        return
    child = derive_child_run_identity(env)
    env[FORGE_RUN_ID_VAR] = child.run_id
    env[FORGE_ROOT_RUN_ID_VAR] = child.root_run_id
    if child.parent_run_id:
        env[FORGE_PARENT_RUN_ID_VAR] = child.parent_run_id
    else:
        env.pop(FORGE_PARENT_RUN_ID_VAR, None)


def build_claude_env(
    base_url: str | None = None,
    extra_vars: dict[str, str] | None = None,
    direct: bool = False,
    derive_run_identity: bool = True,
    interactive: bool = False,
) -> dict[str, str]:
    """Build environment dict for a Claude subprocess.

    Starts with the current process environment. Sets ANTHROPIC_BASE_URL
    if ``base_url`` is provided. When ``direct`` is True, removes any
    inherited ANTHROPIC_BASE_URL and subprocess proxy so the child hits
    Anthropic directly.
    Applies ``extra_vars`` before routing and depth handling so explicit
    function arguments remain authoritative.

    Hydrates ANTHROPIC_API_KEY from the credential file when it's not in
    the env (or when ``auth_ignore_env`` overrides it). This ensures
    ``can_use_bare(env)`` and the subprocess both see the resolved key.

    Args:
        base_url: Proxy URL to route Claude requests through.
        extra_vars: Additional environment variables to set/override.
        direct: Force direct Anthropic routing (unset inherited proxy URL).
        derive_run_identity: When True (default, the headless-spawn case),
            derive a child run identity from the spawner's env and stamp the
            run-tree vars. When False, leave the run-tree vars from
            ``extra_vars`` untouched — used by interactive frontends that
            supply an explicit root identity (so the process IS the root, not
            a child of itself).
        interactive: When True, skip the inline ANTHROPIC_API_KEY hydrate; the
            interactive frontend calls ``apply_interactive_api_key`` as the final
            step so the key policy (``interactive_anthropic_api_key``) wins over
            ``extra_vars``. Orthogonal to ``derive_run_identity`` (auth omission is
            not run-identity rooting). Headless callers leave this False.

    Returns:
        Complete environment dict ready for ``subprocess.run(env=...)``.
    """
    env = os.environ.copy()
    # Interactive launches finalize ANTHROPIC_API_KEY last (after extra_vars and
    # unset_vars) via apply_interactive_api_key, so skip the early hydrate to avoid
    # a redundant write the finalizer would only overwrite. Headless callers keep
    # the inline hydrate so can_use_bare(env) and the subprocess agree.
    if not interactive:
        _hydrate_credentials(env)

    # Apply extra_vars AFTER hydration so explicit caller overrides
    # take precedence over credential-file values.
    if extra_vars:
        env.update(extra_vars)

    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url
    elif direct:
        env.pop("ANTHROPIC_BASE_URL", None)
        env.pop(FORGE_SUBPROCESS_PROXY_VAR, None)
        env.pop(FORGE_SUBPROCESS_BASE_URL_VAR, None)
        env.pop(FORGE_SUBPROCESS_PROXY_ID_VAR, None)
        env.pop(FORGE_SUBPROCESS_TEMPLATE_VAR, None)
        env.pop(FORGE_PROXY_WIRE_SHAPE_VAR, None)
    else:
        # No explicit base_url and not forced direct: check subprocess proxy fallback.
        # FORGE_SUBPROCESS_PROXY is set by `forge session start --subprocess-proxy`
        # and inherited by all child processes.
        injected_subprocess_base_url = env.get(FORGE_SUBPROCESS_BASE_URL_VAR)
        if injected_subprocess_base_url:
            env["ANTHROPIC_BASE_URL"] = injected_subprocess_base_url
        elif subprocess_proxy := env.get(FORGE_SUBPROCESS_PROXY_VAR):
            resolved = _resolve_subprocess_proxy(subprocess_proxy)
            if resolved:
                env["ANTHROPIC_BASE_URL"] = resolved
            else:
                env.pop("ANTHROPIC_BASE_URL", None)

    apply_attribution_header_policy(env)

    # Increment FORGE_DEPTH so child subprocesses know their nesting level
    current_depth = get_forge_depth(env)
    env[FORGE_DEPTH_VAR] = str(current_depth + 1)

    # Stamp the run-tree identity (orthogonal to FORGE_DEPTH). stamp_run_identity reads
    # the spawner's FORGE_RUN_ID from `env` BEFORE we overwrite it, so the child's parent
    # is the spawner and the root is inherited. derive_run_identity=False means the caller
    # supplied an explicit identity (e.g. an interactive root) via extra_vars.
    stamp_run_identity(env, derive=derive_run_identity)
    if derive_run_identity:
        # Slice 4g: stamp run-tree correlation headers for a proxy-routed headless
        # child so the Forge proxy can attribute its cost records to this run tree.
        # Gated to a *proven* Forge proxy (never an opaque gateway) and to
        # derive_run_identity=True (headless), so interactive sessions are excluded.
        _apply_correlation_headers(env)

    return env


def apply_attribution_header_policy(env: dict[str, str]) -> None:
    """Scope Claude Code's attribution-header suppression to translated proxies.

    ``CLAUDE_CODE_ATTRIBUTION_HEADER=0`` removes a volatile Claude Code billing
    system block that defeats third-party prompt caching, but upstream reports
    show it also breaks Claude Code auto-mode's safety classifier when inherited
    into direct Anthropic launches (Claude Code #64585). Forge therefore owns
    this variable for child Claude processes: translated/third-party proxy calls
    get the cache-preserving workaround; direct and Anthropic-passthrough calls
    scrub any inherited/global value so auto mode can classify when Anthropic's
    classifier is available through the route.
    """
    if not env.get("ANTHROPIC_BASE_URL") or _proxy_wire_shape_for_env(env) == ANTHROPIC_PASSTHROUGH_WIRE_SHAPE:
        env.pop(CLAUDE_CODE_ATTRIBUTION_HEADER_VAR, None)
        return

    env[CLAUDE_CODE_ATTRIBUTION_HEADER_VAR] = "0"


def resolve_proxy_wire_shape(*, proxy_id: str | None = None, template: str | None = None) -> str | None:
    """Best-effort wire-shape lookup for attribution-header policy.

    Proxy instance config wins over template defaults because users can edit
    ``proxy.yaml``. Missing/invalid metadata returns ``None`` so unknown proxy
    routes keep the conservative translated-proxy suppression behavior.
    """
    if proxy_id:
        try:
            from forge.config.loader import load_proxy_instance_config

            proxy_config = load_proxy_instance_config(proxy_id)
            if proxy_config and proxy_config.wire_shape:
                return proxy_config.wire_shape
        except Exception as e:
            logger.debug("Could not resolve proxy wire_shape for proxy_id=%s: %s", proxy_id, e)

    if template:
        return _template_wire_shape(template)

    return None


def _template_wire_shape(template: str) -> str | None:
    try:
        import yaml

        from forge.config.loader import read_template

        data = yaml.safe_load(read_template(template))
        if not isinstance(data, dict):
            return None
        proxy = data.get("proxy")
        if not isinstance(proxy, dict):
            return None
        wire_shape = proxy.get("wire_shape", OPENAI_TRANSLATED_WIRE_SHAPE)
        return str(wire_shape) if wire_shape else OPENAI_TRANSLATED_WIRE_SHAPE
    except Exception as e:
        logger.debug("Could not resolve template wire_shape for template=%s: %s", template, e)
        return None


def _proxy_wire_shape_for_env(env: Mapping[str, str]) -> str | None:
    explicit = env.get(FORGE_PROXY_WIRE_SHAPE_VAR)
    if explicit:
        return explicit

    base_url = env.get("ANTHROPIC_BASE_URL")
    subprocess_base_url = env.get(FORGE_SUBPROCESS_BASE_URL_VAR)
    if base_url and subprocess_base_url == base_url:
        wire_shape = resolve_proxy_wire_shape(
            proxy_id=env.get(FORGE_SUBPROCESS_PROXY_ID_VAR),
            template=env.get(FORGE_SUBPROCESS_TEMPLATE_VAR),
        )
        if wire_shape:
            return wire_shape

    if base_url:
        wire_shape = _wire_shape_from_registry_base_url(base_url)
        if wire_shape:
            return wire_shape

    # Template-only sidecars have no host proxy id but do carry FORGE_TEMPLATE.
    if template := env.get(FORGE_TEMPLATE_VAR):
        return resolve_proxy_wire_shape(template=template)

    return None


def _wire_shape_from_registry_base_url(base_url: str) -> str | None:
    try:
        from forge.proxy.proxies import ProxyRegistryStore, lookup_proxy_by_base_url

        entry = lookup_proxy_by_base_url(ProxyRegistryStore().read(), base_url)
        if entry is None:
            return None
        return resolve_proxy_wire_shape(proxy_id=entry.proxy_id, template=entry.template)
    except Exception as e:
        logger.debug("Could not resolve proxy wire_shape for base_url=%s: %s", base_url, e)
        return None


def _hydrate_credentials(env: dict[str, str]) -> None:
    """Ensure resolved credentials are in the subprocess env dict.

    When ``auth_ignore_env`` is active, removes the inherited env value
    for ANTHROPIC_API_KEY and injects the credential-file value instead.
    When inactive, injects the credential-file value only if the env
    var is absent (so ``can_use_bare(env)`` and the subprocess agree).
    """
    from forge.core.auth.template_secrets import resolve_env_or_credential

    resolved = resolve_env_or_credential(_BARE_AUTH_KEY)

    try:
        from forge.runtime_config import get_runtime_config

        ignore_env = get_runtime_config().auth_ignore_env
    except Exception as e:
        logger.debug("Could not read auth_ignore_env; using environment credentials: %s", e)
        ignore_env = False

    if ignore_env:
        if resolved:
            env[_BARE_AUTH_KEY] = resolved
        else:
            env.pop(_BARE_AUTH_KEY, None)
    elif resolved and not env.get(_BARE_AUTH_KEY):
        env[_BARE_AUTH_KEY] = resolved


def _target_is_proven_forge_proxy(env: Mapping[str, str]) -> bool:
    """True only if the resolved ANTHROPIC_BASE_URL is a *proven* Forge proxy.

    Two proofs (Slice 4g leak gate). The marker path requires the marker to own the
    *selected* url: an explicit ``base_url`` arg can override routing while an
    inherited ``FORGE_SUBPROCESS_PROXY_ID`` survives ``os.environ.copy()``, so
    "marker present" alone could point at an opaque override -- require the marker's
    url to equal the resolved base_url. The registry path is host-only (the proxy
    registry isn't mounted in the sidecar); a miss degrades to no header (snapshot
    estimate), never a leak.
    """
    base_url = env.get("ANTHROPIC_BASE_URL")
    if not base_url:
        return False
    if env.get(FORGE_SUBPROCESS_PROXY_ID_VAR) and env.get(FORGE_SUBPROCESS_BASE_URL_VAR) == base_url:
        return True
    try:
        from forge.core.usage.correlation import target_is_forge_proxy

        return target_is_forge_proxy(base_url)
    except Exception as e:  # best-effort: an unreadable registry is "not proven", never a leak
        logger.debug("forge-proxy check failed for %s: %s", base_url, e)
        return False


def _apply_correlation_headers(env: dict[str, str]) -> None:
    """Stamp the Forge correlation headers into ANTHROPIC_CUSTOM_HEADERS (Slice 4g + Phase 1).

    No-ops unless the subprocess is proxy-routed to a *proven* Forge proxy, so the opaque
    ids never reach a non-Forge gateway. Up to four Forge-owned headers are stamped: the
    run-tree ids (``X-Forge-Run-ID``/``-Root-Run-ID``) and the provider grouping ids
    (``X-Forge-Session`` -- an opaque hash of the session name + role, always emittable via
    the ``forge_run_<hash>`` fallback; ``X-Forge-Command`` -- the sanitized role, only when
    a role is set). Inherited ``X-Forge-*`` lines are stripped first (the env starts from
    ``os.environ.copy()``, so a nested child inherits the parent's values), then the current
    child's values are appended; all other (user) header lines are preserved. These headers
    are consumed by the proxy and never forwarded upstream (the passthrough allowlist drops
    them).
    """
    run_id = env.get(FORGE_RUN_ID_VAR)
    if not run_id or not _target_is_proven_forge_proxy(env):
        return

    root_run_id = env.get(FORGE_ROOT_RUN_ID_VAR) or run_id
    role = env.get(FORGE_COMMAND_VAR)
    session_id = derive_provider_session_id(env.get(FORGE_SESSION_VAR), root_run_id, role)
    command = sanitize_label(role)

    forge_owned = {
        FORGE_RUN_ID_HEADER.lower(),
        FORGE_ROOT_RUN_ID_HEADER.lower(),
        FORGE_SESSION_HEADER.lower(),
        FORGE_COMMAND_HEADER.lower(),
    }
    kept: list[str] = []
    for raw in env.get(ANTHROPIC_CUSTOM_HEADERS_VAR, "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        name = line.split(":", 1)[0].strip().lower()
        if name in forge_owned:
            continue  # drop inherited Forge-owned line; re-added fresh below
        kept.append(line)
    kept.append(f"{FORGE_RUN_ID_HEADER}: {run_id}")
    kept.append(f"{FORGE_ROOT_RUN_ID_HEADER}: {root_run_id}")
    kept.append(f"{FORGE_SESSION_HEADER}: {session_id}")  # opaque grouping id, always present
    if command:
        kept.append(f"{FORGE_COMMAND_HEADER}: {command}")
    env[ANTHROPIC_CUSTOM_HEADERS_VAR] = "\n".join(kept)


@dataclass(frozen=True)
class InteractiveApiKeyDecision:
    """What an interactive Claude launch did with ANTHROPIC_API_KEY.

    ``source`` is the provenance breadcrumb recorded in the session manifest:
    ``env``/``credential_file`` (the child got the key from there), ``none`` (no
    key anywhere), or ``omitted_by_config`` (``interactive_anthropic_api_key: omit``
    withheld it). ``available`` is whether the child can see a key at all.
    """

    available: bool
    source: str


def _interactive_omit() -> bool:
    """True when ``interactive_anthropic_api_key`` is ``omit`` (fail-safe to inherit)."""
    try:
        from forge.runtime_config import get_runtime_config

        return get_runtime_config().interactive_anthropic_api_key == "omit"
    except Exception as e:
        logger.debug("Could not read interactive_anthropic_api_key; inheriting key: %s", e)
        return False


def _resolve_interactive_api_key(interactive: bool) -> tuple[str | None, str]:
    """Resolve (value, source) for an interactive child's ANTHROPIC_API_KEY.

    ``omit`` wins for interactive launches: returns ``(None, "omitted_by_config")``
    so the key is withheld. Otherwise defers to the shared source-aware resolver
    (which honors ``auth_ignore_env``). Resolving from os.environ/credential file --
    never a caller's mutated env dict -- is what lets the launch-site recorder
    reproduce the same decision the child env ends up with.
    """
    if interactive and _interactive_omit():
        return None, "omitted_by_config"
    from forge.core.auth.template_secrets import resolve_env_or_credential_with_source

    return resolve_env_or_credential_with_source(_BARE_AUTH_KEY)


def compute_interactive_api_key_decision(*, interactive: bool) -> InteractiveApiKeyDecision:
    """Decide ANTHROPIC_API_KEY provenance for an interactive launch, without mutating.

    Used by the launch-metadata recorder. Matches ``apply_interactive_api_key``
    because both resolve from os.environ/config and ``apply`` is the child's sole
    last writer of the key.
    """
    value, source = _resolve_interactive_api_key(interactive)
    return InteractiveApiKeyDecision(available=bool(value), source=source)


def apply_interactive_api_key(env: dict[str, str], *, interactive: bool) -> InteractiveApiKeyDecision:
    """Set or strip ANTHROPIC_API_KEY in ``env`` per the interactive key policy.

    Authoritative over whatever ``extra_vars`` injected: overwrites the key with the
    resolved value, or pops it for ``omit``/unresolved. Call this LAST in the
    interactive env build (after extra_vars and unset_vars). Returns the same
    decision the recorder computes.
    """
    value, source = _resolve_interactive_api_key(interactive)
    if value:
        env[_BARE_AUTH_KEY] = value
    else:
        env.pop(_BARE_AUTH_KEY, None)
    return InteractiveApiKeyDecision(available=bool(value), source=source)


def _resolve_subprocess_proxy(proxy_id: str) -> str | None:
    """Resolve subprocess proxy to a base URL, or None if unavailable.

    Direct URL lookup only (not resolve_subprocess_routing). build_claude_env()
    sets env vars for child processes and only needs a URL. Model compatibility
    validation happens at workflow routing time (resolve_invocation_routing).
    """
    try:
        from forge.core.reactive.proxy import lookup_proxy_base_url

        url = lookup_proxy_base_url(proxy_id)
        if url:
            logger.debug("Subprocess proxy %r resolved to %s", proxy_id, url)
        return url
    except Exception as e:
        logger.warning("Subprocess proxy %r unavailable: %s", proxy_id, e)
        return None
