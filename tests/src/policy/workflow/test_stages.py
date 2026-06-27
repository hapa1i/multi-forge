"""Tests for forge.policy.workflow.stages."""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

from forge.core.llm import CompletionResponse
from forge.policy.types import ActionContext
from forge.policy.workflow.config import CheckerConfig, FilterConfig, ReviewerConfig
from forge.policy.workflow.stages import (
    CheckerStage,
    FilterStage,
    ReviewerStage,
    _map_verdict,
    _normalize_severity,
)


def _ctx(target_path: str | None = "src/foo.py", new_content: str | None = "x = 1") -> ActionContext:
    return ActionContext(
        origin="claude_code",
        event="PreToolUse.Write",
        tool_name="Write",
        tool_args={},
        repo_root="/repo",
        session_name="test",
        target_path=target_path,
        new_content=new_content,
    )


# --- FilterStage ---


class TestFilterStage:
    def test_empty_config_passes_everything(self):
        stage = FilterStage(FilterConfig())
        assert stage.passes(_ctx()) is True

    def test_path_pattern_matches(self):
        stage = FilterStage(FilterConfig(path_patterns=[r"src/.*\.py$"]))
        assert stage.passes(_ctx(target_path="src/foo.py")) is True

    def test_path_pattern_no_match(self):
        stage = FilterStage(FilterConfig(path_patterns=[r"src/.*\.py$"]))
        assert stage.passes(_ctx(target_path="docs/readme.md")) is False

    def test_exclude_pattern_skips(self):
        stage = FilterStage(FilterConfig(exclude_patterns=[r"^tests/"]))
        assert stage.passes(_ctx(target_path="tests/test_foo.py")) is False

    def test_exclude_takes_precedence(self):
        stage = FilterStage(FilterConfig(path_patterns=[r".*\.py$"], exclude_patterns=[r"^tests/"]))
        assert stage.passes(_ctx(target_path="tests/test_foo.py")) is False

    def test_max_content_length(self):
        stage = FilterStage(FilterConfig(max_content_length=10))
        assert stage.passes(_ctx(new_content="short")) is True
        assert stage.passes(_ctx(new_content="x" * 100)) is False

    def test_none_target_path_handled(self):
        stage = FilterStage(FilterConfig(path_patterns=[r"src/"]))
        assert stage.passes(_ctx(target_path=None)) is False

    def test_invalid_regex_raises_at_init(self):
        with pytest.raises(re.error):
            FilterStage(FilterConfig(path_patterns=["[invalid"]))


# --- CheckerStage ---


class TestCheckerStage:
    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_aligned_returns_allow(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text='```json\n{"aligned": true, "reason": "ok"}\n```')
        mock_adapter_cls.return_value = mock_adapter

        stage = CheckerStage(CheckerConfig(prompt_template="Check: {tool_name} {tags}"))
        result = stage.check(_ctx(), tags=["routine"], policy_id="wf.test")

        assert result is not None
        assert result.decision == "allow"
        assert result.policy_id == "wf.test"

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_not_aligned_returns_none(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text='{"aligned": false, "reason": "unusual pattern"}')
        mock_adapter_cls.return_value = mock_adapter

        stage = CheckerStage(CheckerConfig(prompt_template="{tool_name}"))
        result = stage.check(_ctx(), tags=["architectural"], policy_id="wf.test")

        assert result is None

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_unparseable_returns_none(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text="I don't know, looks fine")
        mock_adapter_cls.return_value = mock_adapter

        stage = CheckerStage(CheckerConfig(prompt_template="{tool_name}"))
        assert stage.check(_ctx(), tags=[], policy_id="wf.test") is None

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_llm_error_returns_none(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.side_effect = RuntimeError("LLM down")
        mock_adapter_cls.return_value = mock_adapter

        stage = CheckerStage(CheckerConfig(prompt_template="{tool_name}"))
        assert stage.check(_ctx(), tags=[], policy_id="wf.test") is None

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_emits_session_tagged_usage_event(self, mock_adapter_cls, mock_get_client, monkeypatch):
        """T5/WS2: a checker run emits a session-tagged policy-checker event with exact tokens."""
        monkeypatch.setenv("FORGE_RUN_ID", "run_chk")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_chk")
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(
            text='{"aligned": true}', usage={"prompt_tokens": 7, "completion_tokens": 3}
        )
        mock_adapter_cls.return_value = mock_adapter

        stage = CheckerStage(CheckerConfig(model="gemini/gemini-2.0-flash", prompt_template="{tool_name}"))
        stage.check(_ctx(), tags=[], policy_id="wf.test")

        from forge.core.usage.ledger import read_usage_events

        events = read_usage_events()
        assert len(events) == 1
        e = events[0]
        assert (e.command, e.session, e.provider, e.status) == ("policy-checker", "test", "gemini", "success")
        assert (e.input_tokens, e.output_tokens) == (7, 3)
        assert e.measurement_source == "provider_usage_exact"

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_parse_failure_emits_error_event(self, mock_adapter_cls, mock_get_client, monkeypatch):
        """T5/WS2: an unparseable checker response still emits, status=error (the call happened)."""
        monkeypatch.setenv("FORGE_RUN_ID", "run_chk")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_chk")
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text="not json")
        mock_adapter_cls.return_value = mock_adapter

        stage = CheckerStage(CheckerConfig(prompt_template="{tool_name}"))
        assert stage.check(_ctx(), tags=[], policy_id="wf.test") is None

        from forge.core.usage.ledger import read_usage_events

        events = read_usage_events()
        assert len(events) == 1
        assert (events[0].command, events[0].status) == ("policy-checker", "error")

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_exception_emits_error_event(self, mock_adapter_cls, mock_get_client, monkeypatch):
        """T5/WS2: a checker LLM exception emits a status=error event and still fails open to None."""
        monkeypatch.setenv("FORGE_RUN_ID", "run_chk")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_chk")
        mock_adapter = MagicMock()
        mock_adapter.complete.side_effect = RuntimeError("LLM down")
        mock_adapter_cls.return_value = mock_adapter

        stage = CheckerStage(CheckerConfig(prompt_template="{tool_name}"))
        assert stage.check(_ctx(), tags=[], policy_id="wf.test") is None

        from forge.core.usage.ledger import read_usage_events

        events = read_usage_events()
        assert len(events) == 1
        assert (events[0].command, events[0].status) == ("policy-checker", "error")


# --- ReviewerStage ---


class TestReviewerStage:
    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_aligned_returns_allow(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text='{"verdict": "aligned", "confidence": 0.95}')
        mock_adapter_cls.return_value = mock_adapter

        stage = ReviewerStage(ReviewerConfig(prompt_template="{tool_name}"))
        result = stage.review(_ctx(), tags=[], policy_id="workflow.test")

        assert result.decision == "allow"
        assert result.policy_id == "workflow.test"

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_divergent_high_confidence_denies(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(
            text=(
                '{"verdict": "divergent", "confidence": 0.95, '
                '"violations": [{"severity": "high", "evidence": "bad", "citations": ["plan says X"]}]}'
            )
        )
        mock_adapter_cls.return_value = mock_adapter

        stage = ReviewerStage(ReviewerConfig(prompt_template="{tool_name}"))
        result = stage.review(_ctx(), tags=[], policy_id="workflow.test")

        assert result.decision == "deny"
        assert len(result.violations) == 1
        assert result.violations[0].severity == "high"

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_divergent_low_confidence_warns(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(
            text='{"verdict": "divergent", "confidence": 0.4, "violations": [{"evidence": "might be off"}]}'
        )
        mock_adapter_cls.return_value = mock_adapter

        stage = ReviewerStage(ReviewerConfig(prompt_template="{tool_name}"))
        result = stage.review(_ctx(), tags=[], policy_id="workflow.test")

        assert result.decision == "warn"
        assert len(result.warnings) > 0
        assert "might be off" in result.warnings[0]

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_parse_failure_warns(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text="not json at all")
        mock_adapter_cls.return_value = mock_adapter

        stage = ReviewerStage(ReviewerConfig(prompt_template="{tool_name}"))
        result = stage.review(_ctx(), tags=[], policy_id="workflow.test")

        assert result.decision == "warn"
        assert "parse" in result.warnings[0].lower()

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_llm_error_warns(self, mock_adapter_cls, mock_get_client):
        mock_adapter = MagicMock()
        mock_adapter.complete.side_effect = RuntimeError("timeout")
        mock_adapter_cls.return_value = mock_adapter

        stage = ReviewerStage(ReviewerConfig(prompt_template="{tool_name}"))
        result = stage.review(_ctx(), tags=[], policy_id="workflow.test")

        assert result.decision == "warn"
        assert "failing open" in result.warnings[0].lower()

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_emits_session_tagged_usage_event(self, mock_adapter_cls, mock_get_client, monkeypatch):
        """T5/WS2: a reviewer run emits a session-tagged policy-reviewer event with exact tokens."""
        monkeypatch.setenv("FORGE_RUN_ID", "run_rev")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_rev")
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(
            text='{"verdict": "aligned", "confidence": 0.9}', usage={"prompt_tokens": 11, "completion_tokens": 5}
        )
        mock_adapter_cls.return_value = mock_adapter

        stage = ReviewerStage(ReviewerConfig(model="gemini/gemini-2.0-flash", prompt_template="{tool_name}"))
        stage.review(_ctx(), tags=[], policy_id="workflow.test")

        from forge.core.usage.ledger import read_usage_events

        events = read_usage_events()
        assert len(events) == 1
        e = events[0]
        assert (e.command, e.session, e.provider, e.status) == ("policy-reviewer", "test", "gemini", "success")
        assert (e.input_tokens, e.output_tokens) == (11, 5)

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_exception_emits_error_event_and_warns(self, mock_adapter_cls, mock_get_client, monkeypatch):
        """T5/WS2: a reviewer LLM exception emits status=error and still fails open to warn."""
        monkeypatch.setenv("FORGE_RUN_ID", "run_rev")
        monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_rev")
        mock_adapter = MagicMock()
        mock_adapter.complete.side_effect = RuntimeError("timeout")
        mock_adapter_cls.return_value = mock_adapter

        stage = ReviewerStage(ReviewerConfig(prompt_template="{tool_name}"))
        result = stage.review(_ctx(), tags=[], policy_id="workflow.test")
        assert result.decision == "warn"

        from forge.core.usage.ledger import read_usage_events

        events = read_usage_events()
        assert len(events) == 1
        assert (events[0].command, events[0].status) == ("policy-reviewer", "error")


# --- _map_verdict ---


class TestMapVerdict:
    def test_aligned(self):
        result = _map_verdict({"verdict": "aligned", "confidence": 0.9}, "wf.test")
        assert result.decision == "allow"

    def test_divergent_no_citations_warns(self):
        result = _map_verdict(
            {
                "verdict": "divergent",
                "confidence": 0.95,
                "violations": [{"evidence": "bad"}],
            },
            "wf.test",
        )
        assert result.decision == "warn"

    def test_divergent_with_citations_denies(self):
        result = _map_verdict(
            {
                "verdict": "divergent",
                "confidence": 0.95,
                "violations": [{"evidence": "bad", "citations": ["plan: do X"]}],
            },
            "wf.test",
        )
        assert result.decision == "deny"
        assert result.violations[0].rule_id == "wf.test.reviewer"

    def test_below_threshold_warns(self):
        result = _map_verdict(
            {
                "verdict": "divergent",
                "confidence": 0.5,
                "violations": [{"evidence": "maybe", "citations": ["plan"]}],
            },
            "wf.test",
        )
        assert result.decision == "warn"

    def test_confidence_exactly_at_threshold_with_citations(self):
        """Confidence == 0.8 with citations triggers deny (>= boundary)."""
        result = _map_verdict(
            {
                "verdict": "divergent",
                "confidence": 0.8,
                "violations": [{"evidence": "bad", "citations": ["plan"]}],
            },
            "wf.test",
        )
        assert result.decision == "deny"

    def test_violations_with_empty_citations_warns(self):
        """Violations with empty citations list → no has_citations → warn."""
        result = _map_verdict(
            {
                "verdict": "divergent",
                "confidence": 0.95,
                "violations": [{"evidence": "bad", "citations": []}],
            },
            "wf.test",
        )
        assert result.decision == "warn"

    def test_mixed_severity_values(self):
        """Invalid severity strings normalize to 'medium'."""
        result = _map_verdict(
            {
                "verdict": "divergent",
                "confidence": 0.9,
                "violations": [
                    {"severity": "CRITICAL", "evidence": "a", "citations": ["x"]},
                    {"severity": "invalid", "evidence": "b", "citations": ["y"]},
                ],
            },
            "wf.test",
        )
        assert result.decision == "deny"
        assert result.violations[0].severity == "critical"
        assert result.violations[1].severity == "medium"

    def test_missing_verdict_defaults_to_aligned(self):
        """Missing 'verdict' key defaults to 'aligned' → allow."""
        result = _map_verdict({"confidence": 0.9}, "wf.test")
        assert result.decision == "allow"

    def test_non_dict_violations_filtered(self):
        """Non-dict entries in violations list are filtered out."""
        result = _map_verdict(
            {
                "verdict": "divergent",
                "confidence": 0.95,
                "violations": ["not a dict", 42, {"evidence": "real", "citations": ["x"]}],
            },
            "wf.test",
        )
        assert result.decision == "deny"
        assert len(result.violations) == 1

    def test_unknown_verdict_treated_as_divergent(self):
        """Unknown verdict string (not 'aligned') treated as divergent."""
        result = _map_verdict(
            {
                "verdict": "maybe",
                "confidence": 0.9,
                "violations": [{"evidence": "unsure", "citations": ["ref"]}],
            },
            "wf.test",
        )
        assert result.decision == "deny"


# --- _normalize_severity ---


class TestNormalizeSeverity:
    def test_valid_lowercase(self):
        assert _normalize_severity("high") == "high"

    def test_case_insensitive(self):
        assert _normalize_severity("CRITICAL") == "critical"

    def test_whitespace_stripped(self):
        assert _normalize_severity("  high  ") == "high"

    def test_invalid_defaults_to_medium(self):
        assert _normalize_severity("unknown") == "medium"

    def test_empty_string_defaults_to_medium(self):
        assert _normalize_severity("") == "medium"

    def test_numeric_string_defaults_to_medium(self):
        assert _normalize_severity("5") == "medium"


# --- FilterStage edge cases ---


class TestFilterStageEdgeCases:
    def test_max_content_length_at_boundary(self):
        """Content exactly at max_content_length passes (uses > not >=)."""
        stage = FilterStage(FilterConfig(max_content_length=5))
        assert stage.passes(_ctx(new_content="12345")) is True
        assert stage.passes(_ctx(new_content="123456")) is False

    def test_none_content_with_max_length(self):
        """None content has length 0, should pass any max_content_length."""
        stage = FilterStage(FilterConfig(max_content_length=0))
        assert stage.passes(_ctx(new_content=None)) is True


# --- CheckerStage edge cases ---


class TestCheckerStageEdgeCases:
    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_aligned_numeric_not_boolean(self, mock_adapter_cls, mock_get_client):
        """aligned=1 (numeric) is not True (boolean identity check)."""
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text='{"aligned": 1}')
        mock_adapter_cls.return_value = mock_adapter

        stage = CheckerStage(CheckerConfig(prompt_template="{tool_name}"))
        assert stage.check(_ctx(), tags=[], policy_id="wf.test") is None

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_aligned_null_returns_none(self, mock_adapter_cls, mock_get_client):
        """aligned=null (JSON null) is not True."""
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text='{"aligned": null}')
        mock_adapter_cls.return_value = mock_adapter

        stage = CheckerStage(CheckerConfig(prompt_template="{tool_name}"))
        assert stage.check(_ctx(), tags=[], policy_id="wf.test") is None

    @patch("forge.core.llm.get_client")
    @patch("forge.core.llm.SyncAdapter")
    def test_content_truncated_at_2000(self, mock_adapter_cls, mock_get_client):
        """Content passed to checker is truncated at 2000 chars (read from the user message)."""
        mock_adapter = MagicMock()
        mock_adapter.complete.return_value = CompletionResponse(text='{"aligned": true}')
        mock_adapter_cls.return_value = mock_adapter

        stage = CheckerStage(CheckerConfig(prompt_template="{content}"))
        long_content = "x" * 5000
        stage.check(_ctx(new_content=long_content), tags=[], policy_id="wf.test")

        messages = mock_adapter.complete.call_args[0][0]
        user_prompt = messages[-1].content  # no system_prompt configured -> single user message
        assert len(user_prompt) == 2000
