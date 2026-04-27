"""Tests for forge.core.reactive.tagger."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from forge.core.reactive.tagger import _parse_tags, tag_action
from forge.guard.types import ActionContext


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


class TestTagAction:
    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_success(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.ask.return_value = "routine | trivial"
        mock_adapter_cls.return_value = mock_adapter

        ctx = _make_context()
        result = tag_action(
            ctx,
            model="gemini/gemini-2.0-flash",
            prompt_template="Classify: {tool_name} on {target_path}",
        )

        assert result == ["routine", "trivial"]
        mock_adapter.ask.assert_called_once()
        prompt = mock_adapter.ask.call_args[0][0]
        assert "Write" in prompt
        assert "src/foo.py" in prompt

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_llm_error_returns_empty_list(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.ask.side_effect = RuntimeError("LLM down")
        mock_adapter_cls.return_value = mock_adapter

        ctx = _make_context()
        result = tag_action(ctx, model="gemini/gemini-2.0-flash", prompt_template="{tool_name}")
        assert result == []

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_truncates_content(self, mock_adapter_cls, mock_get_client):
        """new_content is truncated to 2000 chars in the prompt."""
        mock_adapter = MagicMock()
        mock_adapter.ask.return_value = "routine"
        mock_adapter_cls.return_value = mock_adapter

        ctx = _make_context(new_content="x" * 5000)
        tag_action(ctx, model="test", prompt_template="{content}")

        prompt = mock_adapter.ask.call_args[0][0]
        assert len(prompt) == 2000

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_none_target_path_handled(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.ask.return_value = "routine"
        mock_adapter_cls.return_value = mock_adapter

        ctx = _make_context(target_path=None)
        tag_action(ctx, model="test", prompt_template="{target_path}")

        prompt = mock_adapter.ask.call_args[0][0]
        assert "N/A" in prompt
