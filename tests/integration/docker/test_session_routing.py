"""Docker end-to-end coverage for managed-session routing boundaries."""

from __future__ import annotations

import json

import pytest
import yaml

from tests.fixtures.docker import ContainerLike

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


def _enable_claude_env_capture(workspace: ContainerLike) -> None:
    workspace.write_file(
        "/tmp/model-route-claude",
        """#!/bin/bash
if [ "${1:-}" = "--version" ]; then
    echo "99.99.99 (Claude Code)"
    exit 0
fi
echo "$(date -Iseconds) claude $*" >> /tmp/claude_invocations.log
env | sort | tee /tmp/model_route_latest_env.log > "/tmp/model_route_claude_env_$$.log"
exit 0
""",
    )
    result = workspace.exec("chmod +x /tmp/model-route-claude && ln -sf /tmp/model-route-claude /usr/local/bin/claude")
    assert result.returncode == 0, result.stderr


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


def _register_proxy(workspace: ContainerLike, *, proxy_id: str, port: int, native_passthrough: bool = False) -> str:
    """Register a healthy saved proxy without requiring upstream traffic."""
    template = "anthropic-passthrough" if native_passthrough else "openrouter-openai"
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
        yaml.safe_dump(
            {
                "proxy_format": 1,
                "template": template,
                "template_digest": "sha256:test",
                "provider": "litellm" if native_passthrough else "openrouter",
                "family": "anthropic" if native_passthrough else "openai",
                "proxy_endpoint": base_url,
                "port": port,
                "upstream_base_url": "https://api.anthropic.com" if native_passthrough else "https://openrouter.ai/api",
                "backend": "anthropic-passthrough" if native_passthrough else "openrouter",
                "wire_shape": "anthropic_passthrough" if native_passthrough else "openai_translated",
                "tiers": (
                    {"haiku": "claude-haiku-4-5", "sonnet": "claude-sonnet-5", "opus": "claude-opus-5"}
                    if native_passthrough
                    else {"haiku": "openai/gpt-5.4-mini", "sonnet": "openai/gpt-5.6-sol", "opus": "openai/gpt-5.6-sol"}
                ),
                "default_tier": "sonnet",
                **({} if native_passthrough else {"allow_non_zdr": False}),
            }
        ),
    )

    payload = json.dumps({"is_proxy": True, "template": template, "proxy": {"proxy_id": proxy_id}})
    server_path = "/tmp/model-route-health.py"
    pid_path = "/tmp/model-route-health.pid"
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
        f"nohup python3 {server_path} >/tmp/model-route-health.log 2>&1 & echo $! > {pid_path}; "
        f"for i in $(seq 1 20); do curl -sf {base_url}/ >/dev/null && exit 0; sleep 0.1; done; "
        "cat /tmp/model-route-health.log; exit 1",
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


def test_direct_parent_forks_to_proxy_model_and_bare_resume_reuses_route(
    forge_workspace: ContainerLike,
) -> None:
    """Managed launch intent, payload, child env, and bare replay agree across a route switch."""
    _enable_claude_env_capture(forge_workspace)
    direct = forge_workspace.exec("cd /workspace && forge session start model-route-parent --model claude-opus-4-8")
    assert direct.returncode == 0, direct.stdout + direct.stderr
    assert "Route: provider=direct" in direct.stderr
    parent = json.loads(forge_workspace.read_file("/workspace/.forge/sessions/model-route-parent/forge.session.json"))
    assert parent["intent"]["launch"]["model_route"] == {
        "requested_model": "claude-opus-4-8",
        "selected_tier": "opus",
        "kind": "direct",
        "source_id": None,
    }

    proxy_id = "model-route-openai"
    port = _allocate_container_port(forge_workspace)
    pid_path = _register_proxy(forge_workspace, proxy_id=proxy_id, port=port)
    try:
        forked = forge_workspace.exec(
            "cd /workspace && forge session fork model-route-parent --name model-route-child "
            f"--model gpt-5.6-sol --proxy {proxy_id}"
        )
        assert forked.returncode == 0, forked.stdout + forked.stderr
        assert (
            f"Route: provider=openrouter template=openrouter-openai proxy={proxy_id} "
            "tier=sonnet model=openai/gpt-5.6-sol billing_mode=unknown" in forked.stderr
        )

        child_path = "/workspace/.forge/sessions/model-route-child/forge.session.json"
        child = json.loads(forge_workspace.read_file(child_path))
        assert child["intent"]["proxy"] == {
            "template": "openrouter-openai",
            "base_url": f"http://127.0.0.1:{port}",
        }
        assert child["intent"]["launch"]["direct_model"] is None
        assert child["intent"]["launch"]["model_route"] == {
            "requested_model": "gpt-5.6-sol",
            "selected_tier": "sonnet",
            "kind": "proxy",
            "source_id": "openrouter",
        }

        journal = forge_workspace.read_file("/workspace/.forge/artifacts/model-route-child/routing/events.jsonl")
        payload = json.loads(journal.strip().splitlines()[-1])["payload"]
        assert payload["requested_model"] == "gpt-5.6-sol"
        assert payload["selected_tier"] == "sonnet"
        assert payload["selected_model"] == "openai/gpt-5.6-sol"
        assert payload["route"]["backend_id"] == "openrouter"
        assert payload["route"]["proxy_id"] == proxy_id

        env_capture = forge_workspace.exec("cat /tmp/model_route_claude_env_*.log")
        assert env_capture.returncode == 0, env_capture.stderr
        env_text = env_capture.stdout
        assert "ANTHROPIC_MODEL=sonnet" in env_text
        assert f"ANTHROPIC_BASE_URL=http://127.0.0.1:{port}" in env_text

        resumed = forge_workspace.exec("cd /workspace && forge session resume model-route-child")
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
        assert "Route:" not in resumed.stderr
        replayed = json.loads(forge_workspace.read_file(child_path))
        assert replayed["intent"]["launch"]["model_route"] == child["intent"]["launch"]["model_route"]
    finally:
        forge_workspace.exec(f"kill $(cat {pid_path}) 2>/dev/null || true")


def test_saved_passthrough_launches_preserve_native_model_selection(forge_workspace: ContainerLike) -> None:
    _enable_claude_env_capture(forge_workspace)
    proxy_id = "saved-native-models"
    pid_path = _register_proxy(
        forge_workspace, proxy_id=proxy_id, port=_allocate_container_port(forge_workspace), native_passthrough=True
    )
    config_path = f"$HOME/.forge/proxies/{proxy_id}/proxy.yaml"
    saved_config = forge_workspace.read_file(config_path)
    commands = [
        (f"claude start --proxy {proxy_id}", None),
        (f"session start native-default --proxy {proxy_id}", None),
        (f"session start native-pin --proxy {proxy_id} --model claude-sonnet-5", "claude-sonnet-5"),
        ("session resume native-pin", "claude-sonnet-5"),
        ("session fork native-pin --name native-child --model claude-sonnet-5", "claude-sonnet-5"),
        (f"session incognito --proxy {proxy_id} --model claude-sonnet-5", "claude-sonnet-5"),
    ]
    try:
        shown_proxy = forge_workspace.exec(f"forge proxy show {proxy_id} --json")
        assert shown_proxy.returncode == 0, shown_proxy.stderr
        for command, expected_pin in commands:
            launched = forge_workspace.exec(f"cd /workspace && forge {command}")
            assert launched.returncode == 0, launched.stdout + launched.stderr
            env = dict(
                line.split("=", 1)
                for line in forge_workspace.read_file("/tmp/model_route_latest_env.log").splitlines()
                if "=" in line
            )
            assert env.get("ANTHROPIC_DEFAULT_SONNET_MODEL") == expected_pin, command
            assert "ANTHROPIC_DEFAULT_OPUS_MODEL" not in env, command
            assert int(env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"]) > 200_000, command

        for name in ("native-pin", "native-child"):
            shown = forge_workspace.exec(f"cd /workspace && forge session model show {name} --json")
            assert shown.returncode == 0, shown.stderr
            assert json.loads(shown.stdout)["route_intent"]["requested_model"] == "claude-sonnet-5"
            history = forge_workspace.exec(f"cd /workspace && forge session model history {name} --json")
            assert history.returncode == 0, history.stderr
            events = json.loads(history.stdout)["events"]
            assert events
            assert all(event["payload"]["requested_model"] == "claude-sonnet-5" for event in events)
        assert forge_workspace.read_file(config_path) == saved_config
    finally:
        forge_workspace.exec(f"kill $(cat {pid_path}) 2>/dev/null || true")
