"""Regression test for walkthrough report-mode debug env and log cleanup.

Bug: walkthrough `--report` wanted QA-style debug logs, but the sandbox env
did not enable `FORGE_DEBUG` and reruns preserved stale `.forge-home/logs`
content. That made copied artifacts incomplete or polluted by prior runs.

Fix: env.sh now exports `FORGE_DEBUG=1`, and setup/reset scrubs
`.forge-home/logs` alongside other volatile walkthrough state.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression


def test_setup_repo_enables_debug_and_reset_scrubs_logs(tmp_path: Path) -> None:
    """Generated env.sh should enable debug logs, and reset should clear them."""
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "src" / "skills" / "walkthrough" / "scripts" / "setup-test-repo.sh"

    home = tmp_path / "home"
    home.mkdir()
    forge_test_repo = tmp_path / "walkthrough-repo"

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(forge_test_repo)

    create = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert create.returncode == 0, create.stderr

    env_file = forge_test_repo / ".forge" / "walkthrough" / "env.sh"
    env_text = env_file.read_text(encoding="utf-8")
    assert 'export FORGE_DEBUG="1"' in env_text
    assert "sandbox debug logging" in env_text

    log_file = forge_test_repo / ".forge-home" / "logs" / "cli" / "walkthrough.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("debug evidence\n", encoding="utf-8")
    assert log_file.exists()

    reset = subprocess.run(
        ["bash", str(script), "--reset"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert reset.returncode == 0, reset.stderr
    assert not log_file.exists()

    reset_env_text = env_file.read_text(encoding="utf-8")
    assert 'export FORGE_DEBUG="1"' in reset_env_text
