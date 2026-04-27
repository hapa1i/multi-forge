"""Real-Claude worker validation for headless ``claude -p --bare`` flows (panel workflow)."""

from __future__ import annotations

import json
import os

import pytest

from forge.core.models.catalog import get_default_model
from tests.fixtures.docker import ContainerLike
from tests.integration.docker.conftest import setup_real_claude

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_in,
    pytest.mark.slow,
]


@pytest.fixture(scope="module", autouse=True)
def _require_anthropic_api_key() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.fail("ANTHROPIC_API_KEY not set. Add it to your environment/.env and re-run integration tests.")


def _install_passthrough_logging_wrapper(workspace: ContainerLike) -> None:
    """Wrap the real Claude binary so tests can assert worker argv without mocking execution."""
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


class TestRealClaudeWorkers:
    """Exercise a real ``forge workflow panel`` worker with ``claude -p --bare``."""

    def test_multi_review_uses_real_bare_worker(self, forge_workspace: ContainerLike) -> None:
        setup_real_claude(forge_workspace, session_name="real-worker")
        _install_passthrough_logging_wrapper(forge_workspace)

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        forge_workspace.exec(f"cat > /tmp/.anthropic_key << 'KEY_EOF'\n{api_key}\nKEY_EOF")
        try:
            result = forge_workspace.exec(
                "export ANTHROPIC_API_KEY=$(cat /tmp/.anthropic_key) && "
                "cd /workspace && forge workflow panel "
                "--models claude-opus "
                "-p 'Reply with a single short greeting.' "
                "--timeout 60 --json",
                timeout=90,
            )
        finally:
            forge_workspace.exec("rm -f /tmp/.anthropic_key")

        assert result.returncode == 0, result.stderr

        payload = json.loads(result.stdout)
        assert payload["successful"] == 1
        response = payload["results"]["claude-opus"]["response"]
        assert isinstance(response, str) and response.strip()

        invocations = forge_workspace.read_file("/tmp/claude_invocations.log")
        assert "claude -p --bare" in invocations
        anthropic_opus = get_default_model("anthropic", "opus")
        assert f"--model {anthropic_opus}" in invocations
