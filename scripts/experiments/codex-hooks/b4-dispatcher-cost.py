"""Measure inactive installed hooks versus direct CLI startup without model calls."""

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import forge
from forge.install.hook_dispatcher import (
    dispatcher_source_sha256,
    render_dispatcher_script,
)
from forge.session.models import PolicyIntent, SupervisorConfig, create_session_state
from forge.session.store import SessionStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forge", type=Path, required=True, help="Installed Forge launcher")
    parser.add_argument("--samples", type=int, default=15)
    args = parser.parse_args()
    if not 1 <= args.samples <= 100:
        parser.error("samples must be between 1 and 100")
    measurements = {}
    with tempfile.TemporaryDirectory(prefix="forge-b4-hook-cost-") as temporary:
        root = Path(temporary)
        home = root / "home"
        home.mkdir()
        forge_home = home / ".forge"
        forge_home.mkdir()
        state = create_session_state("per-edit", worktree_path=str(root))
        state.forge_root = str(root)
        state.intent.policy = PolicyIntent(enabled=True, supervisor=SupervisorConfig(resume_id="planner"))
        SessionStore(str(root), state.name).write(state)
        script = root / "forge-hook"
        script.write_text(render_dispatcher_script())
        (forge_home / "runtime.json").write_text(
            json.dumps({"schema_version": 1, "forge_binary_path": str(args.forge.resolve())})
        )
        env = {
            "HOME": str(home),
            "PATH": os.defpath,
            "FORGE_HOME": str(forge_home),
            "FORGE_FORGE_ROOT": str(root),
            "FORGE_SESSION": state.name,
            "PYTHON_DOTENV_DISABLED": "1",
        }
        commands = {
            name: [sys.executable, str(script), name] for name in ("codex-turn-start", "codex-turn-tool", "codex-stop")
        }
        commands["direct-cli-control"] = [str(args.forge), "hook", "codex-turn-tool"]
        for name, command in commands.items():
            samples = []
            for _ in range(args.samples):
                start = time.perf_counter()
                result = subprocess.run(
                    command,
                    cwd=root,
                    env=env,
                    input='{"hook_event_name":"PostToolUse"}',
                    text=True,
                    capture_output=True,
                    timeout=10,
                    check=True,
                )
                assert not result.stdout and not result.stderr, result
                samples.append(round((time.perf_counter() - start) * 1000, 3))
            measurements[name] = {
                "samples_ms": samples,
                "median_ms": statistics.median(samples),
            }
    module = Path(forge.__file__).parent / "install/hook_dispatcher.py"
    print(
        json.dumps(
            {
                "inference": False,
                "fixture_removed": True,
                "samples_per_command": args.samples,
                "python": sys.version,
                "dispatcher_sha256": dispatcher_source_sha256(),
                "module_sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
                "measurements": measurements,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
