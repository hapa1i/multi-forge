"""Tests for OpenRouter client."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.core.llm.clients.openrouter import OpenRouterClient
from forge.core.llm.types import CompletionResponse, Message, ModelHyperparameters


@pytest.fixture
def client():
    """Create an OpenRouter client with mocked credentials."""
    return OpenRouterClient(
        model="anthropic/claude-sonnet-4.6",
        provider="openrouter",
        default_hyperparams=ModelHyperparameters(max_tokens=4096),
    )


class TestOpenRouterClientInit:
    """Tests for client construction."""

    def test_model_property(self, client):
        assert client.model == "anthropic/claude-sonnet-4.6"

    def test_translates_reasoning_effort_to_extra_body(self):
        kwargs = {
            "model": "test",
            "messages": [],
            "max_tokens": 100,
            "reasoning_effort": "high",
            "temperature": 0.7,
        }
        result = OpenRouterClient._translate_params(kwargs)
        assert "reasoning_effort" not in result
        assert result["extra_body"] == {"reasoning": {"effort": "high"}}
        assert result["temperature"] == 0.7

    def test_translates_verbosity_to_extra_body(self):
        kwargs = {"model": "test", "messages": [], "verbosity": "medium"}
        result = OpenRouterClient._translate_params(kwargs)
        assert "verbosity" not in result
        assert result["extra_body"] == {"verbosity": "medium"}

    def test_translates_both_params(self):
        kwargs = {
            "model": "test",
            "messages": [],
            "reasoning_effort": "high",
            "verbosity": "low",
        }
        result = OpenRouterClient._translate_params(kwargs)
        assert result["extra_body"] == {"reasoning": {"effort": "high"}, "verbosity": "low"}

    def test_no_extra_body_when_no_params(self):
        kwargs = {"model": "test", "messages": [], "temperature": 0.5}
        result = OpenRouterClient._translate_params(kwargs)
        assert "extra_body" not in result

    def test_preserves_existing_extra_body(self):
        kwargs = {
            "model": "test",
            "messages": [],
            "reasoning_effort": "medium",
            "extra_body": {"transforms": ["middle-out"]},
        }
        result = OpenRouterClient._translate_params(kwargs)
        assert result["extra_body"]["reasoning"] == {"effort": "medium"}
        assert result["extra_body"]["transforms"] == ["middle-out"]

    def test_translate_params_keeps_user_top_level(self):
        """User channel: a top-level `user` survives translation and is NOT moved to extra_body."""
        kwargs = {"model": "test", "messages": [], "user": "forge_sess_abc123", "reasoning_effort": "high"}
        result = OpenRouterClient._translate_params(kwargs)
        assert result["user"] == "forge_sess_abc123"
        assert "user" not in result.get("extra_body", {})


class TestOpenRouterClientComplete:
    """Tests for non-streaming completion."""

    @staticmethod
    def _raw_response(headers: dict[str, str] | None = None) -> MagicMock:
        """A with_raw_response handle: .parse() -> body, .headers -> raw headers."""
        body = MagicMock()
        body.id = "gen-abc123"
        body.provider = None
        body.choices = [MagicMock(message=MagicMock(content="Hello", tool_calls=None))]
        body.usage = MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        body.usage.prompt_tokens_details = None
        body.error = None
        body.model_extra = None
        body.model_dump = MagicMock(return_value={})

        raw = MagicMock()
        raw.parse = MagicMock(return_value=body)
        raw.headers = headers if headers is not None else {}
        return raw

    @pytest.mark.asyncio
    async def test_calls_chat_completions(self, client):
        """Verify OpenRouter uses chat.completions (with_raw_response), not responses API."""
        mock_client = AsyncMock()
        mock_client.chat.completions.with_raw_response.create = AsyncMock(return_value=self._raw_response())

        mock_creds = {
            "api_key": "sk-or-test",
            "base_url": "https://openrouter.ai/api/v1",
            "extra_headers": {"X-OpenRouter-Title": "Multi-Forge"},
        }
        with patch.object(client, "_credentials") as mock_cm:
            mock_cm.get_credentials = AsyncMock(return_value=mock_creds)
            client._client = mock_client

            result = await client.complete(
                messages=[Message(role="user", content="Hello")],
            )

        mock_client.chat.completions.with_raw_response.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.with_raw_response.create.call_args[1]
        assert call_kwargs["model"] == "anthropic/claude-sonnet-4.6"
        assert "reasoning_effort" not in call_kwargs
        assert isinstance(result, CompletionResponse)
        assert result.text == "Hello"

    @pytest.mark.asyncio
    async def test_non_streaming_populates_allowlisted_headers(self, client):
        """Direct non-streaming path lifts allowlisted response headers into provider_meta (R3).

        Plain .create() dropped headers; with_raw_response keeps them so the direct path
        matches the LiteLLM path. Auth/cookie headers are excluded by the allowlist.
        """
        raw = self._raw_response(
            headers={
                "x-request-id": "req-direct-1",
                "authorization": "Bearer sk-or-secret",
                "set-cookie": "session=abc",
            }
        )
        mock_client = AsyncMock()
        mock_client.chat.completions.with_raw_response.create = AsyncMock(return_value=raw)

        with patch.object(client, "_credentials") as mock_cm:
            mock_cm.get_credentials = AsyncMock(
                return_value={"api_key": "sk-or-test", "base_url": "https://openrouter.ai/api/v1"}
            )
            client._client = mock_client

            result = await client.complete(messages=[Message(role="user", content="Hello")])

        assert result.provider_meta is not None
        assert result.provider_meta.headers == {"x-request-id": "req-direct-1"}  # only allowlisted name+value

    @pytest.mark.asyncio
    async def test_headers_set_on_client_creation(self, client):
        """Verify OpenRouter-specific headers are passed to AsyncOpenAI."""
        mock_creds = {
            "api_key": "sk-or-test",
            "base_url": "https://openrouter.ai/api/v1",
            "extra_headers": {
                "HTTP-Referer": "https://github.com/hapa1i/multi-forge",
                "X-OpenRouter-Title": "Multi-Forge",
            },
        }
        with (
            patch.object(client, "_credentials") as mock_cm,
            patch("forge.core.llm.clients.openrouter.AsyncOpenAI") as mock_openai_cls,
        ):
            mock_cm.get_credentials = AsyncMock(return_value=mock_creds)
            client._client = None

            await client._get_client()

            mock_openai_cls.assert_called_once()
            call_kwargs = mock_openai_cls.call_args[1]
            assert call_kwargs["base_url"] == "https://openrouter.ai/api/v1"
            assert call_kwargs["api_key"] == "sk-or-test"
            assert "X-OpenRouter-Title" in call_kwargs["default_headers"]

    @pytest.mark.asyncio
    async def test_user_from_extra_openai_reaches_create_kwargs(self, client):
        """Channel proof (end-to-end): a `user` under hyperparams.extra["openai"] -- exactly
        what the proxy adapter writes -- reaches chat.completions.create as a TOP-LEVEL `user`
        kwarg, surviving the client's hyperparam merge, and is never nested in extra_body."""
        mock_client = AsyncMock()
        mock_client.chat.completions.with_raw_response.create = AsyncMock(return_value=self._raw_response())

        with patch.object(client, "_credentials") as mock_cm:
            mock_cm.get_credentials = AsyncMock(
                return_value={"api_key": "sk-or-test", "base_url": "https://openrouter.ai/api/v1"}
            )
            client._client = mock_client

            await client.complete(
                messages=[Message(role="user", content="Hello")],
                hyperparams=ModelHyperparameters(max_tokens=100, extra={"openai": {"user": "forge_sess_abc123"}}),
            )

        call_kwargs = mock_client.chat.completions.with_raw_response.create.call_args[1]
        assert call_kwargs["user"] == "forge_sess_abc123"
        assert "user" not in call_kwargs.get("extra_body", {})


class TestOpenRouterClientStream:
    """Tests for streaming completion."""

    @pytest.mark.asyncio
    async def test_stream_yields_events(self, client):
        """Verify streaming yields text_delta and response_end events."""
        mock_chunk1 = MagicMock()
        mock_chunk1.usage = None
        mock_chunk1.choices = [MagicMock(delta=MagicMock(content="Hi", tool_calls=None))]

        mock_chunk2 = MagicMock()
        mock_chunk2.usage = MagicMock(prompt_tokens=10, completion_tokens=2, total_tokens=12)
        mock_chunk2.usage.prompt_tokens_details = None
        mock_chunk2.choices = []

        async def mock_stream():
            yield mock_chunk1
            yield mock_chunk2

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())

        mock_creds = {
            "api_key": "sk-or-test",
            "base_url": "https://openrouter.ai/api/v1",
            "extra_headers": {},
        }
        with patch.object(client, "_credentials") as mock_cm:
            mock_cm.get_credentials = AsyncMock(return_value=mock_creds)
            client._client = mock_client

            events = []
            async for event in client.stream(
                messages=[Message(role="user", content="Hello")],
            ):
                events.append(event)

        types = [e.type for e in events]
        assert "text_delta" in types
        assert "response_end" in types

    @pytest.mark.asyncio
    async def test_stream_captures_reported_cost(self, client):
        """OpenRouter's final usage chunk cost rides on the usage/response_end events."""
        mock_chunk1 = MagicMock()
        mock_chunk1.usage = None
        mock_chunk1.choices = [MagicMock(delta=MagicMock(content="Hi", tool_calls=None))]

        # Real usage object (not MagicMock) so extract_reported_cost_usd reads a float.
        mock_chunk2 = MagicMock()
        mock_chunk2.usage = SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=2,
            total_tokens=12,
            prompt_tokens_details=None,
            cost=0.0021,
        )
        mock_chunk2.choices = []

        async def mock_stream():
            yield mock_chunk1
            yield mock_chunk2

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())

        mock_creds = {"api_key": "sk-or-test", "base_url": "https://openrouter.ai/api/v1", "extra_headers": {}}
        with patch.object(client, "_credentials") as mock_cm:
            mock_cm.get_credentials = AsyncMock(return_value=mock_creds)
            client._client = mock_client

            events = [event async for event in client.stream(messages=[Message(role="user", content="Hello")])]

        cost_carriers = [e.cost_usd for e in events if e.cost_usd is not None]
        assert cost_carriers == [0.0021, 0.0021]  # usage + response_end events

    @pytest.mark.asyncio
    async def test_stream_provider_meta_from_first_chunk_id(self, client):
        """The gen-... id on the FIRST chunk rides on the usage/response_end events (Phase 2)."""
        chunk1 = MagicMock()
        chunk1.id = "gen-stream-abc"
        chunk1.usage = None
        chunk1.choices = [MagicMock(delta=MagicMock(content="Hi", tool_calls=None))]

        chunk2 = MagicMock()
        chunk2.id = "gen-stream-LATER"  # must NOT overwrite the first-seen id
        chunk2.usage = SimpleNamespace(
            prompt_tokens=10, completion_tokens=2, total_tokens=12, prompt_tokens_details=None
        )
        chunk2.choices = []

        async def mock_stream():
            yield chunk1
            yield chunk2

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())
        mock_creds = {"api_key": "sk-or-test", "base_url": "https://openrouter.ai/api/v1", "extra_headers": {}}
        with patch.object(client, "_credentials") as mock_cm:
            mock_cm.get_credentials = AsyncMock(return_value=mock_creds)
            client._client = mock_client
            events = [e async for e in client.stream(messages=[Message(role="user", content="Hello")])]

        metas = [e.provider_meta for e in events if e.provider_meta is not None]
        assert metas  # carried on usage + response_end
        for meta in metas:
            assert meta.provider == "openrouter"
            assert meta.provider_generation_id == "gen-stream-abc"  # first-seen, not overwritten
            assert meta.provider_response_id == "gen-stream-abc"

    @pytest.mark.asyncio
    async def test_stream_non_string_id_leaves_provider_meta_none(self, client):
        """A chunk with no usable string id yields no provider_meta (guards against mock ids)."""
        chunk = MagicMock(spec=["usage", "choices"])  # no .id attribute at all
        chunk.usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2, prompt_tokens_details=None)
        chunk.choices = []

        async def mock_stream():
            yield chunk

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())
        mock_creds = {"api_key": "sk-or-test", "base_url": "https://openrouter.ai/api/v1", "extra_headers": {}}
        with patch.object(client, "_credentials") as mock_cm:
            mock_cm.get_credentials = AsyncMock(return_value=mock_creds)
            client._client = mock_client
            events = [e async for e in client.stream(messages=[Message(role="user", content="Hello")])]

        response_end = [e for e in events if e.type == "response_end"]
        assert response_end and response_end[0].provider_meta is None
