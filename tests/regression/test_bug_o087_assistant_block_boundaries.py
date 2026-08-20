"""Regression coverage for O087 assistant text-block boundary collapse.

Completion promises are valid only as standalone lines. Both supported Claude
transcript projections previously concatenated adjacent text blocks without a
separator, hiding a promise that began a later block and fabricating promises
whose text was split across blocks.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from forge.cli.hooks.verification import (
    _check_completion_promise,
    _get_last_assistant_text_for_verification,
)
from forge.session.models import VerificationConfig

pytestmark = pytest.mark.regression

_PROMISE = "VERIFICATION COMPLETE"
_Projection = Callable[[list[str]], dict[str, object]]


def _newer_projection(texts: list[str]) -> dict[str, object]:
    return {
        "requestId": "request-1",
        "timestamp": "2026-08-20T12:00:00Z",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text} for text in texts],
        },
    }


def _legacy_projection(texts: list[str]) -> dict[str, object]:
    return {
        "type": "assistant",
        "timestamp": "2026-08-20T12:00:00Z",
        "message": {
            "content": [{"type": "text", "text": text} for text in texts],
        },
    }


_PROJECTIONS = (
    pytest.param(_newer_projection, id="request-message-role"),
    pytest.param(_legacy_projection, id="legacy-entry-type"),
)


def _write_transcript(tmp_path: Path, entry: dict[str, object]) -> Path:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    return transcript


def _completion_status(transcript: Path) -> str:
    config = VerificationConfig(type="completion_promise", promise=_PROMISE)
    return _check_completion_promise(config, transcript).status


@pytest.mark.parametrize("projection", _PROJECTIONS)
def test_later_text_block_keeps_standalone_promise(
    tmp_path: Path,
    projection: _Projection,
) -> None:
    transcript = _write_transcript(tmp_path, projection(["Implementation finished.", _PROMISE]))

    assert _get_last_assistant_text_for_verification(transcript) == f"Implementation finished.\n{_PROMISE}"
    assert _completion_status(transcript) == "passed"


@pytest.mark.parametrize("projection", _PROJECTIONS)
@pytest.mark.parametrize(
    ("texts", "expected"),
    (
        pytest.param(["Implementation finished.\n", _PROMISE], f"Implementation finished.\n{_PROMISE}", id="left"),
        pytest.param(
            ["Implementation finished.", f"\n{_PROMISE}"], f"Implementation finished.\n{_PROMISE}", id="right"
        ),
        pytest.param([_PROMISE], _PROMISE, id="single-block"),
    ),
)
def test_existing_or_unneeded_boundaries_are_unchanged(
    tmp_path: Path,
    projection: _Projection,
    texts: list[str],
    expected: str,
) -> None:
    transcript = _write_transcript(tmp_path, projection(texts))

    assert _get_last_assistant_text_for_verification(transcript) == expected


@pytest.mark.parametrize("projection", _PROJECTIONS)
@pytest.mark.parametrize(
    "texts",
    (
        pytest.param([f"Not {_PROMISE} yet"], id="single-block-substring"),
        pytest.param(["Still working.", f"Not {_PROMISE} yet"], id="later-block-substring"),
        pytest.param(["VERIFICATION ", "COMPLETE"], id="split-across-blocks"),
    ),
)
def test_non_standalone_promise_remains_incomplete(
    tmp_path: Path,
    projection: _Projection,
    texts: list[str],
) -> None:
    transcript = _write_transcript(tmp_path, projection(texts))

    assert _completion_status(transcript) == "incomplete"
