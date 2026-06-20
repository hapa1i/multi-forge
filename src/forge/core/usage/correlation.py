"""Direct-path request correlation primitives (Phase 4c).

When Forge itself is the HTTP client (a ``core.llm`` call, not a ``claude -p``
subprocess), it can mint an ``X-Request-ID`` and forward it as a request header.
If that call happens to hit a Forge proxy, the proxy honors the inbound id
(``server.py``: ``request.headers.get("X-Request-ID") or ...``) and writes its
cost/audit records under the same id -- making ``source_refs.cost_request_id`` an
exact join key. Against an external provider the header is harmlessly ignored and
no Forge cost record exists, so the caller leaves ``cost_request_id`` null rather
than dangling.

The ``claude -p`` case (Forge is NOT the client) is out of scope here -- that is
the deferred proxied-correlation slice (4g).
"""

from __future__ import annotations

import logging
import os
import uuid

from forge.core.llm import ModelHyperparameters

logger = logging.getLogger(__name__)

_FORGE_REQUEST_ID_HEADER = "X-Request-ID"


def mint_request_id() -> str:
    """Mint a request id (mirrors the proxy's ``req_`` prefix in server.py)."""
    return f"req_{uuid.uuid4().hex[:12]}"


def with_forge_request_id(
    hyperparams: ModelHyperparameters | None,
    request_id: str,
) -> ModelHyperparameters:
    """Return hyperparameters with ``X-Request-ID`` added to the OpenAI headers.

    Merges into ``extra["openai"]["extra_headers"]`` so both the Chat Completions
    and Responses paths forward it, without clobbering any header the caller
    already set. Returns a copy -- the caller's instance is never mutated.

    Args:
        hyperparams: Existing hyperparameters, or None to start from defaults.
        request_id: The id to forward (mint via :func:`mint_request_id`).
    """
    base = hyperparams.model_copy(deep=True) if hyperparams is not None else ModelHyperparameters()
    openai_extra = dict(base.extra.get("openai", {}))
    headers = dict(openai_extra.get("extra_headers", {}))
    headers[_FORGE_REQUEST_ID_HEADER] = request_id
    openai_extra["extra_headers"] = headers
    base.extra = {**base.extra, "openai": openai_extra}
    return base


def with_openrouter_user(
    hyperparams: ModelHyperparameters | None,
    user_id: str,
) -> ModelHyperparameters:
    """Return hyperparameters with the OpenRouter ``user`` grouping id set.

    Merges into ``extra["openai"]["user"]`` so the OpenAI-compatible client forwards
    it as a top-level ``user`` field (``build_chat_completion_kwargs`` does
    ``kwargs.update(extra["openai"])``), where OpenRouter reads it for account-side
    ``/generation`` grouping. Never clobbers a ``user`` the caller already set, and
    preserves sibling ``openai`` extras (e.g. an ``extra_headers`` X-Request-ID).
    Returns a copy -- the caller's instance is never mutated.

    Args:
        hyperparams: Existing hyperparameters, or None to start from defaults.
        user_id: The opaque grouping id (mint via :func:`resolve_direct_provider_user`).
    """
    base = hyperparams.model_copy(deep=True) if hyperparams is not None else ModelHyperparameters()
    openai_extra = dict(base.extra.get("openai", {}))
    openai_extra.setdefault("user", user_id)
    base.extra = {**base.extra, "openai": openai_extra}
    return base


def resolve_direct_provider_user(role: str | None = None) -> str | None:
    """The OpenRouter ``user`` grouping id for a direct (non-proxied) call, or None.

    Gated on the global ``provider_trace.inject_provider_user`` toggle. Reads the
    ambient run identity from the environment and derives the SAME opaque id the
    proxied path stamps into ``X-Forge-Session`` (:func:`derive_provider_session_id`),
    so a run's direct and proxied OpenRouter calls group identically account-side.

    Returns None when the flag is off, or when no run identity is present (a bare
    ``forge resume`` outside a run tree). Best-effort: never raises -- a grouping id
    is telemetry, not correctness, so any failure degrades to "no grouping".

    The caller is responsible for the route gate (inject only when the call targets
    OpenRouter); this resolver only answers "what id, if any, should we group under".

    Args:
        role: Optional role suffix (e.g. ``"plan-check"``) for per-role grouping;
            canonicalized by ``derive_provider_session_id`` via ``sanitize_label``.
    """
    try:
        from forge.runtime_config import get_runtime_config

        if not get_runtime_config().provider_trace.inject_provider_user:
            return None

        from forge.core.reactive.env import (
            FORGE_ROOT_RUN_ID_VAR,
            FORGE_RUN_ID_VAR,
            FORGE_SESSION_VAR,
        )
        from forge.core.run_id import derive_provider_session_id

        session = os.environ.get(FORGE_SESSION_VAR)
        # Mirror the proxied path (reactive/env.py): root falls back to the run id when
        # FORGE_ROOT_RUN_ID is unset, so a root-level call still derives a stable id.
        root_run_id = os.environ.get(FORGE_ROOT_RUN_ID_VAR) or os.environ.get(FORGE_RUN_ID_VAR)
        if not session and not root_run_id:
            return None
        return derive_provider_session_id(session, root_run_id or "", role)
    except Exception as e:
        logger.debug("resolve_direct_provider_user(role=%s) failed: %s", role, e)
        return None


def resolve_client_base_url(model: str) -> str | None:
    """The base_url a ``core.llm`` client will use for ``model`` (synchronously).

    Mirrors the client's own resolution (provider detection -> sync base_url
    derivation) so a sync caller can tell whether a direct call will hit a Forge
    proxy. Returns None for a direct-API provider (Anthropic) or on any failure.
    """
    try:
        from forge.core.llm.credentials import resolve_provider_base_url
        from forge.core.llm.detection import detect_provider

        return resolve_provider_base_url(detect_provider(model))
    except Exception as e:
        logger.debug("resolve_client_base_url(%s) failed: %s", model, e)
        return None


def target_is_forge_proxy(base_url: str | None) -> bool:
    """True if ``base_url`` is a known Forge proxy endpoint.

    Reverse-lookup in the proxy registry (``~/.forge/proxies/index.json``).
    Best-effort: any failure (no registry, unreadable, lookup error) returns
    False -- callers must not stamp ``cost_request_id`` unless this is certain,
    or the ledger would carry a back-reference to a cost record that never
    materialized.
    """
    if not base_url:
        return False
    try:
        from forge.proxy.proxies import ProxyRegistryStore, lookup_proxy_by_base_url

        registry = ProxyRegistryStore().read()
        return lookup_proxy_by_base_url(registry, base_url.rstrip("/")) is not None
    except Exception as e:
        logger.debug("target_is_forge_proxy(%s) failed, treating as non-proxy: %s", base_url, e)
        return False
