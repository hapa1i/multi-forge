"""LLM client protocol definition."""

from typing import Any, AsyncGenerator, Callable, Protocol

from .types import CompletionResponse, Message, ModelHyperparameters, StreamEvent


class LLMClient(Protocol):
    """Async-first LLM client protocol.

    All provider implementations must implement this interface.
    The client is async-first; use SyncAdapter for synchronous usage.
    """

    @property
    def model(self) -> str:
        """The model this client is configured for."""
        ...

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        hyperparams: ModelHyperparameters | None = None,
        on_provider_dispatch: Callable[[], None] | None = None,
    ) -> CompletionResponse:
        """Non-streaming completion.

        Args:
            messages: List of messages in the conversation.
            tools: Optional list of tool definitions (JSON Schema format).
            hyperparams: Optional hyperparameters to override client defaults.
            on_provider_dispatch: Optional callback fired immediately before provider I/O.

        Returns:
            CompletionResponse with text, optional tool_calls, and usage.
        """
        ...

    def stream(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        hyperparams: ModelHyperparameters | None = None,
        on_provider_dispatch: Callable[[], None] | None = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Streaming completion.

        Yields canonical StreamEvent objects. For tool calls, accumulate
        ToolCallDelta events until response_end, then parse into ToolCall.

        Note: Returns an async generator directly (not an async def).
        Use `async for event in client.stream(...)` to iterate.

        Args:
            messages: List of messages in the conversation.
            tools: Optional list of tool definitions (JSON Schema format).
            hyperparams: Optional hyperparameters to override client defaults.
            on_provider_dispatch: Optional callback fired immediately before provider I/O.

        Yields:
            StreamEvent objects (text_delta, tool_call_delta, response_end, usage, error).
        """
        ...

    async def count_tokens(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        """Estimate token count for messages and tools.

        Accuracy varies by provider. Use for rough estimates only.

        Args:
            messages: List of messages to count.
            tools: Optional list of tool definitions to include in count.

        Returns:
            Estimated token count.
        """
        ...
