"""O021 regression: generic argument errors disable process-wide JSON output."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from forge.core.reactive import headless_json as hj
from forge.core.reactive.session_runner import run_claude_session

pytestmark = pytest.mark.regression


@pytest.fixture(autouse=True)
def _reset_capability_latch() -> Iterator[None]:
    hj.reset_json_capability_cache()
    yield
    hj.reset_json_capability_cache()


@pytest.mark.parametrize(
    "stderr",
    [
        "error: unknown option '--model'",
        "error: unknown argument '--effort'",
        "error: unexpected argument '--verbose'",
        "error: unrecognized option '--permission-mode'",
        "error: value is not in the allowed choices for --model",
    ],
)
def test_o021_generic_rejection_must_not_implicate_output_format(stderr: str) -> None:
    assert hj.is_json_flag_rejection(2, stderr) is False


def test_o021_explicit_output_format_rejection_remains_detected() -> None:
    assert hj.is_json_flag_rejection(2, "error: unknown option '--output-format'") is True
    assert hj.is_json_flag_rejection(2, "invalid choice for --output-format") is True


@patch("forge.core.reactive.session_runner.subprocess.run")
def test_o021_generic_unknown_option_does_not_retry_or_latch(
    mock_run: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FORGE_SUBPROCESS_PROXY", raising=False)
    mock_run.return_value = MagicMock(
        stdout="",
        stderr="error: unknown option '--model'",
        returncode=2,
    )

    result = run_claude_session("prompt")

    assert result.returncode == 2
    assert mock_run.call_count == 1
    assert hj.should_request_json(["claude", "-p"]) is True
