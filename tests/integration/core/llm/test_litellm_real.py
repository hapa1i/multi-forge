"""Real integration tests that call LiteLLM providers.

These tests make actual API calls - use cheap/fast models.

Run with: pytest tests/integration/core/llm/ -v -m slow

Configuration:
  - Uses unified config (config.proxy.litellm.base_url) via template
  - Tests load litellm-gemini-test template for port 4001 access

For local LiteLLM tests:
  - Local LiteLLM must be running on port 4001 (test instance, avoids conflict with dev)
  - GEMINI_API_KEY must be set (for local LiteLLM to authenticate with Gemini)
  - Start test LiteLLM: forge model backend start litellm --port 4001
  - Stop test LiteLLM: forge model backend stop litellm-4001
"""

import os
import socket

import pytest

from forge.core.llm import (
    Message,
    ModelHyperparameters,
    SyncAdapter,
    get_client,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]  # asyncio marker applied per-class (sync tests exist)


def _is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def _has_local_litellm_access() -> bool:
    """Check if local LiteLLM access is available.

    Checks:
    1. Local LiteLLM is running (port 4001 responds - test instance)
    2. GEMINI_API_KEY is set (local LiteLLM needs it)
    3. Local LiteLLM base URL is configured via template (litellm-gemini-test)

    Note: These tests call `core.llm` directly, so we load the litellm-gemini-test
    template to configure the base URL for port 4001.

    Uses port 4001 for test isolation (port 4000 is for local development).
    """
    # Check if local LiteLLM is running on test port
    if not _is_port_open("localhost", 4001):
        return False

    # Check if we have API key for local LiteLLM
    if not os.environ.get("GEMINI_API_KEY"):
        return False

    # base_url is resolved at runtime from backend_dependency.port or
    # LITELLM_LOCAL_BASE_URL env var — no need to check config here.
    return True


def _require_local_litellm() -> None:
    """Guard: fail if local LiteLLM not available.

    Call at the start of tests that require local LiteLLM.
    This ensures tests FAIL (not skip) when dependencies are missing.
    """
    if not _has_local_litellm_access():
        pytest.fail(
            "Local LiteLLM not available. Requires:\n"
            "  - LiteLLM running on port 4001 (test instance)\n"
            "  - GEMINI_API_KEY set\n"
            "  - litellm-gemini-test template loadable\n"
            "Run: make test-integration (handles prerequisites automatically)"
        )


@pytest.mark.asyncio
class TestLiteLLMRemoteReal:
    """Real tests against remote LiteLLM (TR proxy)."""

    async def test_complete_simple(self):
        """Test simple completion with remote LiteLLM."""
        client = get_client("openai/gpt-4o-mini")
        response = await client.complete(
            [Message(role="user", content="Say 'hello' and nothing else")],
            hyperparams=ModelHyperparameters(max_tokens=50),
        )
        assert "hello" in response.text.lower()
        assert response.usage is not None
        assert response.usage["total_tokens"] > 0

    async def test_stream_simple(self):
        """Test streaming completion with remote LiteLLM."""
        client = get_client("openai/gpt-4o-mini")
        chunks = []

        async for event in client.stream(
            [Message(role="user", content="Count from 1 to 3, one number per line")],
            hyperparams=ModelHyperparameters(max_tokens=50),
        ):
            if event.type == "text_delta":
                chunks.append(event.text or "")
            elif event.type == "response_end":
                # Verify we got the response_end event
                pass

        assert len(chunks) > 0
        full_text = "".join(chunks)
        assert "1" in full_text and "2" in full_text

    async def test_system_message(self):
        """Test with system message."""
        client = get_client("openai/gpt-4o-mini")
        response = await client.complete(
            [
                Message(
                    role="system",
                    content="You are a helpful assistant that only responds with 'YES' or 'NO'.",
                ),
                Message(role="user", content="Is the sky blue?"),
            ],
            hyperparams=ModelHyperparameters(max_tokens=10),
        )
        assert "yes" in response.text.lower() or "no" in response.text.lower()

    async def test_conversation(self):
        """Test multi-turn conversation."""
        client = get_client("openai/gpt-4o-mini")

        # First turn
        response1 = await client.complete(
            [Message(role="user", content="My name is Alice.")],
            hyperparams=ModelHyperparameters(max_tokens=50),
        )

        # Second turn
        response2 = await client.complete(
            [
                Message(role="user", content="My name is Alice."),
                Message(role="assistant", content=response1.text),
                Message(role="user", content="What is my name?"),
            ],
            hyperparams=ModelHyperparameters(max_tokens=50),
        )

        assert "alice" in response2.text.lower()

    async def test_gpt5_tool_roundtrip_with_reasoning_and_verbosity(self) -> None:
        """GPT-5 Responses API should handle tools plus reasoning/verbosity in a real tool workflow."""
        client = get_client("openai/gpt-5-mini")
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "lookup_ticket",
                    "description": "Look up a ticket by ticket_id and return triage details.",
                    "strict": True,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ticket_id": {"type": "string"},
                        },
                        "required": ["ticket_id"],
                        "additionalProperties": False,
                    },
                },
            }
        ]
        params = ModelHyperparameters(
            max_tokens=96,
            reasoning_effort="medium",
            verbosity="low",
        )
        opening_messages = [
            Message(
                role="system",
                content="You are a release triage assistant. When a user asks about a ticket, call lookup_ticket first.",
            ),
            Message(
                role="user",
                content="Summarize ticket T-123. You must call lookup_ticket exactly once before answering.",
            ),
        ]

        first = await client.complete(opening_messages, tools=tools, hyperparams=params)

        assert first.tool_calls is not None and len(first.tool_calls) == 1
        tool_call = first.tool_calls[0]
        assert tool_call.name == "lookup_ticket"
        assert str(tool_call.arguments.get("ticket_id", "")).upper() == "T-123"
        assert first.raw is not None
        assert first.raw["finish_reason"] == "tool_calls"

        follow_up_messages = opening_messages + [
            Message(role="assistant", content=first.text, tool_calls=first.tool_calls),
            Message(
                role="tool",
                tool_call_id=tool_call.id,
                content=(
                    '{"ticket_id":"T-123","status":"open","severity":"high",'
                    '"summary":"Database migration fails in staging"}'
                ),
            ),
        ]
        second = await client.complete(follow_up_messages, hyperparams=params)

        assert second.text
        lowered = second.text.lower()
        assert "database" in lowered or "staging" in lowered
        assert second.usage is not None
        assert second.usage["total_tokens"] > 0


class TestLiteLLMSyncAdapter:
    """Sync adapter tests (not async)."""

    def test_sync_adapter_ask(self):
        """Test SyncAdapter.ask() for Policy use case."""
        client = SyncAdapter(get_client("openai/gpt-4o-mini"))
        response = client.ask(
            "What is 2+2? Reply with just the number.",
            hyperparams=ModelHyperparameters(max_tokens=10),
        )
        assert "4" in response


@pytest.mark.asyncio
class TestLiteLLMLocalReal:
    """Real tests against local LiteLLM (personal API keys)."""

    @pytest.fixture(autouse=True)
    def _load_test_template(self, monkeypatch):
        """Load litellm-gemini-test template for all tests in this class."""
        from forge.config import init_config

        # Override .env dev URL (port 4000) with test URL (port 4001)
        monkeypatch.setenv("LITELLM_LOCAL_BASE_URL", "http://localhost:4001")

        # Initialize config singleton with test template for port 4001
        init_config(template="litellm-gemini-test")

    async def test_complete_simple_gemini(self) -> None:
        """Test simple completion with local LiteLLM (Gemini)."""
        _require_local_litellm()

        client = get_client("gemini/gemini-2.5-flash")
        response = await client.complete(
            [Message(role="user", content="What is 2+2? Reply with just the number.")],
            hyperparams=ModelHyperparameters(max_tokens=50),
        )
        assert "4" in response.text

    async def test_stream_simple_gemini(self) -> None:
        """Test streaming with local LiteLLM (Gemini)."""
        _require_local_litellm()

        client = get_client("gemini/gemini-2.5-flash")
        chunks = []

        async for event in client.stream(
            [Message(role="user", content="Count from 1 to 3")],
            hyperparams=ModelHyperparameters(max_tokens=50),
        ):
            if event.type == "text_delta":
                chunks.append(event.text or "")

        assert len(chunks) > 0
        full_text = "".join(chunks)
        assert "1" in full_text


@pytest.mark.asyncio
class TestTokenCounting:
    """Tests for token counting functionality."""

    async def test_count_tokens_basic(self):
        """Test basic token counting."""
        client = get_client("openai/gpt-4o-mini")
        count = await client.count_tokens(
            [
                Message(role="user", content="Hello, world!"),
            ]
        )
        # Simple estimation, should be > 0
        assert count > 0

    async def test_count_tokens_conversation(self):
        """Test token counting for multi-turn conversation."""
        client = get_client("openai/gpt-4o-mini")

        short_count = await client.count_tokens(
            [
                Message(role="user", content="Hi"),
            ]
        )

        long_count = await client.count_tokens(
            [
                Message(role="user", content="Hi"),
                Message(role="assistant", content="Hello! How can I help you today?"),
                Message(role="user", content="Can you explain quantum computing in detail?"),
            ]
        )

        assert long_count > short_count


@pytest.mark.asyncio
class TestErrorHandling:
    """Tests for error handling with real API."""

    async def test_invalid_model_name(self):
        """Test handling of invalid model name."""
        client = get_client("openai/nonexistent-model-12345")

        # Should raise a ProviderError
        from forge.core.llm.errors import ProviderError

        with pytest.raises(ProviderError):
            await client.complete(
                [
                    Message(role="user", content="Hello"),
                ]
            )
