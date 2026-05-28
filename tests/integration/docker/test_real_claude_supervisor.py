"""Best-effort real-Claude supervisor smoke test.

Exercises the real ``forge policy supervisor`` path against a live planning
session so ``claude -p --resume`` is covered with a real Claude backend.

Assertions stay narrow to reduce flakiness:
- the planning session gets a confirmed Claude session ID
- the supervisor exits without infra failure (exit 0 or 1, never 2)
- the JSON payload reports a non-error final decision
- the wrapped Claude binary was invoked with ``--resume <planner_uuid>``
"""

from __future__ import annotations

import json
import os

import pytest

from tests.fixtures.docker import ContainerLike
from tests.integration.docker.conftest import run_claude_print, setup_real_claude

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_in,
    pytest.mark.slow,
]


@pytest.fixture(scope="module", autouse=True)
def _require_anthropic_api_key() -> None:
    """Fail loudly if API key is missing (never skip tests policy)."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.fail("ANTHROPIC_API_KEY not set. Add it to your environment/.env and re-run integration tests.")


def _install_passthrough_logging_wrapper(workspace: ContainerLike) -> None:
    """Wrap the real Claude binary so the test can assert the actual argv."""
    result = workspace.exec(
        """
        mv /usr/local/bin/claude /usr/local/bin/claude-upstream-real
        cat > /usr/local/bin/claude << 'SCRIPT'
#!/bin/bash
set -euo pipefail
echo "$(date -Iseconds) claude $*" >> /tmp/claude_invocations.log
exec /usr/local/bin/claude-upstream-real "$@"
SCRIPT
        chmod +x /usr/local/bin/claude
        > /tmp/claude_invocations.log
        """,
    )
    if result.returncode != 0:
        pytest.fail(f"Failed to install real Claude logging wrapper: {result.stderr}")


def _write_api_key_file(workspace: ContainerLike) -> None:
    """Persist the Anthropic API key for the follow-up supervisor command."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    result = workspace.exec(f"cat > /tmp/.anthropic_key << 'KEY_EOF'\n{api_key}\nKEY_EOF")
    if result.returncode != 0:
        pytest.fail(f"Failed to write API key: {result.stderr}")


class TestRealClaudeSupervisor:
    """Smoke coverage for the real ``claude -p --resume`` supervisor path."""

    def test_real_supervisor_resume_smoke(self, forge_workspace: ContainerLike) -> None:
        setup_real_claude(forge_workspace, session_name="planner")
        _install_passthrough_logging_wrapper(forge_workspace)

        prompt = (
            "Create a plan only. Do not write any files. "
            "The plan is: create src/demo.py containing only "
            "def greet(name: str) -> str that returns f'hello, {name}'. "
            "No other files. Show the plan and stop."
        )
        exit_code, stdout, stderr = run_claude_print(
            forge_workspace,
            prompt,
            session_name="planner",
            timeout=60,
        )

        planner_manifest = forge_workspace.read_json("/workspace/.forge/sessions/planner/forge.session.json")
        planner_resume_id = planner_manifest.get("confirmed", {}).get("claude_session_id")
        assert planner_resume_id is not None, (
            "Expected planner session to get a confirmed Claude session ID after "
            f"claude --print. exit={exit_code}, stdout={stdout[:300]!r}, stderr={stderr[:300]!r}"
        )

        file_result = forge_workspace.exec(
            """
            mkdir -p /workspace/src
            cat > /workspace/src/demo.py << 'PY'
def greet(name: str) -> str:
    return f"hello, {name}"
PY
            """,
        )
        assert file_result.returncode == 0, file_result.stderr

        clear_result = forge_workspace.exec("> /tmp/claude_invocations.log")
        assert clear_result.returncode == 0, clear_result.stderr

        _write_api_key_file(forge_workspace)
        try:
            result = forge_workspace.exec(
                "export ANTHROPIC_API_KEY=$(cat /tmp/.anthropic_key) && "
                f"cd /workspace && forge policy supervisor -f src/demo.py -r {planner_resume_id} --json",
                timeout=120,
            )
        finally:
            forge_workspace.exec("rm -f /tmp/.anthropic_key")

        payload = json.loads(result.stdout)
        assert result.returncode in (0, 1), result.stdout
        assert payload["final_decision"] in ("allow", "warn", "deny")
        assert payload["final_decision"] != "error"

        invocations = forge_workspace.read_file("/tmp/claude_invocations.log")
        assert "claude -p" in invocations
        assert f"--resume {planner_resume_id}" in invocations
