"""Regression test for walkthrough report-mode debug env and log cleanup.

Bug: walkthrough `--report` wanted QA-style debug logs, but the sandbox env
did not enable `FORGE_DEBUG` and reruns preserved stale `.forge-home/logs`
content. That made copied artifacts incomplete or polluted by prior runs.

Fix: env.sh exports `FORGE_DEBUG=1`, setup/reset scrubs `.forge-home/logs`
alongside other volatile walkthrough state, and reset preserves persistent
Forge/Claude state while recreating the owned Codex home empty.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression


def _source_debug_value(env_file: Path) -> str:
    result = subprocess.run(
        ["bash", "-c", 'source "$1" >/dev/null; printf "%s" "$FORGE_DEBUG"', "bash", str(env_file)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_setup_repo_enables_debug_and_reset_preserves_persistent_sandbox_state(tmp_path: Path) -> None:
    """Reset should clear volatile logs and the ephemeral Codex home."""
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
    assert _source_debug_value(env_file) == "1"
    assert "sandbox debug logging" in env_text

    log_file = forge_test_repo / ".forge-home" / "logs" / "cli" / "walkthrough.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("debug evidence\n", encoding="utf-8")
    assert log_file.exists()
    tracking = forge_test_repo / ".forge-home" / "installed.json"
    claude_settings = forge_test_repo / ".claude-user" / "settings.json"
    codex_settings = forge_test_repo / ".codex-user" / "config.toml"
    tracking.write_text('{"version": 1}\n', encoding="utf-8")
    claude_settings.write_text('{"custom": true}\n', encoding="utf-8")
    codex_settings.write_text('model = "gpt-5"\n', encoding="utf-8")

    reset = subprocess.run(
        ["bash", str(script), "--reset"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert reset.returncode == 0, reset.stderr
    assert not log_file.exists()
    assert tracking.read_text(encoding="utf-8") == '{"version": 1}\n'
    assert claude_settings.read_text(encoding="utf-8") == '{"custom": true}\n'
    assert codex_settings.parent.is_dir()
    assert not codex_settings.exists()

    assert _source_debug_value(env_file) == "1"
