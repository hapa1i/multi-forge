"""Unit tests for ``parse_codex_jsonl_stream`` (Phase 5b, B1).

Driven by the recorded ``tests/fixtures/codex/`` streams (codex-cli 0.137.0). The
fixture is authoritative: ``final_text`` must equal the ``-o`` oracle, and the token
counts must equal the values the binary actually reported.
"""

from __future__ import annotations

from pathlib import Path

from forge.core.invoker.codex_stream import parse_codex_jsonl_stream

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
