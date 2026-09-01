"""Regression: managed walkthrough children must use sandbox hook settings.

``CLAUDE_HOME`` is Forge's isolated install/test path, but Claude Code selects
its native config with ``CLAUDE_CONFIG_DIR``. Launching Claude directly used the
real user settings and could make a walkthrough pass only because Forge hooks
were already installed outside the sandbox.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "src/skills/walkthrough/scripts"


def test_generated_launcher_loads_only_sandbox_hook_settings(tmp_path: Path) -> None:
    """The PATH shim keeps native auth/store state but excludes real user settings."""
    home = tmp_path / "home"
    target = tmp_path / "walkthrough-repo"
    fake_bin = tmp_path / "native-bin"
    native_config = tmp_path / "native-claude"
    capture_args = tmp_path / "claude-args.txt"
    capture_config = tmp_path / "claude-config.txt"
    home.mkdir()
    fake_bin.mkdir()
    native_config.mkdir()

    fake_claude = fake_bin / "claude"
    fake_claude.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"printf '%s\\n' \"$@\" > {shlex.quote(str(capture_args))}\n"
        f"printf '%s\\n' \"${{CLAUDE_CONFIG_DIR:-}}\" > {shlex.quote(str(capture_config))}\n"
        "printf '9.9.9 (native fixture)\\n'\n",
        encoding="utf-8",
    )
    fake_claude.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "FORGE_TEST_REPO": str(target),
            "CLAUDE_CONFIG_DIR": str(native_config),
            "PATH": f"{fake_bin}:{env['PATH']}",
        }
    )
    setup = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert setup.returncode == 0, setup.stderr

    launched = subprocess.run(
        ["bash", str(SCRIPTS / "run-in-repo.sh"), "claude", "--version"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert launched.returncode == 0, launched.stderr
    assert launched.stdout == "9.9.9 (native fixture)\n"
    assert capture_args.read_text(encoding="utf-8").splitlines() == [
        "--setting-sources",
        "project,local",
        "--settings",
        str(target / ".claude-user/settings.json"),
        "--version",
    ]
    assert capture_config.read_text(encoding="utf-8").strip() == str(native_config)
    assert (target / ".claude-user/settings.json").read_text(encoding="utf-8") == "{}\n"
    assert (target / ".forge/walkthrough/bin/claude").is_file()
