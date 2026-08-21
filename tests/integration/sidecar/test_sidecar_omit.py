"""Verify that a sidecar can withhold upstream credentials from Claude.

The entrypoint starts the proxy before it removes ``ANTHROPIC_API_KEY`` from the
Claude process. The test reads each process environment to confirm that Claude
has no key and the proxy retains its upstream credential.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from forge.core.reactive.env import FORGE_PROXY_WIRE_SHAPE_VAR
from forge.sidecar.docker import is_docker_available

pytestmark = [pytest.mark.integration, pytest.mark.docker_host]

CONTAINER = "forge-test-omit-sidecar"


@pytest.fixture(scope="module", autouse=True)
def _require_docker() -> None:
    """Fail loudly if Docker is unavailable (never-skip policy)."""
    if not is_docker_available():
        pytest.fail("Docker not available. Start Docker and re-run integration tests.")


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True)


def _claude_path(image: str) -> str:
    result = _docker("run", "--rm", "--entrypoint", "sh", image, "-c", "command -v claude")
    path = result.stdout.strip()
    if not path:
        pytest.fail(f"Could not locate `claude` in {image}: {result.stderr}")
    return path


# Report which container processes retain ANTHROPIC_API_KEY.
_PROC_PROBE = (
    "import glob\n"
    "def has(pid):\n"
    "    return b'ANTHROPIC_API_KEY=' in open(f'/proc/{pid}/environ','rb').read()\n"
    "ppid=None\n"
    "for p in glob.glob('/proc/[0-9]*'):\n"
    "    try:\n"
    "        if b'forge.proxy.server' in open(p+'/cmdline','rb').read(): ppid=p.split('/')[-1]\n"
    "    except Exception: pass\n"
    "print('claude', has(1))\n"
    "print('proxy', has(ppid) if ppid else 'none')\n"
)


def test_sidecar_omit_withholds_key_from_claude_but_proxy_keeps_it(sidecar_image: str) -> None:
    sleeper = Path(__file__).parent / ".forge-omit-claude-sleeper"
    sleeper.write_text("#!/bin/sh\nexec sleep 300\n")
    sleeper.chmod(0o755)
    claude_path = _claude_path(sidecar_image)

    _docker("rm", "-f", CONTAINER)
    run_cmd = [
        "run",
        "-d",
        "--name",
        CONTAINER,
        "-e",
        "FORGE_TEMPLATE=anthropic-passthrough",
        "-e",
        "FORGE_SIDECAR=1",
        "-e",
        f"{FORGE_PROXY_WIRE_SHAPE_VAR}=anthropic_passthrough",
        "-e",
        "HOME=/root",
        "-e",
        "ANTHROPIC_API_KEY=test-not-real",
        "-e",
        "FORGE_OMIT_INTERACTIVE_KEY=1",
        "-v",
        f"{sleeper}:{claude_path}:ro",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        sidecar_image,
    ]

    try:
        started = _docker(*run_cmd)
        assert started.returncode == 0, f"docker run failed: {started.stderr}"

        # PID 1 becomes the sleeper only after the proxy is healthy and the key is removed.
        ready = False
        for _ in range(60):
            cmd = _docker("exec", CONTAINER, "cat", "/proc/1/cmdline")
            if cmd.returncode == 0 and "sleep" in cmd.stdout:
                ready = True
                break
            time.sleep(1)
        logs = _docker("logs", CONTAINER)
        assert ready, f"claude (sleeper) never became PID 1.\nSTDOUT:\n{logs.stdout}\nSTDERR:\n{logs.stderr}"
        assert "withheld from Claude" in (logs.stdout + logs.stderr), "entrypoint did not announce omit"

        check = _docker("exec", CONTAINER, "/forge/.venv/bin/python", "-c", _PROC_PROBE)
        assert check.returncode == 0, f"proc inspect failed: {check.stderr}"
        assert "claude False" in check.stdout, f"Claude still sees ANTHROPIC_API_KEY: {check.stdout}"
        assert "proxy True" in check.stdout, f"proxy lost its upstream credential: {check.stdout}"
    finally:
        _docker("rm", "-f", CONTAINER)
        sleeper.unlink(missing_ok=True)
