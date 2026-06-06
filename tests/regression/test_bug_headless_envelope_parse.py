"""Regression: headless `claude -p --output-format json` envelope parsing.

Bug class this guards: the documented envelope is a single ``{"type":"result",...}``
object, but Claude Code 2.1.x emits a JSON ARRAY ``[system, assistant, result]``
with cost/usage in the LAST ``result`` element (spike: Phase 5a). Wiring to the
documented single-object shape would have dropped ALL cost/usage and, worse, a
naive ``.get("result")`` on the array would have raised. ``parse_headless_envelope``
must accept the array, the bare object, and ``stream-json``, and NEVER raise --
falling back to raw text so every existing text consumer is byte-for-byte unchanged.

Root cause: undocumented multi-shape envelope. Fix: ``_find_result_object`` +
``parse_headless_envelope`` in ``src/forge/core/reactive/structured_output.py``.
"""

from __future__ import annotations

import json

import pytest

from forge.core.reactive.structured_output import parse_headless_envelope

pytestmark = pytest.mark.regression


def _result_obj(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "type": "result",
        "subtype": "success",
        "result": "MODEL TEXT",
        "total_cost_usd": 0.0269,
        "is_error": False,
        "usage": {
            "input_tokens": 120,
            "output_tokens": 34,
            "cache_read_input_tokens": 80,
            "cache_creation_input_tokens": 12,
        },
    }
    base.update(overrides)
    return base


def _array_envelope(**overrides: object) -> str:
    # The real 2.1.x shape: system + assistant + terminal result.
    return json.dumps(
        [
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": "..."}},
            _result_obj(**overrides),
        ]
    )


def test_array_envelope_takes_last_result_and_lifts_metrics() -> None:
    env = parse_headless_envelope(_array_envelope())
    assert env.parsed is True
    assert env.result_text == "MODEL TEXT"
    assert env.cost_micro_usd == 26900  # 0.0269 USD -> micro-USD (Decimal exact)
    assert env.input_tokens == 120
    assert env.output_tokens == 34
    assert env.cached_tokens == 80  # cache_read_input_tokens, NOT cache_creation
    assert env.is_error is False


def test_array_with_multiple_results_takes_the_last() -> None:
    payload = json.dumps(
        [
            _result_obj(result="FIRST", total_cost_usd=0.01),
            _result_obj(result="LAST", total_cost_usd=0.02),
        ]
    )
    env = parse_headless_envelope(payload)
    assert env.result_text == "LAST"
    assert env.cost_micro_usd == 20000


def test_bare_result_object_shape() -> None:
    # The documented single-object shape must also parse.
    env = parse_headless_envelope(json.dumps(_result_obj(result="BARE")))
    assert env.parsed is True
    assert env.result_text == "BARE"
    assert env.cost_micro_usd == 26900


def test_stream_json_takes_last_result_line_with_trailing_blanks() -> None:
    lines = [
        json.dumps({"type": "system"}),
        json.dumps(_result_obj(result="STREAMED", total_cost_usd=0.003)),
        "",
        "   ",
    ]
    env = parse_headless_envelope("\n".join(lines), output_format="stream-json")
    assert env.parsed is True
    assert env.result_text == "STREAMED"
    assert env.cost_micro_usd == 3000


def test_empty_stdout_falls_back_to_raw() -> None:
    env = parse_headless_envelope("")
    assert env.parsed is False
    assert env.result_text == ""
    assert env.cost_micro_usd is None


def test_non_json_falls_back_to_raw_text() -> None:
    raw = "this is just plain model prose, not JSON"
    env = parse_headless_envelope(raw)
    assert env.parsed is False
    assert env.result_text == raw  # text consumers see exactly today's stdout
    assert env.input_tokens is None


def test_json_not_dict_falls_back() -> None:
    # Valid JSON, but a scalar / list-without-result -> no usable envelope.
    for payload in ("123", '"a string"', "[1, 2, 3]", "[]"):
        env = parse_headless_envelope(payload)
        assert env.parsed is False, payload
        assert env.result_text == payload


def test_dict_without_result_key_falls_back() -> None:
    env = parse_headless_envelope(json.dumps({"type": "result", "total_cost_usd": 0.05}))
    assert env.parsed is False
    assert env.cost_micro_usd is None  # never lift cost without a real result text


def test_non_string_result_falls_back() -> None:
    # A non-string `result` must not be claimed as parsed (would drop the output).
    env = parse_headless_envelope(json.dumps(_result_obj(result={"nested": "obj"})))
    assert env.parsed is False


def test_absent_and_null_cost_is_none_never_zero() -> None:
    absent = parse_headless_envelope(_array_envelope(total_cost_usd=None))
    assert absent.parsed is True
    assert absent.cost_micro_usd is None  # null cost -> unavailable, NOT a real $0

    payload = json.dumps([_result_obj()])
    obj = json.loads(payload)
    del obj[0]["total_cost_usd"]
    missing = parse_headless_envelope(json.dumps(obj))
    assert missing.parsed is True
    assert missing.cost_micro_usd is None


def test_non_numeric_cost_is_none() -> None:
    env = parse_headless_envelope(_array_envelope(total_cost_usd="not-a-number"))
    assert env.parsed is True
    assert env.cost_micro_usd is None


def test_bool_tokens_rejected() -> None:
    # JSON `true` is not a token count (bool is an int subclass -> must be rejected).
    env = parse_headless_envelope(
        _array_envelope(usage={"input_tokens": True, "output_tokens": 5})
    )
    assert env.parsed is True
    assert env.input_tokens is None
    assert env.output_tokens == 5


def test_missing_usage_block_leaves_tokens_none_but_parses() -> None:
    payload = json.dumps([_result_obj(usage="not-a-dict")])
    env = parse_headless_envelope(payload)
    assert env.parsed is True
    assert env.input_tokens is None
    assert env.cached_tokens is None


def test_is_error_true_is_surfaced() -> None:
    env = parse_headless_envelope(
        _array_envelope(is_error=True, subtype="error_during_execution")
    )
    assert env.parsed is True
    assert env.is_error is True
