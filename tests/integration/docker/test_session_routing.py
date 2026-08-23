"""Docker end-to-end coverage for managed-session routing boundaries."""

from __future__ import annotations

import json

import pytest

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


def _allocate_container_port(workspace: ContainerLike) -> int:
    result = workspace.exec(
        'python3 -c \'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); '
        "print(s.getsockname()[1]); s.close()'"
    )
    assert result.returncode == 0, result.stderr
    return int(result.stdout.strip())


def _register_proxy_with_invalid_backend(workspace: ContainerLike, *, proxy_id: str, port: int) -> str:
    """Register a reachable proxy whose user-owned config has malformed identity."""
    template = "litellm-openai"
    base_url = f"http://127.0.0.1:{port}"
    workspace.mkdir(f"$HOME/.forge/proxies/{proxy_id}", parents=True)
    workspace.write_json(
        "$HOME/.forge/proxies/index.json",
        {
            "version": 1,
            "proxies": {
                proxy_id: {
                    "proxy_id": proxy_id,
                    "template": template,
                    "base_url": base_url,
                    "port": port,
                    "pid": None,
                    "status": "healthy",
                }
            },
        },
    )
    workspace.write_file(
        f"$HOME/.forge/proxies/{proxy_id}/proxy.yaml",
        f"""proxy_format: 1
template: {template}
template_digest: sha256:test
provider: litellm
proxy_endpoint: {base_url}
port: {port}
upstream_base_url: https://litellm.test.example.com
backend: OpenRouter
tiers:
  haiku: gpt-5.4-mini
  sonnet: gpt-5.5
  opus: gpt-5.5
default_tier: sonnet
""",
    )

    payload = json.dumps({"is_proxy": True, "template": template, "proxy": {"proxy_id": proxy_id}})
    server_path = "/tmp/malformed-backend-health.py"
    pid_path = "/tmp/malformed-backend-health.pid"
    workspace.write_file(
        server_path,
        f"""import http.server

PAYLOAD = {payload!r}.encode()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(PAYLOAD)

    def log_message(self, *args):
        pass


http.server.HTTPServer(("127.0.0.1", {port}), Handler).serve_forever()
""",
    )
    started = workspace.exec(
        f"nohup python3 {server_path} >/tmp/malformed-backend-health.log 2>&1 & echo $! > {pid_path}; "
        f"for i in $(seq 1 20); do curl -sf {base_url}/ >/dev/null && exit 0; sleep 0.1; done; "
        "cat /tmp/malformed-backend-health.log; exit 1",
        timeout=10,
    )
    assert started.returncode == 0, started.stdout + started.stderr
    return pid_path


def test_malformed_proxy_backend_stops_before_routing_or_child(forge_workspace: ContainerLike) -> None:
    enabled = forge_workspace.exec("forge extension enable --scope user --profile standard")
    assert enabled.returncode == 0, enabled.stderr
    proxy_id = "malformed-backend-e2e"
    pid_path = _register_proxy_with_invalid_backend(
        forge_workspace,
        proxy_id=proxy_id,
        port=_allocate_container_port(forge_workspace),
    )

    try:
        result = forge_workspace.exec(f"cd /workspace && forge session start malformed-route --proxy {proxy_id}")
    finally:
        forge_workspace.exec(f"kill $(cat {pid_path}) 2>/dev/null || true")

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert f"proxy.yaml for proxy '{proxy_id}' is invalid" in output
    assert "Invalid proxy.backend: 'OpenRouter'" in output
    assert "Traceback" not in output
    assert forge_workspace.read_file("/tmp/claude_invocations.log") == ""
    assert not forge_workspace.file_exists("/workspace/.forge/artifacts/malformed-route/routing/events.jsonl")
