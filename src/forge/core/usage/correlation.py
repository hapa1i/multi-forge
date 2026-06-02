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
