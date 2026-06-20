"""Canonical types for LLM client abstraction.

These types provide a provider-agnostic interface for LLM interactions.
All client implementations convert to/from these canonical types.
"""

from typing import Any, Literal, Self, get_args

from pydantic import BaseModel, Field, model_validator

ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh"]
Verbosity = Literal["low", "medium", "high", "xhigh", "max"]
MessageRole = Literal["system", "user", "assistant", "tool"]
StreamEventType = Literal["text_delta", "tool_call_delta", "response_end", "usage", "error"]
# Client-side prompt caching policy (NOT provider mechanism)
# Provider mechanisms (auto, explicit, context_cache_api) are in model_catalog.yaml
PromptCachingPolicy = Literal["passthrough", "auto_inject"]

REASONING_EFFORT_LEVELS: tuple[str, ...] = get_args(ReasoningEffort)


def validate_reasoning_effort(value: str | None) -> None:
    """Raise ValueError if ``value`` is not a valid core.llm ``ReasoningEffort``.

    ``None`` is allowed (means "send no reasoning_effort; use the model default").
    This is the tier-1 plan-checker vocabulary; the ``claude --effort`` CLI
    vocabulary (which adds ``max``, drops ``none``) lives in ``forge.core.effort``.
    """
    if value is not None and value not in REASONING_EFFORT_LEVELS:
        raise ValueError(f"reasoning_effort must be one of {', '.join(REASONING_EFFORT_LEVELS)}, got {value!r}")


class ThinkingConfig(BaseModel):
    """Direct thinking mode control (Gemini/Claude extended thinking)."""

    type: Literal["enabled", "disabled", "adaptive"] = "enabled"
    budget_tokens: int = 8192

    @model_validator(mode="after")
    def validate_budget_tokens(self) -> Self:
        """Validate budget_tokens is positive when thinking is enabled/adaptive."""
        if self.type in ("enabled", "adaptive") and self.budget_tokens <= 0:
            raise ValueError("budget_tokens must be positive when thinking is enabled")
        return self


class InjectionPoint(BaseModel):
    """Typed injection point for auto_inject cache control.

    Specifies where to add cache_control directives in messages.
    """

    location: Literal["message"] = "message"
    role: Literal["system", "user", "assistant"] | None = None
    index: int | None = None  # Target by index (-1 = last message)


class PromptCachingConfig(BaseModel):
    """Client-side prompt caching configuration for LLM calls.

    Policies (client behavior):
    - passthrough: Honor caller's cache_control if provided (default)
    - auto_inject: Force cache_control injection even if caller didn't specify
                   (uses LiteLLM's cache_control_injection_points)

    Note: Provider mechanisms (auto, explicit, context_cache_api) are defined
    in model_catalog.yaml under prompt_caching.mechanism, not here.
    """

    policy: PromptCachingPolicy = "passthrough"
    # For auto_inject policy: where to inject cache_control
    injection_points: list[InjectionPoint] | None = None

    @model_validator(mode="after")
    def validate_injection_points(self) -> Self:
        """Validate injection_points is provided when policy is auto_inject."""
        if self.policy == "auto_inject" and not self.injection_points:
            # Default: cache system messages
            self.injection_points = [InjectionPoint(location="message", role="system")]
        return self


class ModelHyperparameters(BaseModel):
    """Provider-agnostic parameters for LLM calls.

    Timeout and prompt caching are operational parameters that vary by model:
    - Reasoning models (GPT-5, o3) need longer timeouts (180-300s)
    - Fast models (GPT-4o-mini, Haiku) can use shorter timeouts (30-60s)
    - Prompt caching mode controls whether cache_control is passed through or auto-injected
    """

    max_tokens: int = 4096
    temperature: float | None = None
    top_p: float | None = None
    reasoning_effort: ReasoningEffort | None = None
    thinking: ThinkingConfig | None = None
    verbosity: Verbosity | None = None
    timeout: int | None = None  # Request timeout in seconds (None = use model default)
    prompt_caching: PromptCachingConfig | None = None
    strict: bool = False  # Raise UnsupportedParamError instead of warn+ignore
    # Provider-specific extras, namespaced: {"openai": {...}, "anthropic": {...}}
    extra: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_hyperparameters(self) -> Self:
        """Validate numeric hyperparameters are within valid ranges.

        Catches invalid values early rather than failing at the LLM provider.
        """
        if self.max_tokens <= 0:
            raise ValueError(f"max_tokens must be positive, got {self.max_tokens}")
        if self.max_tokens > 1_000_000:
            raise ValueError(f"max_tokens exceeds maximum (1M), got {self.max_tokens}")

        if self.temperature is not None:
            if not 0.0 <= self.temperature <= 2.0:
                raise ValueError(f"temperature must be between 0.0 and 2.0, got {self.temperature}")

        if self.top_p is not None:
            if not 0.0 <= self.top_p <= 1.0:
                raise ValueError(f"top_p must be between 0.0 and 1.0, got {self.top_p}")

        if self.timeout is not None:
            if self.timeout <= 0:
                raise ValueError(f"timeout must be positive, got {self.timeout}")
            if self.timeout > 600:
                raise ValueError(f"timeout exceeds maximum (600s), got {self.timeout}")

        return self


class ToolCall(BaseModel):
    """Canonical tool call representation (stable across providers).

    Represents a complete, parsed tool call ready for execution.
    """

    id: str
    name: str
    arguments: dict[str, Any]  # Parsed arguments (not raw JSON string)


class ToolCallDelta(BaseModel):
    """Partial tool call for streaming (accumulate until complete).

    During streaming, tool calls arrive in fragments. Accumulate these
    deltas until the stream completes, then parse into ToolCall.

    OpenAI streaming sends `id` only on the first chunk for each tool call.
    Subsequent argument chunks use `index` (integer) to correlate.
    """

    index: int | None = None  # OpenAI tool call index (stable across chunks)
    id: str | None = None
    name: str | None = None
    arguments_json: str = ""  # Raw JSON fragment, parse when complete


class Message(BaseModel):
    """Canonical message format."""

    role: MessageRole
    content: str | list[dict[str, Any]]  # text or content blocks
    tool_call_id: str | None = None  # For role="tool" responses
    tool_calls: list[ToolCall] | None = None  # For role="assistant" with tool use


class ProviderTraceMeta(BaseModel):
    """Provider-side trace metadata, lifted from the upstream response (Phase 2).

    Carries the *provider's own* identifiers and routing facts so the proxy boundary can
    populate a provider-trace plane -- kept strictly separate from Forge's synthetic
    ``chatcmpl-<ts>`` response id. Every field is optional/defaulted: old providers and
    test fakes that build ``CompletionResponse(text=...)`` must keep working, and any
    single surface (e.g. a header-only id) may be absent without breaking the rest.
    """

    provider: str | None = None  # "openrouter" / "litellm" / ...
    provider_response_id: str | None = None  # body.id (non-streaming)
    provider_generation_id: str | None = None  # OpenRouter gen-... (chunk.id / body.id)
    provider_request_id: str | None = None  # upstream request-id header, when present
    selected_provider: str | None = None  # the upstream the provider routed to
    headers: dict[str, str] | None = None  # allowlisted correlation headers only (never auth)
    provider_session_id: str | None = None  # the session/user value Forge sent, if recognized


class CompletionResponse(BaseModel):
    """Canonical completion response."""

    text: str
    tool_calls: list[ToolCall] | None = None
    usage: dict[str, int] | None = None  # {prompt_tokens, completion_tokens, total_tokens}
    # Route-reported cost in USD (OpenRouter body usage.cost / LiteLLM response-cost header).
    # None = the route reported no cost. Reporter/confidence are derived at the proxy.
    cost_usd: float | None = None
    # Provider-side trace metadata (provider/generation ids, selected upstream, allowlisted
    # headers). None for providers/fakes that don't populate it; dropped at the Anthropic
    # translation boundary, so it never reaches the client.
    provider_meta: ProviderTraceMeta | None = None
    raw: dict[str, Any] | None = None  # Original provider response (debugging only)


class StreamEvent(BaseModel):
    """Canonical streaming event.

    For type="response_end", tool_calls contains the finalized list of
    complete ToolCall objects accumulated from tool_call_delta events.
    """

    type: StreamEventType
    text: str | None = None
    tool_call_delta: ToolCallDelta | None = None
    tool_calls: list[ToolCall] | None = None  # Finalized tool calls at response_end
    usage: dict[str, int] | None = None
    # Route-reported cost in USD, carried on the final usage/response_end event.
    # None = no cost reported on this stream. Reporter/confidence derived at the proxy.
    cost_usd: float | None = None
    # Provider-side trace metadata, carried on the final usage/response_end event (Phase 2).
    provider_meta: ProviderTraceMeta | None = None
    error: str | None = None
