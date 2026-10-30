"""CLI content fixtures must override widths captured from the invoking shell."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression
ROOT = Path(__file__).resolve().parents[2]


def test_cli_content_assertions_ignore_initial_narrow_columns(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/src/cli/test_session_start_delete.py::TestSessionDelete::test_orphan_refuses_and_names_repair[False]",
            "tests/src/cli/test_session_rewind_cli.py::test_resume_fresh_rewind_privacy_warning_for_code_delta_llm",
            "tests/src/cli/test_activity.py::test_human_render_shows_runtime_billing",
            "-n",
            "0",
            "-q",
            "--basetemp",
            str(tmp_path / "child-pytest"),
        ],
        cwd=ROOT,
        env={**os.environ, "COLUMNS": "80", "PYTEST_ADDOPTS": ""},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed" in result.stdout
