"""B4: user-scope turn hooks started the full Forge CLI even without Stop supervision."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from forge.install.hook_dispatcher import render_dispatcher_script
from forge.session.effective import apply_overrides

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("handler", ["codex-turn-start", "codex-turn-tool", "codex-stop"])
@pytest.mark.parametrize(
    "override",
    [
        {},
        {"policy": None},
        {"policy": {"enabled": False}},
        {"policy": {"supervisor": {"review_trigger": "stop"}}},
        {"policy": {"supervisor": {"review_trigger": "stop", "suspended": True}}},
    ],
)
def test_installed_dispatcher_only_execs_cli_for_effective_stop(tmp_path: Path, handler: str, override: dict) -> None:
    script = tmp_path / "forge-hook"
    script.write_text(render_dispatcher_script())
    checkout = tmp_path / "dev"
    launcher = checkout / ".venv/bin/forge"
    launcher.parent.mkdir(parents=True)
    launcher.write_text(f"#!{sys.executable}\nimport sys\nprint(sys.stdin.read())\n")
    launcher.chmod(0o755)
    path = tmp_path / ".forge/sessions/fixture/forge.session.json"
    path.parent.mkdir(parents=True)
    intent = {"policy": {"enabled": True, "supervisor": {"resume_id": "planner"}}}
    path.write_text(json.dumps({"schema_version": 4, "intent": intent, "overrides": override}))
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
    policy = apply_overrides(intent, override)["policy"]
    sup = policy.get("supervisor") if policy else None
    active = bool(
        policy and policy["enabled"] and sup and sup.get("review_trigger") == "stop" and not sup.get("suspended")
    )
    assert result.stdout == ("payload\n" if active else "")
    # No restart needed: enabling Stop on an already-running executor is seen.
    path.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "intent": {
                    "policy": {
                        "enabled": True,
                        "supervisor": {
                            "resume_id": "planner",
                            "review_trigger": "stop",
                        },
                    }
                },
                "overrides": {},
            }
        )
    )
    result = subprocess.run(
        [sys.executable, str(script), handler],
        env=env,
        input="enabled",
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    )
    assert result.stdout == "enabled\n"


def test_unmanaged_skips_cli_but_enrollment_probe_dispatches(tmp_path: Path) -> None:
    script = tmp_path / "forge-hook"
    script.write_text(render_dispatcher_script())
    env = {"PATH": os.defpath, "HOME": str(tmp_path), "FORGE_DEV": "/missing"}
    command = [sys.executable, str(script), "codex-turn-tool"]
    assert subprocess.run(command, env=env, capture_output=True, timeout=5).returncode == 0
    env.update(FORGE_SESSION="forge-enroll-probe", FORGE_CODEX_ENROLLMENT_NONCE="a" * 32)
    assert subprocess.run(command, env=env, capture_output=True, timeout=5).returncode == 127
