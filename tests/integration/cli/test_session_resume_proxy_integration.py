"""Docker integration coverage for persisted proxy resume failures."""

from __future__ import annotations

import json
from inspect import cleandoc

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


@pytest.mark.parametrize("resume_mode", ["native", "transfer"])
def test_fresh_direct_resume_after_previous_proxy_launch(
    mock_claude_workspace: ContainerLike, resume_mode: str
) -> None:
    created = mock_claude_workspace.exec("cd /workspace && forge session start parent --no-proxy --no-launch")
    assert created.returncode == 0, created.stderr
    script = cleandoc("""
        from forge.session import SessionStore
        from forge.session.models import ProxyIntent, StartedWithProxy

        store = SessionStore('/workspace', 'parent')
        def confirm_previous_launch(state):
            state.intent.proxy = ProxyIntent('litellm-openai', 'http://localhost:8084')
            state.confirmed.claude_session_id = 'parent-conversation'
            state.confirmed.confirmed_by = 'hook:SessionStart:startup'
            state.confirmed.started_with_proxy = StartedWithProxy(
                template='litellm-openai', base_url='http://localhost:8084', proxy_id='old-proxy'
            )
        store.update(timeout_s=5.0, mutate=confirm_previous_launch)
        """)
    written = mock_claude_workspace.write_file("/tmp/confirm-proxy.py", script)
    assert written.returncode == 0, written.stderr
    seeded = mock_claude_workspace.exec("/forge/.venv/bin/python /tmp/confirm-proxy.py")
    assert seeded.returncode == 0, seeded.stderr
    first = mock_claude_workspace.exec("cd /workspace && forge session resume parent --no-proxy")
    assert first.returncode == 0, first.stderr
    parent_path = "/workspace/.forge/sessions/parent/forge.session.json"
    before = mock_claude_workspace.read_file(parent_path)
    assert json.loads(before)["intent"]["proxy"] is None

    result = mock_claude_workspace.exec(
        "cd /workspace && forge session resume parent --fresh --no-proxy --child-name child "
        f"--resume-mode {resume_mode}"
    )

    assert result.returncode == 0, result.stderr
    child = json.loads(mock_claude_workspace.read_file("/workspace/.forge/sessions/child/forge.session.json"))
    assert child["intent"]["proxy"] is None
    assert child["confirmed"]["derivation"]["inherited_proxy"] == "litellm-openai"
    assert mock_claude_workspace.read_file(parent_path) == before
    assert len(mock_claude_workspace.read_file("/tmp/claude_invocations.log").splitlines()) == 2


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
