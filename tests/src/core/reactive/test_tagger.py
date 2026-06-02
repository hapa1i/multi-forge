"""Tests for forge.core.reactive.tagger."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from forge.core.llm import CompletionResponse
from forge.core.reactive.tagger import _parse_tags, tag_action
from forge.policy.types import ActionContext


def _make_context(**kwargs: object) -> ActionContext:
    defaults: dict[str, object] = {
        "event": "PreToolUse.Write",
        "tool_name": "Write",
        "tool_args": {},
        "repo_root": "/repo",
        "session_name": "test",
        "target_path": "src/foo.py",
        "new_content": "some content",
    }
    defaults.update(kwargs)

    return ActionContext(
        event=str(defaults["event"]),
        tool_name=str(defaults["tool_name"]),
        tool_args=defaults["tool_args"],  # type: ignore[arg-type]
        repo_root=str(defaults["repo_root"]),
        session_name=str(defaults["session_name"]),
        target_path=defaults["target_path"],  # type: ignore[arg-type]
        new_content=defaults["new_content"],  # type: ignore[arg-type]
    )


class TestParseTags:
    def test_json_array(self):
        assert _parse_tags('["architectural", "config"]') == ["architectural", "config"]

    def test_pipe_separated(self):
        assert _parse_tags("routine | trivial") == ["routine", "trivial"]

    def test_comma_separated(self):
        assert _parse_tags("routine, config") == ["routine", "config"]

    def test_single_tag(self):
        assert _parse_tags("routine") == ["routine"]

    def test_empty_string(self):
        assert _parse_tags("") == []

    def test_whitespace_stripped(self):
        assert _parse_tags("  routine | trivial  ") == ["routine", "trivial"]

    def test_empty_entries_filtered(self):
        assert _parse_tags("routine||") == ["routine"]

    def test_json_with_whitespace(self):
        assert _parse_tags(' ["a", "b"] ') == ["a", "b"]

    def test_mixed_pipe_and_comma_uses_pipe(self):
        """Pipe takes precedence over comma when both present."""
        assert _parse_tags("routine | config, trivial") == ["routine", "config, trivial"]

    def test_comma_separated_empty_entries(self):
        """Empty entries between commas are filtered."""
        assert _parse_tags(", ,routine, ,") == ["routine"]

    def test_json_array_with_non_string_elements(self):
        """Non-string elements in JSON array are coerced via str()."""
        assert _parse_tags('[42, true, "tag"]') == ["42", "True", "tag"]

    def test_json_array_with_null_entries(self):
        """JSON null entries are filtered out."""
        assert _parse_tags('[null, "real"]') == ["real"]


def _prompt_of(mock_complete) -> str:
    """Extract the user prompt from a mocked adapter.complete(...) call."""
    messages = mock_complete.call_args[0][0]
    return messages[0].content


class TestTagAction:
    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_success(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(
            text="routine | trivial", usage={"prompt_tokens": 5, "completion_tokens": 2}
        )
        mock_adapter_cls.return_value = mock_adapter

        ctx = _make_context()
        result = tag_action(
            ctx,
            model="gemini/gemini-2.0-flash",
            prompt_template="Classify: {tool_name} on {target_path}",
        )

        assert result == ["routine", "trivial"]
        mock_adapter.complete.assert_called_once()
        prompt = _prompt_of(mock_adapter.complete)
        assert "Write" in prompt
        assert "src/foo.py" in prompt
        # Default path: target is not a Forge proxy -> no header forwarded (prior
        # behavior preserved; cost_request_id stays null in the emitted event).
        assert mock_adapter.complete.call_args.kwargs["hyperparams"] is None

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_llm_error_returns_empty_list(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.side_effect = RuntimeError("LLM down")
        mock_adapter_cls.return_value = mock_adapter

        ctx = _make_context()
        result = tag_action(ctx, model="gemini/gemini-2.0-flash", prompt_template="{tool_name}")
        assert result == []

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_truncates_content(self, mock_adapter_cls, mock_get_client):
        """new_content is truncated to 2000 chars in the prompt."""
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text="routine")
        mock_adapter_cls.return_value = mock_adapter

        ctx = _make_context(new_content="x" * 5000)
        tag_action(ctx, model="test", prompt_template="{content}")

        assert len(_prompt_of(mock_adapter.complete)) == 2000

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_none_target_path_handled(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text="routine")
        mock_adapter_cls.return_value = mock_adapter

        ctx = _make_context(target_path=None)
        tag_action(ctx, model="test", prompt_template="{target_path}")

        assert "N/A" in _prompt_of(mock_adapter.complete)

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_emits_usage_event(self, mock_adapter_cls, mock_get_client, monkeypatch):
        """A successful tag call emits a provider_usage_exact event to the ledger."""
        monkeypatch.setenv("FORGE_RUN_ID", "run_tag")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_tag")
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(
            text="routine", usage={"prompt_tokens": 9, "completion_tokens": 4}
        )
        mock_adapter_cls.return_value = mock_adapter

        tag_action(_make_context(), model="gemini/gemini-2.0-flash", prompt_template="{tool_name}")

        from forge.core.usage.ledger import read_usage_events

        events = read_usage_events()
        assert len(events) == 1
        e = events[0]
        assert (e.command, e.run_id, e.provider) == ("tagger", "run_tag", "gemini")
        assert e.measurement_source == "provider_usage_exact"
        assert (e.input_tokens, e.output_tokens) == (9, 4)
        assert e.source_refs is None  # no proven Forge-proxy target

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_proxy_target_forwards_header_and_joins(self, mock_adapter_cls, mock_get_client, monkeypatch):
        """When the resolved target IS a Forge proxy: forward X-Request-ID AND record
        the exact source_refs.cost_request_id join (the forwarded id == the recorded id)."""
        monkeypatch.setenv("FORGE_RUN_ID", "run_t")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_t")
        monkeypatch.setattr("forge.core.usage.resolve_client_base_url", lambda _m: "http://localhost:8084")
        monkeypatch.setattr("forge.core.usage.target_is_forge_proxy", lambda _u: True)
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(
            text="routine", usage={"prompt_tokens": 1, "completion_tokens": 1}
        )
        mock_adapter_cls.return_value = mock_adapter

        tag_action(_make_context(), model="gemini/gemini-2.0-flash", prompt_template="{tool_name}")

        forwarded = mock_adapter.complete.call_args.kwargs["hyperparams"].extra["openai"]["extra_headers"]["X-Request-ID"]
        assert forwarded.startswith("req_")

        from forge.core.usage.ledger import read_usage_events

        e = read_usage_events()[0]
        assert e.source_refs is not None
        assert e.source_refs.cost_request_id == forwarded
