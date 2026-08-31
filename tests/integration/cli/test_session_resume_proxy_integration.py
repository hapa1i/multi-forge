"""Docker integration coverage for persisted proxy resume failures."""

from __future__ import annotations

from inspect import cleandoc

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


def test_bare_resume_refuses_dead_persisted_proxy_before_launch(
    mock_claude_workspace: ContainerLike,
) -> None:
    created = mock_claude_workspace.exec(
        "cd /workspace && forge session start dead-proxy-resume --no-proxy --no-launch"
    )
    assert created.returncode == 0, created.stderr
    script = cleandoc("""
        import json
        from pathlib import Path

        path = Path("/workspace/.forge/sessions/dead-proxy-resume/forge.session.json")
        data = json.loads(path.read_text())
        data["intent"]["proxy"] = {
            "template": "openrouter-gemini",
            "base_url": "http://127.0.0.1:65534",
        }
        data["confirmed"]["claude_session_id"] = "dead-proxy-conversation"
        data["confirmed"]["confirmed_by"] = "hook:SessionStart:startup"
        data["confirmed"]["started_with_proxy"] = {
            "base_url": "http://127.0.0.1:65534",
            "proxy_id": "missing-dead-proxy",
            "template": "openrouter-gemini",
            "port": 65534,
        }
        path.write_text(json.dumps(data))
        """)
    write_result = mock_claude_workspace.write_file("/tmp/forge-test-script.py", script)
    assert write_result.returncode == 0, write_result.stderr
    setup_result = mock_claude_workspace.exec("/forge/.venv/bin/python /tmp/forge-test-script.py")
    assert setup_result.returncode == 0, setup_result.stderr
    mock_claude_workspace.exec("> /tmp/claude_invocations.log")

    result = mock_claude_workspace.exec("cd /workspace && forge session resume dead-proxy-resume")

    assert result.returncode == 1
    assert "Persisted proxy route" in result.stderr
    assert "connection refused" in result.stderr
    assert "forge session resume dead-proxy-resume --proxy openrouter-gemini" in result.stderr
    assert "forge proxy start missing-dead-proxy" not in result.stderr
    assert mock_claude_workspace.read_file("/tmp/claude_invocations.log") == ""
    assert not mock_claude_workspace.file_exists("/workspace/.forge/artifacts/dead-proxy-resume/routing/events.jsonl")
