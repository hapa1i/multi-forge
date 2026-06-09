"""Regression: the --output-format capability guard/retry is centralized, not per-caller.

Phase 5 requests ``--output-format json`` optimistically. An older/odd ``claude``
that rejects the flag must NOT break headless work: the run retries EXACTLY ONCE
without the flag, latches "unsupported" so siblings skip it, and returns the raw
text. This is the R1 backstop and it must hold on BOTH headless runners --
``run_claude_session`` AND ``ClaudeHeadlessInvoker.run_parallel`` (the review
fan-out) -- proving the guard lives in the shared ``headless_json`` helpers, not
on the supervisor path alone.

Affected: ``src/forge/core/reactive/headless_json.py``,
``src/forge/core/reactive/session_runner.py``, ``src/forge/core/invoker/claude.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from forge.core.invoker import ClaudeHeadlessInvoker, HeadlessRequest
from forge.core.reactive import headless_json as hj
from forge.core.reactive.session_runner import run_claude_session

pytestmark = pytest.mark.regression

_REJECT = "error: unknown option '--output-format'"


@pytest.fixture(autouse=True)
def _reset_latch() -> Iterator[None]:
    hj.reset_json_capability_cache()
    yield
    hj.reset_json_capability_cache()


# --- run_claude_session ------------------------------------------------------


@patch("forge.core.reactive.session_runner.subprocess.run")
def test_session_runner_retries_once_without_flag_and_latches(mock_run: MagicMock) -> None:
    mock_run.side_effect = [
        MagicMock(stdout="", stderr=_REJECT, returncode=2),  # flag rejected
        MagicMock(stdout="raw text after retry", stderr="", returncode=0),  # retry sans flag
    ]
    result = run_claude_session("prompt")

    assert mock_run.call_count == 2, "exactly one retry, no more"
    first_argv = mock_run.call_args_list[0].args[0]
    second_argv = mock_run.call_args_list[1].args[0]
    assert "--output-format" in first_argv
    assert "--output-format" not in second_argv
    assert result.stdout == "raw text after retry"
    assert result.envelope_parsed is False
    # Latched: a sibling run now skips the flag entirely.
    assert hj.should_request_json(["claude", "-p"]) is False


@patch("forge.core.reactive.session_runner.subprocess.run")
def test_session_runner_skips_flag_when_already_latched(mock_run: MagicMock) -> None:
    hj.mark_json_output_unsupported()
    mock_run.return_value = MagicMock(stdout="plain", stderr="", returncode=0)
    run_claude_session("prompt")

    assert mock_run.call_count == 1, "latched -> no flag, no retry, single spawn"
    assert "--output-format" not in mock_run.call_args.args[0]


@patch("forge.core.reactive.session_runner.subprocess.run")
def test_session_runner_no_retry_on_unrelated_nonzero_exit(mock_run: MagicMock) -> None:
    # A genuine error (not a flag rejection) must NOT trigger a retry or latch.
    mock_run.return_value = MagicMock(stdout="", stderr="model overloaded", returncode=1)
    result = run_claude_session("prompt")

    assert mock_run.call_count == 1
    assert result.returncode == 1
    assert hj.should_request_json(["claude", "-p"]) is True  # not latched


# --- ClaudeHeadlessInvoker.run_parallel (the review fan-out) -----------------


def _reject_proc() -> MagicMock:
    proc = MagicMock()
    proc.communicate.return_value = ("", _REJECT)
    proc.returncode = 2
    proc.poll.return_value = 2
    proc.pid = 4321
    proc.wait.return_value = 2
    return proc


def _ok_proc(stdout: str) -> MagicMock:
    proc = MagicMock()
    proc.communicate.return_value = (stdout, "")
    proc.returncode = 0
    proc.poll.return_value = 0
    proc.pid = 4322
    proc.wait.return_value = 0
    return proc


@patch("forge.core.invoker._lifecycle.subprocess.run")
@patch("forge.core.invoker._lifecycle.subprocess.Popen")
def test_invoker_fan_out_retries_once_without_flag_and_latches(mock_popen: MagicMock, mock_run: MagicMock) -> None:
    # Primary spawn rejects the flag; the retry is a TRACKED Popen (not subprocess.run),
    # so it stays in `children` and remains terminable under cancellation (the fix).
    mock_popen.side_effect = [_reject_proc(), _ok_proc("raw fan-out text")]

    req = HeadlessRequest(argv=["claude", "-p"], prompt="p", env={}, label="w0")
    results = ClaudeHeadlessInvoker().run_parallel([req])

    assert len(results) == 1
    assert results[0].stdout == "raw fan-out text"
    assert results[0].envelope_parsed is False
    # Two TRACKED Popen spawns: primary (flagged) + retry (unflagged). The retry no
    # longer goes through subprocess.run, so it is reapable by _cleanup.
    assert mock_popen.call_count == 2
    assert "--output-format" in mock_popen.call_args_list[0].args[0]
    assert "--output-format" not in mock_popen.call_args_list[1].args[0]
    assert mock_run.call_count == 0
    assert hj.should_request_json(["claude", "-p"]) is False  # latched


@patch("forge.core.invoker._lifecycle.subprocess.run")
@patch("forge.core.invoker._lifecycle.subprocess.Popen")
def test_invoker_fan_out_skips_flag_when_latched(mock_popen: MagicMock, mock_run: MagicMock) -> None:
    hj.mark_json_output_unsupported()
    proc = MagicMock()
    proc.communicate.return_value = ("plain", "")
    proc.returncode = 0
    proc.poll.return_value = 0
    proc.pid = 5555
    proc.wait.return_value = 0
    mock_popen.return_value = proc

    req = HeadlessRequest(argv=["claude", "-p"], prompt="p", env={}, label="w0")
    ClaudeHeadlessInvoker().run_parallel([req])

    assert "--output-format" not in mock_popen.call_args.args[0]
    assert mock_run.call_count == 0  # no retry path taken


# --- over-broad-regex misfire guard --------------------------------------------
# The retry trigger must require unambiguous rejection phrasing. A non-zero exit
# whose stderr merely ECHOES the failing command line (a transient 529/overload/auth
# error that prints the invocation) must NOT be read as a flag rejection -- that
# misfire latches the JSON capability off process-wide AND, on a proxied worker,
# re-runs the request for a duplicate proxy-side cost row.


def test_is_json_flag_rejection_requires_unambiguous_phrasing() -> None:
    # Real argparse-style rejections still trigger the retry.
    assert hj.is_json_flag_rejection(2, "error: unknown option '--output-format'") is True
    assert hj.is_json_flag_rejection(1, "error: unrecognized arguments: --output-format json") is True
    # A transient error that merely echoes the failing command line must NOT.
    assert hj.is_json_flag_rejection(1, "API Error: 529 overloaded_error\n  claude -p --output-format json") is False
    assert hj.is_json_flag_rejection(1, "request failed while running claude -p --output-format json") is False
    # rc 0 is never a rejection, whatever the text.
    assert hj.is_json_flag_rejection(0, "unknown option") is False


@patch("forge.core.reactive.session_runner.subprocess.run")
def test_session_runner_no_retry_when_unrelated_error_echoes_flag(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(
        stdout="", stderr="API Error: 529 overloaded_error\n  claude -p --output-format json", returncode=1
    )
    result = run_claude_session("prompt")

    assert mock_run.call_count == 1  # no retry: the flag echo is not a rejection
    assert result.returncode == 1
    assert hj.should_request_json(["claude", "-p"]) is True  # capability not latched off
