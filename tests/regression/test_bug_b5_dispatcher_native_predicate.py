"""B5: the stdlib turn-hook dispatcher missed native-only Stop supervisors."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from forge.install.hook_dispatcher import render_dispatcher_script

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("handler", ["codex-turn-start", "codex-turn-tool", "codex-stop"])
def test_native_only_stop_supervisor_reaches_the_turn_handler(tmp_path: Path, handler: str) -> None:
    # Mirrors SupervisorConfig.configured, which counts a native source with no
    # conversation target or plan path; skipping would silently drop turn evidence.
    script = tmp_path / "forge-hook"
    script.write_text(render_dispatcher_script())
    checkout = tmp_path / "dev"
    launcher = checkout / ".venv/bin/forge"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(f"#!{sys.executable}\nimport sys\nprint('cli', sys.stdin.read())\n")
    launcher.chmod(0o755)
    manifest = tmp_path / ".forge/sessions/fixture/forge.session.json"
    manifest.parent.mkdir(parents=True)
    supervisor = {"review_trigger": "stop", "native_source": {"runtime": "codex", "thread_id": "native"}}
    intent = {"policy": {"enabled": True, "supervisor": supervisor}}
    manifest.write_text(json.dumps({"schema_version": 5, "intent": intent}))
    env = {
        "PATH": os.defpath,
        "HOME": str(tmp_path),
        "FORGE_DEV": str(checkout),
        "FORGE_SESSION": "fixture",
        "FORGE_FORGE_ROOT": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, str(script), handler],
        env=env,
        input="payload",
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    )
    assert result.stdout.strip() == "cli payload"
