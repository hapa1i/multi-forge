"""Real-Claude worker validation for headless ``claude -p --bare`` workflow flows."""

from __future__ import annotations

import json
import os

import pytest

from forge.core.models.catalog import get_default_model
from tests.fixtures.docker import ContainerLike
from tests.integration.docker.conftest import (
    read_container_usage_events,
    setup_real_claude,
)

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
        if [ ! -f /usr/local/bin/claude-upstream-real ]; then
            mv /usr/local/bin/claude /usr/local/bin/claude-upstream-real
        fi
cat > /usr/local/bin/claude << 'SCRIPT'
#!/bin/bash
set -euo pipefail
pid="$$"
echo "$(date -Iseconds) claude $*" >> /tmp/claude_invocations.log
env | sort > "/tmp/claude_env_${pid}.log"
exec /usr/local/bin/claude-upstream-real "$@"
SCRIPT
        chmod +x /usr/local/bin/claude
        > /tmp/claude_invocations.log
        rm -f /tmp/claude_env_*.log
        """,
    )
    if result.returncode != 0:
        pytest.fail(f"Failed to install real Claude logging wrapper: {result.stderr}")


def _restore_passthrough_logging_wrapper(workspace: ContainerLike) -> None:
    """Restore the real Claude binary after a passthrough wrapper test."""
    result = workspace.exec("""
        if [ -f /usr/local/bin/claude-upstream-real ]; then
            mv /usr/local/bin/claude-upstream-real /usr/local/bin/claude
        fi
        """)
    if result.returncode != 0:
        pytest.fail(f"Failed to restore real Claude logging wrapper: {result.stderr}")


class TestRealClaudeWorkers:
    """Exercise real workflow workers through ``claude -p --bare``."""

    def test_multi_review_uses_real_bare_worker(self, forge_workspace: ContainerLike) -> None:
        setup_real_claude(forge_workspace, session_name="real-worker")
        _install_passthrough_logging_wrapper(forge_workspace)
        forge_workspace.exec("rm -rf ~/.forge/usage")

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        forge_workspace.exec(f"cat > /tmp/.anthropic_key << 'KEY_EOF'\n{api_key}\nKEY_EOF")
        try:
            result = forge_workspace.exec(
                "export ANTHROPIC_API_KEY=$(cat /tmp/.anthropic_key) && "
                "export FORGE_RUN_ID=run_real_worker_panel FORGE_ROOT_RUN_ID=run_real_worker_panel && "
                "cd /workspace && forge workflow panel "
                "--models claude-opus "
                "-p 'Reply with a single short greeting.' "
                "--timeout 60 --json",
                timeout=90,
            )
        finally:
            forge_workspace.exec("rm -f /tmp/.anthropic_key")
            _restore_passthrough_logging_wrapper(forge_workspace)

        assert result.returncode == 0, result.stderr

        payload = json.loads(result.stdout)
        assert payload["successful"] == 1
        response = payload["results"]["claude-opus"]["response"]
        assert isinstance(response, str) and response.strip()

        invocations = forge_workspace.read_file("/tmp/claude_invocations.log")
        assert "claude -p --bare" in invocations
        assert "--model" not in invocations

        anthropic_opus = get_default_model("anthropic", "opus")
        env_path = forge_workspace.exec("ls -1 /tmp/claude_env_*.log | head -n 1").stdout.strip()
        assert env_path
        env_text = forge_workspace.read_file(env_path)
        assert "ANTHROPIC_MODEL=opus" in env_text
        assert f"ANTHROPIC_DEFAULT_OPUS_MODEL={anthropic_opus}" in env_text

        usage_events = read_container_usage_events(forge_workspace, command="panel")
        worker_events = [event for event in usage_events if event["attribution_granularity"] == "worker"]
        assert len(worker_events) == 1
        worker_event = worker_events[0]
        assert worker_event["runtime"] == "claude_code"
        assert worker_event["status"] == "success"
        assert worker_event["parent_run_id"] == "run_real_worker_panel"
        assert worker_event["root_run_id"] == "run_real_worker_panel"
        assert worker_event["run_id"].startswith("run_")
        assert worker_event["run_id"] != "run_real_worker_panel"
        assert worker_event["provider"] == "direct"
        assert worker_event["model"] == anthropic_opus
        assert worker_event["proxy_id"] is None
        # Phase 5: a direct (API-key) worker self-reports cost via --output-format json
        # (5a verdict: direct API key -> COST-REPORTED + USAGE-REPORTED), so the leaf is
        # runtime_native / claude_code, not the pre-5 unattributed. A PROXIED worker would
        # stay unattributed here (the verb aggregate owns proxied cost) -- this is direct.
        assert worker_event["measurement_source"] == "runtime_native"
        assert worker_event["reporter"] == "claude_code"
        assert worker_event["confidence"] == "reported"
        assert worker_event["cost_micro_usd"] is not None
        assert worker_event["input_tokens"] is not None
        assert worker_event["source_refs"] is None

        verb_events = [event for event in usage_events if event["attribution_granularity"] == "verb"]
        assert len(verb_events) == 1
        verb_event = verb_events[0]
        assert verb_event["run_id"] == "run_real_worker_panel"
        assert verb_event["root_run_id"] == "run_real_worker_panel"
        assert verb_event["status"] == "success"

    def test_debate_uses_real_bare_worker(self, forge_workspace: ContainerLike) -> None:
        setup_real_claude(forge_workspace, session_name="real-debate-worker")
        _install_passthrough_logging_wrapper(forge_workspace)

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        forge_workspace.exec(f"cat > /tmp/.anthropic_key << 'KEY_EOF'\n{api_key}\nKEY_EOF")
        try:
            result = forge_workspace.exec(
                "export ANTHROPIC_API_KEY=$(cat /tmp/.anthropic_key) && "
                "cd /workspace && forge workflow debate "
                "'Should this smoke test prefer a tiny Python script? Answer briefly.' "
                "--models claude-opus "
                "--timeout 60 --json",
                timeout=90,
            )
        finally:
            forge_workspace.exec("rm -f /tmp/.anthropic_key")
            _restore_passthrough_logging_wrapper(forge_workspace)

        assert result.returncode == 0, result.stderr

        payload = json.loads(result.stdout)
        assert payload["successful"] == 1
        assert payload["failed"] == 0
        response = next(iter(payload["results"].values()))["response"]
        assert isinstance(response, str) and response.strip()

        invocations = forge_workspace.read_file("/tmp/claude_invocations.log")
        assert "claude -p --bare" in invocations
        assert "--model" not in invocations

        anthropic_opus = get_default_model("anthropic", "opus")
        env_path = forge_workspace.exec("ls -1 /tmp/claude_env_*.log | head -n 1").stdout.strip()
        assert env_path
        env_text = forge_workspace.read_file(env_path)
        assert "ANTHROPIC_MODEL=opus" in env_text
        assert f"ANTHROPIC_DEFAULT_OPUS_MODEL={anthropic_opus}" in env_text
