"""Full-command source acquisition tests for the status-line segment plan."""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from forge.cli import status_line as sl
from forge.cli.status_line import TranscriptStats, status_line
from forge.runtime_config import RuntimeConfig, StatusLineConfig

_INPUT = {
    "workspace": {"current_dir": "/tmp/source-plan"},
    "model": {"display_name": "Opus 4.6"},
    "context_window": {
        "context_window_size": 200_000,
        "used_percentage": 12,
        "current_usage": {"input_tokens": 12_000},
    },
}


@pytest.mark.parametrize(
    ("segments", "expected_proxy_calls", "expected_session_calls"),
    [
        (["path", "branch"], 0, 0),
        (["model"], 1, 0),
        (["breadcrumb"], 0, 1),
        (["cost"], 1, 1),
        ([], 1, 1),
    ],
)
def test_status_line_acquires_only_declared_sources_once(
    segments: list[str],
    expected_proxy_calls: int,
    expected_session_calls: int,
) -> None:
    config = RuntimeConfig(statusline=StatusLineConfig(segments=segments))
    proxy_probe = Mock(return_value=(False, None, False))
    session_probe = Mock(return_value=(None, False))

    with (
        patch.object(sl, "detect_proxy", proxy_probe),
        patch.object(sl, "discover_session", session_probe),
        patch.object(sl, "get_git_branch", return_value="main"),
        patch.object(sl, "_cached_scan_transcript", return_value=TranscriptStats()),
        patch.object(sl, "_get_terminal_width", return_value=200),
        patch("forge.runtime_config.get_runtime_config", return_value=config),
    ):
        result = CliRunner().invoke(
            status_line,
            input=json.dumps(_INPUT),
            env={"FORGE_STATUS_TRUNCATE": "0"},
        )

    assert result.exit_code == 0, result.output
    assert proxy_probe.call_count == expected_proxy_calls
    assert session_probe.call_count == expected_session_calls


def test_repeated_zero_source_renders_keep_probe_counters_at_zero() -> None:
    """Instrument the hot path: repeated minimal polls never enter either probe."""
    config = RuntimeConfig(statusline=StatusLineConfig(segments=["path", "branch"]))
    proxy_probe = Mock(return_value=(False, None, False))
    session_probe = Mock(return_value=(None, False))
    runner = CliRunner()

    with (
        patch.object(sl, "detect_proxy", proxy_probe),
        patch.object(sl, "discover_session", session_probe),
        patch.object(sl, "get_git_branch", return_value="main"),
        patch.object(sl, "_get_terminal_width", return_value=200),
        patch("forge.runtime_config.get_runtime_config", return_value=config),
    ):
        results = [
            runner.invoke(
                status_line,
                input=json.dumps(_INPUT),
                env={"FORGE_STATUS_TRUNCATE": "0"},
            )
            for _ in range(25)
        ]

    assert all(result.exit_code == 0 for result in results)
    assert proxy_probe.call_count == 0
    assert session_probe.call_count == 0
