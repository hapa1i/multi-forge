"""Shared helpers for OpenAI-compatible LLM clients.

Used by both LiteLLMClient and OpenRouterClient. Extracted here so the
OpenRouter client has no import dependency on LiteLLM.
"""

import json
import logging
from typing import Any

from openai import APIError, APIStatusError, RateLimitError

from ..errors import ProviderError
from ..types import (
    CompletionResponse,
    Message,
    ModelHyperparameters,
    ProviderTraceMeta,
    ToolCall,
    ToolCallDelta,
)

logger = logging.getLogger(__name__)


def is_retryable_error(error: Exception) -> bool:
    """Return True if the error should trigger tenacity retry.

    Only retries transient errors (rate limits, server errors).
    Auth failures (401/403) are excluded -- retrying with the same
    bad credentials just adds ~14s of delay.
    """
    if isinstance(error, APIStatusError):
        return error.status_code not in (400, 401, 403)
    if isinstance(error, (RateLimitError, APIError)):
        return True
    return False


def extract_cached_tokens(usage: object) -> int:
    """Extract cached_tokens from a usage object's prompt_tokens_details.

    LiteLLM and OpenRouter pass through provider cache metrics in
    ``usage.prompt_tokens_details.cached_tokens``.  The field may be an
    object (SDK model) or a plain dict depending on the response path.

    Returns 0 if no cache data is present.
    """
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    if prompt_details is None and isinstance(usage, dict):
        prompt_details = usage.get("prompt_tokens_details")
    if not prompt_details:
        return 0
    if isinstance(prompt_details, dict):
        raw = prompt_details.get("cached_tokens", 0) or 0
    else:
        raw = getattr(prompt_details, "cached_tokens", 0) or 0
    return int(raw)


def extract_reported_cost_usd(usage: object) -> float | None:
    """Extract route-reported cost (USD) from an OpenAI-shaped usage object.

    OpenRouter includes ``usage.cost`` (total spend in USD) in the response
    body when usage accounting is available; it is auto-included, so we read
    it when present rather than depending on a request flag. The typed SDK
    surfaces it as an attribute (and in ``model_extra``); the dict path covers
    responses already serialized to JSON.

    Returns None when no cost field is present (cost unavailable, not $0).
    """
    cost = getattr(usage, "cost", None)
    if cost is None and isinstance(usage, dict):
        cost = usage.get("cost")
    if cost is None:
        extra = getattr(usage, "model_extra", None)  # SDK stashes unknown fields here
        if isinstance(extra, dict):
            cost = extra.get("cost")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)):
        return None
    return float(cost)


def message_to_openai(msg: Message) -> dict[str, Any]:
    """Convert canonical Message to OpenAI chat completion format."""
    result: dict[str, Any] = {"role": msg.role, "content": msg.content}

    if msg.tool_call_id:
        result["tool_call_id"] = msg.tool_call_id

    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments),
                },
            }
            for tc in msg.tool_calls
        ]

    return result


def build_chat_completion_kwargs(
    model: str,
    messages: list[Message],
    tools: list[dict[str, Any]] | None,
    hyperparams: ModelHyperparameters,
) -> dict[str, Any]:
    """Build kwargs for OpenAI chat.completions.create()."""
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [message_to_openai(m) for m in messages],
        "max_tokens": hyperparams.max_tokens,
    }

    if hyperparams.temperature is not None:
        kwargs["temperature"] = hyperparams.temperature

    if hyperparams.top_p is not None:
        kwargs["top_p"] = hyperparams.top_p

    if hyperparams.reasoning_effort is not None:
        kwargs["reasoning_effort"] = hyperparams.reasoning_effort

    if hyperparams.verbosity is not None:
        kwargs["verbosity"] = hyperparams.verbosity

    if tools:
        kwargs["tools"] = tools

    if "openai" in hyperparams.extra:
        kwargs.update(hyperparams.extra["openai"])

    return kwargs


def provider_trace_meta(response: Any, provider: str) -> ProviderTraceMeta:
    """Build provider-trace metadata from a non-streaming OpenAI-shaped response (Phase 2).

    ``body.id`` carries the provider response id; for OpenRouter that id is the ``gen-…``
    generation id (probe 1), surfaced as ``provider_generation_id``. ``selected_provider``
    is the upstream OpenRouter routed to, reported in the body's ``provider`` field (read
    from ``model_extra`` when the typed SDK stashed it there).
    """
    response_id = getattr(response, "id", None)
    response_id = response_id if isinstance(response_id, str) else None
    generation_id = response_id if response_id and response_id.startswith("gen-") else None

    selected = getattr(response, "provider", None)
    if selected is None:
        extra = getattr(response, "model_extra", None)
        if isinstance(extra, dict):
            selected = extra.get("provider")

    return ProviderTraceMeta(
        provider=provider,
        provider_response_id=response_id,
        provider_generation_id=generation_id,
        selected_provider=selected if isinstance(selected, str) else None,
    )


# A deliberately tiny allowlist of correlation header names lifted into
# ProviderTraceMeta.headers (Phase 2). Header *values* are retained and can themselves be
# identifiers, so anything not listed here is dropped -- never "everything except auth".
# Auth/cookie/set-cookie headers are excluded by omission, not by a denylist.
_PROVIDER_TRACE_HEADER_ALLOWLIST = frozenset(
    {
        "x-request-id",  # generic request correlation id
        "x-generation-id",  # OpenRouter gen-... id header carrier
        "x-litellm-call-id",  # LiteLLM per-call id
        "x-litellm-model-id",  # LiteLLM resolved model id
    }
)


def provider_trace_headers(headers: Any) -> dict[str, str] | None:
    """Return only the allowlisted correlation headers (lowercased name -> value), or None.

    A fixed name-allowlist (:data:`_PROVIDER_TRACE_HEADER_ALLOWLIST`): non-string names/values
    and anything not on the list are dropped, so a response's auth/cookie headers never enter
    the trace plane. Returns None when nothing allowlisted is present (keeps the field unset).
    """
    if headers is None:
        return None
    try:
        pairs = list(headers.items())  # httpx.Headers and dict both expose .items()
    except (AttributeError, TypeError):
        return None
    out: dict[str, str] = {}
    for name, value in pairs:
        if isinstance(name, str) and isinstance(value, str) and name.lower() in _PROVIDER_TRACE_HEADER_ALLOWLIST:
            out[name.lower()] = value
    return out or None


def merge_provider_headers(completion: CompletionResponse, headers: Any, provider: str) -> CompletionResponse:
    """Attach allowlisted correlation headers to ``completion.provider_meta`` (Phase 2).

    Used by the non-streaming/Responses paths that hold a raw-response handle (direct
    OpenRouter + LiteLLM); streaming has no headers, so its ``provider_meta.headers`` stays
    None. Creates a ``provider_meta`` when the completion has none yet.
    """
    trace_headers = provider_trace_headers(headers)
    if not trace_headers:
        return completion
    meta = completion.provider_meta or ProviderTraceMeta(provider=provider)
    return completion.model_copy(update={"provider_meta": meta.model_copy(update={"headers": trace_headers})})


def openai_response_to_completion(response: Any, provider: str) -> CompletionResponse:
    """Convert OpenAI ChatCompletion response to canonical CompletionResponse."""
    if hasattr(response, "error") and response.error:
        error_msg = response.error.get("message", "Unknown error")
        error_code = response.error.get("code", "unknown")
        raise ProviderError(
            provider,
            Exception(f"API error (code={error_code}): {error_msg}"),
        )

    if not response.choices:
        raise ProviderError(
            provider,
            Exception("No choices in response"),
        )

    choice = response.choices[0]
    message = choice.message

    text = message.content or ""

    tool_calls = None
    if message.tool_calls:
        tool_calls = []
        for tc in message.tool_calls:
            try:
                arguments = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=arguments,
                )
            )

    usage = None
    cost_usd = None
    if response.usage:
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
        cached = extract_cached_tokens(response.usage)
        if cached:
            usage["cached_tokens"] = cached
        cost_usd = extract_reported_cost_usd(response.usage)

    return CompletionResponse(
        text=text,
        tool_calls=tool_calls,
        usage=usage,
        cost_usd=cost_usd,
        provider_meta=provider_trace_meta(response, provider),
        raw=response.model_dump(),
    )


class ToolCallAccumulator:
    """Accumulates streaming tool call deltas into complete ToolCalls.

    During streaming, tool calls arrive as fragments (id, name, argument chunks).
    OpenAI sends `id` only on the first chunk; subsequent chunks use `index`
    to correlate. This accumulator uses index-based lookup to handle both.
    """

    def __init__(self) -> None:
        self._pending: dict[int, ToolCallDelta] = {}

    def add_delta(self, delta: ToolCallDelta) -> None:
        """Add a streaming delta to the accumulator."""
        idx = delta.index
        if idx is None:
            return

        if idx not in self._pending:
            self._pending[idx] = ToolCallDelta(index=idx)

        existing = self._pending[idx]
        if delta.id:
            existing.id = delta.id
        if delta.name:
            existing.name = delta.name
        existing.arguments_json += delta.arguments_json

    def finalize(self) -> list[ToolCall]:
        """Parse accumulated deltas into complete ToolCalls.

        Returns tool calls sorted by index for deterministic ordering.
        """
        result = []
        for idx in sorted(self._pending):
            delta = self._pending[idx]
            if delta.id and delta.name:
                try:
                    arguments = json.loads(delta.arguments_json) if delta.arguments_json else {}
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse tool call arguments: {delta.arguments_json}")
                    arguments = {}

                result.append(
                    ToolCall(
                        id=delta.id,
                        name=delta.name,
                        arguments=arguments,
                    )
                )
            elif delta.arguments_json:
                logger.warning(
                    f"Dropping incomplete tool call at index {idx}: "
                    f"id={delta.id}, name={delta.name}, args_len={len(delta.arguments_json)}"
                )
        return result

    def has_pending(self) -> bool:
        """Check if there are any pending tool calls."""
        return len(self._pending) > 0

    def default_index(self) -> int | None:
        """Suggest an index for an unindexed single-tool delta.

        Returns 0 when no calls are pending (first tool call), the sole
        pending index when exactly one exists (continuation), or None
        when multiple calls are pending (ambiguous -- caller should drop).
        """
        if len(self._pending) == 0:
            return 0
        if len(self._pending) == 1:
            return next(iter(self._pending))
        return None
