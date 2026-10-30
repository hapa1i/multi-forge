"""Exercise the real sidecar launcher and Docker's multiline header transport."""

from __future__ import annotations

import json
import os
import pty
import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest

from forge.core.reactive.env import new_root_run_identity
from forge.core.run_id import (
    ANTHROPIC_CUSTOM_HEADERS_VAR,
    read_launch_id,
    read_projected_model_tier,
)
from forge.sidecar.container import run_sidecar_session

pytestmark = [pytest.mark.integration, pytest.mark.docker_host]


def test_owned_sidecar_preserves_launch_and_effort_headers(
    tmp_path: Path, sidecar_image: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_run = subprocess.run
    located = real_run(
        ["docker", "run", "--rm", "--entrypoint", "sh", sidecar_image, "-c", "command -v claude"],
        capture_output=True,
        text=True,
        check=True,
    )
    claude_path = located.stdout.strip()
    assert claude_path.startswith("/"), located.stdout + located.stderr
    project = tmp_path / "project"
    project.mkdir()
    capture = tmp_path / "claude"
    capture.write_text(
        "#!/bin/sh\n"
        "/forge/.venv/bin/python - <<'PY'\n"
        "import json, os, urllib.request\n"
        "with urllib.request.urlopen('http://localhost:8085/') as response:\n"
        "    assert json.load(response)['is_proxy'] is True\n"
        "keys = ('FORGE_RUN_ID', 'FORGE_ROOT_RUN_ID', 'ANTHROPIC_CUSTOM_HEADERS')\n"
        "with open('/workspace/launch-env.json', 'w') as output:\n"
        "    json.dump({key: os.environ.get(key) for key in keys}, output)\n"
        "PY\n"
    )
    capture.chmod(0o755)
    session_name = f"test-effort-{uuid.uuid4().hex[:8]}"
    root = new_root_run_identity()
    output: list[str] = []

    def run_with_terminal(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        if cmd[:2] != ["docker", "run"]:
            return real_run(cmd, **kwargs)
        # Give the unchanged interactive launcher a real terminal without running Claude.
        master, slave = pty.openpty()
        try:
            result = real_run(cmd, stdin=slave, capture_output=True, text=True, timeout=90, **kwargs)
            output.append(result.stdout + result.stderr)
            return result
        finally:
            os.close(slave)
            os.close(master)

    monkeypatch.setattr("forge.sidecar.container.subprocess.run", run_with_terminal)
    try:
        code = run_sidecar_session(
            image=sidecar_image,
            template="anthropic-passthrough",
            session_name=session_name,
            project_dir=project,
            extra_mounts=[(str(capture), claude_path, "ro")],
            env_vars={
                "ANTHROPIC_API_KEY": "test-not-real",
                ANTHROPIC_CUSTOM_HEADERS_VAR: "X-User: retained\nX-Forge-Effort-Source: client\nX-Forge-Launch: run_bbbbbbbbbbbb",
            },
            run_identity=root,
        )
        assert code == 0, "\n".join(output)
        env = json.loads((project / "launch-env.json").read_text())
        headers = env[ANTHROPIC_CUSTOM_HEADERS_VAR]
        assert read_launch_id(headers) == root.run_id == env["FORGE_RUN_ID"] == env["FORGE_ROOT_RUN_ID"]
        assert "X-User: retained" in headers
        assert "X-Forge-Effort-Source: client" in headers
        assert read_projected_model_tier(headers) is None
    finally:
        real_run(["docker", "rm", "-f", f"forge-{session_name}"], capture_output=True)
