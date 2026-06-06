"""Regression: a runtime-reported error (envelope is_error) maps to a failed status.

Spike 5a confirmed ``is_error`` is a trustworthy top-level field that can be
``true`` with EXIT 0 (subtype ``error_during_execution`` / ``error_max_turns``).
So a clean process exit is not proof of success: when an envelope was parsed and
``is_error`` is true, the usage ledger must record ``status="error"`` /
``failure_type="runtime_reported_error"``. Crucially this steers the LEDGER STATUS
ONLY -- ``SessionResult.success`` stays returncode-based so fail-open control flow
(supervisor / memory writer) is unchanged.

Affected: ``src/forge/core/reactive/session_runner.py`` (``runtime_is_error``),
``src/forge/core/usage/emit.py`` (``_session_status``).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from forge.core.reactive import headless_json as hj
from forge.core.reactive.session_runner import SessionResult, run_claude_session
from forge.core.usage.emit import _session_status

pytestmark = pytest.mark.regression


@pytest.fixture(autouse=True)
def _reset_latch() -> Iterator[None]:
    hj.reset_json_capability_cache()
    yield
    hj.reset_json_capability_cache()


def _envelope(is_error: bool) -> str:
    return json.dumps(
        [
            {"type": "system"},
            {
                "type": "result",
                "subtype": "error_during_execution" if is_error else "success",
                "result": "text",
                "total_cost_usd": 0.01,
                "is_error": is_error,
                "usage": {"input_tokens": 10, "output_tokens": 2},
            },
        ]
    )


@patch("forge.core.reactive.session_runner.subprocess.run")
def test_exit_zero_with_is_error_sets_runtime_is_error(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(stdout=_envelope(is_error=True), stderr="", returncode=0)
    result = run_claude_session("prompt")

    assert result.returncode == 0
    assert result.runtime_is_error is True
    # success stays returncode-based: consumers branching on it are unchanged.
    assert result.success is True


@patch("forge.core.reactive.session_runner.subprocess.run")
def test_exit_zero_without_is_error_is_clean(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(stdout=_envelope(is_error=False), stderr="", returncode=0)
    result = run_claude_session("prompt")
    assert result.runtime_is_error is False


def test_session_status_maps_runtime_error_to_failure() -> None:
    rt_err = SessionResult(stdout="t", stderr="", returncode=0, envelope_parsed=True, runtime_is_error=True)
    assert _session_status(rt_err) == ("error", "runtime_reported_error")


def test_session_status_success_when_no_runtime_error() -> None:
    ok = SessionResult(stdout="t", stderr="", returncode=0, envelope_parsed=True, runtime_is_error=False)
    assert _session_status(ok) == ("success", None)


def test_session_status_returncode_path_unchanged() -> None:
    # A non-zero exit keeps its returncode-derived failure_type (no regression).
    nonzero = SessionResult(stdout="", stderr="boom", returncode=3)
    assert _session_status(nonzero) == ("error", "exit_3")

    timeout = SessionResult(stdout="", stderr="", returncode=-1, timed_out=True)
    assert _session_status(timeout) == ("timeout", "timeout")
