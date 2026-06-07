"""Regression: headless JSON unwrap must keep text consumers byte-for-byte unchanged.

Phase 5 added ``--output-format json`` to every ``claude -p`` run. The envelope is
parsed at the subprocess boundary and ``.result`` is unwrapped back into
``SessionResult.stdout`` so existing text consumers (supervisor verdict parse,
memory writer, shadow curation) read exactly what they read before -- while the
runtime's self-reported cost/usage is lifted onto new nullable fields.

The hazard: if unwrap dropped, truncated, or altered the model text, every text
consumer would silently break. This pins that the happy path unwraps to the
result text, and that non-envelope / non-zero-exit outputs fall back to raw stdout
with metrics ``None`` and ``envelope_parsed=False``.

Affected: ``src/forge/core/reactive/session_runner.py``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from forge.core.reactive import headless_json as hj
from forge.core.reactive.session_runner import run_claude_session

pytestmark = pytest.mark.regression


@pytest.fixture(autouse=True)
def _reset_latch() -> Iterator[None]:
    hj.reset_json_capability_cache()
    yield
    hj.reset_json_capability_cache()


def _envelope(result_text: str = "VERDICT: aligned", **overrides: object) -> str:
    obj: dict[str, object] = {
        "type": "result",
        "subtype": "success",
        "result": result_text,
        "total_cost_usd": 0.0042,
        "is_error": False,
        "usage": {
            "input_tokens": 200,
            "output_tokens": 50,
            "cache_read_input_tokens": 100,
        },
    }
    obj.update(overrides)
    return json.dumps([{"type": "system"}, obj])


@patch("forge.core.reactive.session_runner.subprocess.run")
def test_success_unwraps_result_and_lifts_metrics(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(stdout=_envelope("VERDICT: aligned"), stderr="", returncode=0)
    result = run_claude_session("prompt")

    # Text consumers see the unwrapped model text, NOT the JSON envelope.
    assert result.stdout == "VERDICT: aligned"
    assert "total_cost_usd" not in result.stdout
    assert result.envelope_parsed is True
    assert result.cost_micro_usd == 4200
    assert result.input_tokens == 200
    assert result.output_tokens == 50
    assert result.cached_tokens == 100
    assert result.success is True


@patch("forge.core.reactive.session_runner.subprocess.run")
def test_nonzero_exit_keeps_raw_stdout_and_no_metrics(mock_run: MagicMock) -> None:
    # A non-zero exit is not parsed: raw stdout preserved, metrics stay None.
    mock_run.return_value = MagicMock(stdout="partial output", stderr="boom", returncode=1)
    result = run_claude_session("prompt")

    assert result.stdout == "partial output"
    assert result.envelope_parsed is False
    assert result.cost_micro_usd is None
    assert result.input_tokens is None
    assert result.success is False


@patch("forge.core.reactive.session_runner.subprocess.run")
def test_non_envelope_stdout_falls_back_to_raw(mock_run: MagicMock) -> None:
    # JSON was requested, but the CLI emitted plain prose (e.g. an old/odd build):
    # fall back to raw text, no metrics, no crash.
    mock_run.return_value = MagicMock(stdout="just plain prose", stderr="", returncode=0)
    result = run_claude_session("prompt")

    assert result.stdout == "just plain prose"
    assert result.envelope_parsed is False
    assert result.cost_micro_usd is None


@patch("forge.core.reactive.session_runner.subprocess.run")
def test_token_only_envelope_keeps_tokens_without_cost(mock_run: MagicMock) -> None:
    # Direct OAuth: usage present but no dollar figure. envelope_parsed AND tokens
    # are set; cost is None (independent facts -- #1).
    mock_run.return_value = MagicMock(stdout=_envelope("text", total_cost_usd=None), stderr="", returncode=0)
    result = run_claude_session("prompt")

    assert result.envelope_parsed is True
    assert result.input_tokens == 200
    assert result.cost_micro_usd is None


@patch("forge.core.reactive.session_runner.subprocess.run")
def test_output_format_none_keeps_plain_text_path(mock_run: MagicMock) -> None:
    # output_format=None never requests JSON; stdout is the raw text untouched and
    # the --output-format token is absent from the argv.
    mock_run.return_value = MagicMock(stdout="raw model text", stderr="", returncode=0)
    result = run_claude_session("prompt", output_format=None)

    assert result.stdout == "raw model text"
    assert result.envelope_parsed is False
    argv = mock_run.call_args.args[0]
    assert "--output-format" not in argv
