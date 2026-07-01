"""Unit tests for ``parse_codex_jsonl_stream`` (Phase 5b, B1).

Driven by the recorded ``tests/fixtures/codex/`` streams (codex-cli 0.137.0). The
fixture is authoritative: ``final_text`` must equal the ``-o`` oracle, and the token
counts must equal the values the binary actually reported.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.core.invoker.codex_stream import (
    is_subscription_exhausted,
    parse_codex_jsonl_stream,
)

_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "codex"


def _read(name: str) -> str:
    return (_FIXTURES / name).read_text()


class TestRecordedSuccessStream:
    """The recorded success run: prompt "reply with the single word OK"."""

    def test_final_text_equals_output_last_message_oracle(self) -> None:
        result = parse_codex_jsonl_stream(_read("exec_json_success.jsonl"))
        # The `-o` oracle's content is exactly "OK"; rstrip the file-convention trailing
        # newline a text normalizer may add (not part of the model's last message).
        oracle = _read("exec_last_message_success.txt").rstrip("\n")
        assert result.final_text == oracle == "OK"

    def test_tokens_match_recorded_usage(self) -> None:
        # turn.completed.usage in the fixture: input 14936, cached_input 10624, output 22.
        result = parse_codex_jsonl_stream(_read("exec_json_success.jsonl"))
        assert result.input_tokens == 14936
        assert result.output_tokens == 22
        assert result.cached_tokens == 10624

    def test_success_is_not_an_error(self) -> None:
        result = parse_codex_jsonl_stream(_read("exec_json_success.jsonl"))
        assert result.is_error is False
        assert result.error_message is None

    def test_thread_id_extracted_from_thread_started(self) -> None:
        result = parse_codex_jsonl_stream(_read("exec_json_success.jsonl"))
        assert result.thread_id == "019eaa51-6920-7c41-ae34-d4f7f368d55a"


class TestRecordedErrorStream:
    """The recorded failed run: bogus model -> error + turn.failed, exit 1, no usage."""

    def test_error_and_turn_failed_set_is_error(self) -> None:
        result = parse_codex_jsonl_stream(_read("exec_json_error.jsonl"))
        assert result.is_error is True

    def test_error_message_surfaced_for_diagnostics(self) -> None:
        result = parse_codex_jsonl_stream(_read("exec_json_error.jsonl"))
        assert result.error_message is not None
        assert "not supported" in result.error_message

    def test_failed_turn_has_no_text_or_tokens(self) -> None:
        result = parse_codex_jsonl_stream(_read("exec_json_error.jsonl"))
        assert result.final_text == ""
        assert result.input_tokens is None
        assert result.output_tokens is None
        assert result.cached_tokens is None

    def test_failed_turn_still_carries_thread_id(self) -> None:
        # The recorded bogus-model failure still opened a thread before failing.
        result = parse_codex_jsonl_stream(_read("exec_json_error.jsonl"))
        assert result.thread_id == "019eaa51-f236-7bc2-be86-6903c9339b46"


class TestReducerRobustness:
    """Hermetic edge cases (system boundary: external subprocess output)."""

    def test_multiple_agent_messages_concatenate_in_order(self) -> None:
        stream = (
            '{"type":"item.completed","item":{"id":"a","type":"agent_message","text":"first"}}\n'
            '{"type":"item.completed","item":{"id":"b","type":"agent_message","text":"second"}}\n'
        )
        assert parse_codex_jsonl_stream(stream).final_text == "first\nsecond"

    def test_non_agent_message_items_are_ignored(self) -> None:
        stream = (
            '{"type":"item.completed","item":{"id":"r","type":"reasoning","text":"thinking"}}\n'
            '{"type":"item.completed","item":{"id":"a","type":"agent_message","text":"answer"}}\n'
        )
        assert parse_codex_jsonl_stream(stream).final_text == "answer"

    def test_malformed_json_line_is_skipped_not_fatal(self) -> None:
        stream = (
            "not json at all\n" '{"type":"item.completed","item":{"id":"a","type":"agent_message","text":"survived"}}\n'
        )
        result = parse_codex_jsonl_stream(stream)
        assert result.final_text == "survived"
        assert result.is_error is False

    def test_non_dict_json_line_is_skipped(self) -> None:
        stream = "[1, 2, 3]\n" '{"type":"item.completed","item":{"id":"a","type":"agent_message","text":"ok"}}\n'
        assert parse_codex_jsonl_stream(stream).final_text == "ok"

    def test_empty_stream_is_empty_not_error(self) -> None:
        result = parse_codex_jsonl_stream("")
        assert result.final_text == ""
        assert result.is_error is False
        assert result.input_tokens is None

    def test_bool_usage_value_rejected(self) -> None:
        # bool is an int subclass; a token count is never a bool.
        stream = '{"type":"turn.completed","usage":{"input_tokens":true,"output_tokens":5}}\n'
        result = parse_codex_jsonl_stream(stream)
        assert result.input_tokens is None
        assert result.output_tokens == 5

    def test_turn_failed_only_still_flags_error(self) -> None:
        stream = '{"type":"turn.failed","error":{"message":"boom"}}\n'
        result = parse_codex_jsonl_stream(stream)
        assert result.is_error is True
        assert result.error_message == "boom"

    def test_last_turn_completed_usage_wins(self) -> None:
        # Documents the chosen behavior: one-shot `codex exec` emits one terminal
        # turn.completed; if several appear, the parser keeps the LAST.
        stream = (
            '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":2,"cached_input_tokens":0}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":20,"cached_input_tokens":3}}\n'
        )
        result = parse_codex_jsonl_stream(stream)
        assert (result.input_tokens, result.output_tokens, result.cached_tokens) == (10, 20, 3)

    def test_reasoning_output_tokens_not_added_to_output(self) -> None:
        # reasoning is a SUBSET of output (Responses usage is inclusive); never summed.
        stream = '{"type":"turn.completed","usage":{"output_tokens":5,"reasoning_output_tokens":4}}\n'
        assert parse_codex_jsonl_stream(stream).output_tokens == 5

    def test_thread_id_none_when_no_thread_started(self) -> None:
        stream = '{"type":"item.completed","item":{"id":"a","type":"agent_message","text":"ok"}}\n'
        assert parse_codex_jsonl_stream(stream).thread_id is None

    def test_first_thread_id_wins(self) -> None:
        # One stream opens one thread; a resumed stream re-announces the SAME id
        # (probe 60b). If a hypothetical stream carried two, the first is the binding one.
        stream = (
            '{"type":"thread.started","thread_id":"first-id"}\n' '{"type":"thread.started","thread_id":"second-id"}\n'
        )
        assert parse_codex_jsonl_stream(stream).thread_id == "first-id"

    def test_non_string_or_empty_thread_id_ignored(self) -> None:
        stream = '{"type":"thread.started","thread_id":""}\n{"type":"thread.started","thread_id":42}\n'
        assert parse_codex_jsonl_stream(stream).thread_id is None


# Exact Display strings from openai/codex protocol/src/error.rs (main @ db887d0), one per
# exhaustion family, plus the two raw-leak JSON envelopes the untyped path can produce.
_EXHAUSTED_MESSAGES = [
    # UsageLimitReached, Plus plan (the recorded quota fixture's message)
    "You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
    "visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again later.",
    # UsageLimitReached, generic/unknown plan
    "You've hit your usage limit. Try again later.",
    # UsageLimitReached, named-limit branch ("...for X. Switch to another model now,")
    "You've hit your usage limit for GPT-5. Switch to another model now, or try again later.",
    # Workspace credits depleted
    "Your workspace is out of credits. Add credits to continue.",
    # Workspace spend cap
    "You hit your spend cap set in your workspace. Increase your spend cap to continue.",
    # QuotaExceeded (fixed literal)
    "Quota exceeded. Check your plan and billing details.",
    # UsageNotIncluded (fixed literal)
    "To use Codex with your ChatGPT plan, upgrade to Plus: https://chatgpt.com/explore/plus.",
    # Raw-leak JSON envelope (untyped path) carrying a usage-limit / quota error.type
    '{"type":"error","status":429,"error":{"type":"usage_limit_reached","message":"limit"}}',
    '{"type":"error","status":429,"error":{"type":"insufficient_quota","message":"quota"}}',
]

_NOT_EXHAUSTED_MESSAGES = [
    # The recorded 400 model error (generic) -- JSON envelope, non-exhaustion error.type
    '{"type":"error","status":400,"error":{"type":"invalid_request_error",'
    '"message":"The \'x\' model is not supported when using Codex with a ChatGPT account."}}',
    # Transient per-minute RPM throttle -- deliberately NOT exhaustion (recoverable)
    '{"type":"error","status":429,"error":{"type":"rate_limit_exceeded","message":"slow down"}}',
    "Rate limit reached for gpt-5-codex. Limit: 20/min. Try again in 3s.",
    # ServerOverloaded (transient)
    "Selected model is at capacity. Please try a different model.",
    # InternalServerError (transient)
    "We're currently experiencing high demand, which may cause temporary errors.",
    # Connection / generic runtime failure / fallback line
    "Connection failed: error sending request",
    "Codex runtime reported a failed turn",
    "boom",
    "",
    "   ",
]


class TestSubscriptionExhaustionClassifier:
    """T7 ``is_subscription_exhausted`` truth table (codex JSONL ``message`` signal)."""

    @pytest.mark.parametrize("message", _EXHAUSTED_MESSAGES)
    def test_exhaustion_messages_classified_true(self, message: str) -> None:
        assert is_subscription_exhausted(message) is True

    @pytest.mark.parametrize("message", _NOT_EXHAUSTED_MESSAGES)
    def test_non_exhaustion_messages_classified_false(self, message: str) -> None:
        assert is_subscription_exhausted(message) is False

    def test_match_is_case_insensitive(self) -> None:
        assert is_subscription_exhausted("YOU'VE HIT YOUR USAGE LIMIT. TRY AGAIN LATER.") is True

    def test_recorded_quota_fixture_classified_true(self) -> None:
        # End-to-end: the source-derived wire fixture -> is_error and the classifier agree.
        result = parse_codex_jsonl_stream(_read("exec_json_quota_exhausted.jsonl"))
        assert result.is_error is True
        assert result.error_message is not None
        assert is_subscription_exhausted(result.error_message) is True

    def test_recorded_400_fixture_classified_false(self) -> None:
        # The generic model-not-supported 400 must never read as exhaustion.
        result = parse_codex_jsonl_stream(_read("exec_json_error.jsonl"))
        assert result.error_message is not None
        assert is_subscription_exhausted(result.error_message) is False

    def test_both_extraction_shapes_feed_classifier(self) -> None:
        # G4: the quota message classifies True whether it arrived as a top-level
        # ``error`` event or a nested ``turn.failed`` event -- the two
        # ``_extract_error_message`` branches that ``parse_codex_jsonl_stream`` reduces.
        msg = "Quota exceeded. Check your plan and billing details."
        top_level = parse_codex_jsonl_stream(f'{{"type":"error","message":"{msg}"}}\n')
        nested = parse_codex_jsonl_stream(f'{{"type":"turn.failed","error":{{"message":"{msg}"}}}}\n')
        assert top_level.error_message is not None and nested.error_message is not None
        assert is_subscription_exhausted(top_level.error_message) is True
        assert is_subscription_exhausted(nested.error_message) is True
