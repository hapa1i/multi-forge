"""Regression: malformed transcript usage rows crashed compute_cache_hit_rate.

Bug: ``compute_cache_hit_rate`` assumed ``message``/``usage`` were dicts and the
token fields were numeric. A valid JSONL row like ``{"message": {"usage":
{"input_tokens": "100"}}}`` raised ``TypeError`` at the final ``sum()``; a
non-dict ``message`` raised ``AttributeError``. The transcript is an external
Claude Code artifact (system boundary) and cache_hit is an opt-in segment, so
bad rows must be skipped/coerced, not crash.

Root cause / fix: ``src/forge/cli/status_line.py`` — guard ``message``/``usage``
shapes, coerce token fields with ``_safe_int``, and skip rows that still raise.
"""

from __future__ import annotations

import json

import pytest

from forge.cli.status_line import compute_cache_hit_rate

pytestmark = pytest.mark.regression


def _write(tmp_path, entries):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries))
    return str(p)


def test_string_token_field_coerced(tmp_path):
    path = _write(
        tmp_path, [{"requestId": "r1", "message": {"usage": {"input_tokens": "100", "cache_read_input_tokens": "50"}}}]
    )
    assert compute_cache_hit_rate(path) == 50.0  # coerced, not crashed


def test_non_numeric_token_field_skipped(tmp_path):
    path = _write(
        tmp_path, [{"requestId": "r1", "message": {"usage": {"input_tokens": "abc", "cache_read_input_tokens": 5}}}]
    )
    # input coerces to 0 -> no usable input -> 0.0, no crash.
    assert compute_cache_hit_rate(path) == 0.0


def test_non_dict_message_skipped(tmp_path):
    path = _write(tmp_path, [{"requestId": "r1", "message": "not-a-dict"}])
    assert compute_cache_hit_rate(path) is None


def test_non_dict_usage_skipped(tmp_path):
    path = _write(tmp_path, [{"requestId": "r1", "message": {"usage": [1, 2, 3]}}])
    assert compute_cache_hit_rate(path) is None


def test_non_object_json_line_skipped(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(
        "123\n[1,2]\n"
        + json.dumps({"requestId": "r1", "message": {"usage": {"input_tokens": 100, "cache_read_input_tokens": 40}}})
    )
    assert compute_cache_hit_rate(str(p)) == 40.0  # good row still counted


def test_mixed_good_and_bad_rows(tmp_path):
    path = _write(
        tmp_path,
        [
            {"requestId": "r1", "message": {"usage": {"input_tokens": "bad"}}},  # skipped/zeroed
            {"requestId": "r2", "message": "nope"},  # skipped
            {"requestId": "r3", "message": {"usage": {"input_tokens": 100, "cache_read_input_tokens": 25}}},
        ],
    )
    assert compute_cache_hit_rate(path) == 25.0  # only r3 contributes
