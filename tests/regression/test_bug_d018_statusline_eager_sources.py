"""Regression for D018: unrelated status-line layouts eagerly probed proxy and session state."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli import status_line as sl
from forge.cli.status_line import status_line
from forge.cli.statusline import sources as status_sources
from forge.runtime_config import RuntimeConfig, StatusLineConfig

pytestmark = pytest.mark.regression


def test_bug_d018_path_branch_layout_skips_proxy_and_session_sources() -> None:
    """A zero-source layout must not touch either expensive discovery boundary."""
    calls: list[str] = []
    config = RuntimeConfig(statusline=StatusLineConfig(segments=["path", "branch"]))

    def _detect_proxy() -> tuple[bool, None, bool]:
        calls.append("proxy")
        return False, None, False

    def _discover_session() -> tuple[None, bool]:
        calls.append("session")
        return None, False

    with (
        patch.object(status_sources, "detect_proxy", side_effect=_detect_proxy),
        patch.object(status_sources, "discover_session", side_effect=_discover_session),
        patch.object(status_sources, "get_git_branch", return_value="main"),
        patch.object(sl, "_get_terminal_width", return_value=200),
        patch("forge.runtime_config.get_runtime_config", return_value=config),
    ):
        result = CliRunner().invoke(
            status_line,
            input=json.dumps(
                {
                    "workspace": {"current_dir": "/tmp/d018"},
                    "model": {"display_name": "Test"},
                }
            ),
            env={"FORGE_STATUS_TRUNCATE": "0"},
        )

    assert result.exit_code == 0, result.output
    assert calls == []
    assert "/tmp/d018" in result.output.replace("\u00a0", " ")
    assert "main" in result.output
