"""Regression: an empty Codex provider error message produced blank stderr.

Bug: ``_extract_error_message`` returned ``""`` for an empty provider message, and
``_build_result`` only backfilled stderr when ``error_message`` was truthy -> a failed turn
rendered "Codex turn failed." with no detail.

Fix: empty/whitespace -> ``None`` in the extractor (core/invoker/codex_stream.py);
``_build_result`` backfills a generic line when ``is_error`` and no message
(core/invoker/codex.py).
"""

from __future__ import annotations

import pytest

from forge.core.invoker._lifecycle import ParseHints
from forge.core.invoker.codex import CodexHeadlessInvoker
from forge.core.invoker.codex_stream import parse_codex_jsonl_stream
from forge.core.invoker.types import HeadlessRequest

pytestmark = pytest.mark.regression


def test_empty_error_message_parses_to_none() -> None:
    stream = parse_codex_jsonl_stream('{"type": "error", "message": ""}')
    assert stream.is_error is True
    assert stream.error_message is None  # empty -> absent, not ""


def test_whitespace_error_message_parses_to_none() -> None:
    stream = parse_codex_jsonl_stream('{"type": "turn.failed", "error": {"message": "   "}}')
    assert stream.is_error is True
    assert stream.error_message is None


def test_build_result_backfills_generic_stderr_on_empty_error() -> None:
    result = CodexHeadlessInvoker()._build_result(
        HeadlessRequest(argv=["codex"], prompt="x", env={}),
        stdout='{"type": "turn.failed", "error": {"message": ""}}',
        stderr="",
        returncode=1,
        duration_seconds=0.1,
        ident={"run_id": None, "parent_run_id": None, "root_run_id": None},
        hints=ParseHints(is_jsonl_stream=True),
    )
    assert result.runtime_is_error is True
    assert result.stderr  # not blank
    assert "no provider error message" in result.stderr
