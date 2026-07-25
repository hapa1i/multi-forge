"""Deterministic Docker wire coverage for team-supervisor hooks."""

from __future__ import annotations

import json
from typing import Generator

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]

_SESSION_NAME = "team-wire"
_RESUME_ID = "00000000-0000-4000-8000-000000000042"


def _allocate_container_port(workspace: ContainerLike) -> int:
    result = workspace.exec(
        'python3 -c \'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); '
        "print(s.getsockname()[1]); s.close()'"
    )
    assert result.returncode == 0, result.stderr
    return int(result.stdout.strip())


def _start_tagger_stub(workspace: ContainerLike, port: int) -> None:
    """Start a minimal OpenAI-compatible chat-completions endpoint."""
    workspace.write_file(
        "/tmp/team-tagger-stub.py",
        f"""import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RESPONSE = json.dumps({{
    "id": "chatcmpl-team-hook",
    "object": "chat.completion",
    "created": 0,
    "model": "gemini/team-hook-stub",
    "choices": [{{
        "index": 0,
        "message": {{"role": "assistant", "content": "needs-review"}},
        "finish_reason": "stop",
    }}],
    "usage": {{"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}},
}}).encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        with Path("/tmp/team-tagger-requests.log").open("a") as log:
            log.write(self.path + "\\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(RESPONSE)))
        self.end_headers()
        self.wfile.write(RESPONSE)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", {port}), Handler).serve_forever()
""",
    )
    result = workspace.exec(
        "rm -f /tmp/team-tagger-requests.log && "
        "nohup python3 /tmp/team-tagger-stub.py > /tmp/team-tagger-stub.log 2>&1 & "
        "echo $! > /tmp/team-tagger-stub.pid && "
        f"for i in $(seq 1 30); do curl -sf http://127.0.0.1:{port}/ >/dev/null && exit 0; sleep 0.1; done; "
        "cat /tmp/team-tagger-stub.log; exit 1",
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _install_claude_harness(workspace: ContainerLike) -> None:
    workspace.write_file(
        "/usr/local/bin/claude-mock",
        """#!/bin/bash
set -euo pipefail

if [ "${1:-}" = "--version" ]; then
    echo "99.99.99 (Claude Code)"
    exit 0
fi

echo "claude $*" >> /tmp/claude_invocations.log
case "${FORGE_TEST_TEAM_MODE:-}" in
    low)
        echo '{"verdict":"divergent","confidence":0.3,"feedback":"low-confidence review warning"}'
        ;;
    high)
        echo '{"verdict":"divergent","confidence":0.95,"feedback":"high-confidence review block"}'
        ;;
    *)
        echo "unknown FORGE_TEST_TEAM_MODE=${FORGE_TEST_TEAM_MODE:-}" >&2
        exit 3
        ;;
esac
""",
    )
    result = workspace.exec("chmod +x /usr/local/bin/claude-mock")
    assert result.returncode == 0, result.stderr


def _configure_team_session(workspace: ContainerLike) -> None:
    result = workspace.exec(f"cd /workspace && forge session start {_SESSION_NAME} --no-proxy --no-launch")
    assert result.returncode == 0, result.stdout + result.stderr

    manifest_path = f"/workspace/.forge/sessions/{_SESSION_NAME}/forge.session.json"
    manifest = workspace.read_json(manifest_path)
    manifest["intent"]["policy"] = {
        "enabled": True,
        "fail_mode": "open",
        "team_supervisor": {
            "enabled": True,
            "tagger_model": "gemini/team-hook-stub",
            "resume_id": _RESUME_ID,
            "direct": True,
            "timeout_seconds": 10,
            "throttle_seconds": 0,
            "max_blocks_per_task": 3,
        },
    }
    write_result = workspace.write_json(manifest_path, manifest)
    assert write_result.returncode == 0, write_result.stderr
    workspace.exec("> /tmp/claude_invocations.log")


@pytest.fixture
def team_hook_workspace(
    forge_workspace: ContainerLike,
) -> Generator[tuple[ContainerLike, str], None, None]:
    port = _allocate_container_port(forge_workspace)
    _start_tagger_stub(forge_workspace, port)
    _install_claude_harness(forge_workspace)
    _configure_team_session(forge_workspace)

    yield forge_workspace, f"http://127.0.0.1:{port}/v1"

    forge_workspace.exec(
        "if [ -f /tmp/team-tagger-stub.pid ]; then kill $(cat /tmp/team-tagger-stub.pid) 2>/dev/null || true; fi"
    )


def _invoke_team_hook(
    workspace: ContainerLike,
    *,
    base_url: str,
    command: str,
    mode: str,
    payload: dict[str, str],
) -> tuple[int, str, str]:
    payload_json = json.dumps(payload)
    result = workspace.exec(
        f"cd /workspace && printf '%s' '{payload_json}' | "
        f"FORGE_SESSION={_SESSION_NAME} LITELLM_LOCAL_BASE_URL={base_url} "
        f"FORGE_TEST_TEAM_MODE={mode} forge hook {command}"
    )
    return result.returncode, result.stdout, result.stderr


def test_team_hooks_warn_then_block_on_the_claude_wire(
    team_hook_workspace: tuple[ContainerLike, str],
) -> None:
    workspace, base_url = team_hook_workspace

    idle_exit, idle_stdout, idle_stderr = _invoke_team_hook(
        workspace,
        base_url=base_url,
        command="teammate-idle",
        mode="low",
        payload={
            "session_id": "team-idle-low",
            "hook_event_name": "TeammateIdle",
            "teammate_name": "executor-low",
            "team_name": "wire-team",
        },
    )
    task_exit, task_stdout, task_stderr = _invoke_team_hook(
        workspace,
        base_url=base_url,
        command="task-completed",
        mode="high",
        payload={
            "session_id": "team-task-high",
            "hook_event_name": "TaskCompleted",
            "teammate_name": "executor-high",
            "team_name": "wire-team",
            "task_id": "task-high",
            "task_subject": "Finish the integration fixture",
        },
    )

    assert idle_exit == 0
    assert idle_stdout == ""
    assert "low-confidence review warning" in idle_stderr
    assert task_exit == 2
    assert task_stdout == ""
    assert "high-confidence review block" in task_stderr

    tagger_requests = workspace.read_file("/tmp/team-tagger-requests.log")
    assert tagger_requests.splitlines() == ["/v1/chat/completions", "/v1/chat/completions"]
    invocations = workspace.read_file("/tmp/claude_invocations.log")
    assert invocations.count(f"--resume {_RESUME_ID}") == 2
    assert "--model opus" not in invocations
