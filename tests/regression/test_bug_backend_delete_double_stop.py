"""Regression: `forge model backend delete --port` double-printed "Stopped" + nested sys.exit.

Bug: ``delete_cmd`` invoked ``stop_cmd.callback()``, so the stop command printed its own
"Stopped" line (delete then printed a second one) and, on failure, ran ``sys.exit(1)``
*inside* ``delete_cmd``'s ``try/except Exception`` -- ``SystemExit`` is not an ``Exception``,
so delete's own error path was bypassed. Fix: both commands share a silent
``_stop_instance(adapter, port)`` helper; delete owns its output and error handling.

Affected: src/forge/cli/backend.py (_stop_instance, delete_cmd, stop_cmd).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main

pytestmark = pytest.mark.regression


def test_delete_by_port_prints_single_stopped() -> None:
    """delete --port stops the instance once and prints exactly one "Stopped" line."""
    with patch("forge.cli.backend._stop_instance") as stop:
        result = CliRunner().invoke(main, ["model", "backend", "delete", "litellm", "--port", "4000", "--yes"])

    assert result.exit_code == 0, result.output
    stop.assert_called_once_with("litellm", 4000)
    assert result.output.count("Stopped") == 1


def test_delete_by_port_stop_failure_uses_delete_error_path() -> None:
    """A stop failure surfaces via delete's own error path, not a swallowed nested exit."""
    with patch("forge.cli.backend._stop_instance", side_effect=RuntimeError("boom")):
        result = CliRunner().invoke(main, ["model", "backend", "delete", "litellm", "--port", "4000", "--yes"])

    assert result.exit_code == 1
    assert "boom" in result.output
    assert result.output.count("Stopped") == 0
