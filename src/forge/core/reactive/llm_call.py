"""Shared transport for synchronous single-call LLM consumers."""

from __future__ import annotations

import time

from forge.core.llm.detection import ProviderType
from forge.core.llm.types import CompletionResponse, Message, ModelHyperparameters


def complete_llm_call(
    *,
    model: str,
    messages: list[Message],
    provider: ProviderType | None = None,
    hyperparams: ModelHyperparameters | None = None,
) -> tuple[CompletionResponse, float, str | None]:
    """Complete one synchronous LLM call and return response, latency, and request id.

    A request id is attached only when the resolved client target is a known Forge
    proxy. Parsing, telemetry emission, and failure handling remain caller-owned.
    """
    from forge.core.llm import SyncAdapter, get_client
    from forge.core.llm.credentials import resolve_provider_base_url
    from forge.core.usage import (
        mint_request_id,
        resolve_client_base_url,
        target_is_forge_proxy,
        with_forge_request_id,
    )

    adapter = SyncAdapter(get_client(model, provider=provider))
    base_url = resolve_provider_base_url(provider) if provider is not None else resolve_client_base_url(model)
    request_id = mint_request_id() if target_is_forge_proxy(base_url) else None
    call_hyperparams = with_forge_request_id(hyperparams, request_id) if request_id else hyperparams

    start = time.monotonic()
    response = adapter.complete(messages, hyperparams=call_hyperparams)
    latency_ms = (time.monotonic() - start) * 1000
    return response, latency_ms, request_id
