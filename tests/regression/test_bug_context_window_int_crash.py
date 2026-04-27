"""Regression: context_window as int crashes status-line.

Bug: Claude Code sends context_window as a plain integer (e.g., 200000)
in early conversation turns before usage data is available. The
parse_context_from_json function called .get() on the int, raising
AttributeError and silently killing the status-line process.

Root cause: parse_context_from_json assumed context_window was always a dict
with context_window_size and current_usage fields.

Fix: Guard with isinstance check — return None for int/float values.

Affected file: src/forge/cli/status_line.py
"""

import pytest

from forge.cli.status_line import parse_context_from_json

pytestmark = pytest.mark.regression


def test_context_window_int_does_not_crash():
    """context_window as int must return None, not raise AttributeError."""
    data = {
        "context_window": 200000,
        "exceeds_200k_tokens": False,
    }
    result = parse_context_from_json(data)
    assert result is None


def test_context_window_dict_still_works():
    """context_window as dict with usage data still parses correctly."""
    data = {
        "context_window": {
            "context_window_size": 200000,
            "current_usage": {
                "input_tokens": 8500,
                "cache_creation_input_tokens": 5000,
                "cache_read_input_tokens": 2000,
            },
        },
    }
    result = parse_context_from_json(data)
    assert result is not None
    assert result["tokens"] == 15500
    assert result["context_window"] == 200000
    assert result["percent"] == 7


def test_context_window_zero_returns_none():
    """context_window of 0 (falsy int) returns None."""
    data = {"context_window": 0}
    result = parse_context_from_json(data)
    assert result is None


def test_context_window_missing_returns_none():
    """Missing context_window returns None."""
    data = {"model": {"display_name": "Claude"}}
    result = parse_context_from_json(data)
    assert result is None
