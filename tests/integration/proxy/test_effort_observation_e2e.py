"""A real proxy reports launch effort from the request received by a local stub upstream."""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
import pytest
import yaml

from forge.core.run_id import FORGE_LAUNCH_HEADER, mint_run_id
from tests.fixtures.proxy import allocate_ephemeral_port, kill_process
from tests.integration.proxy.conftest import (
    _register_proxy_for_test,
    _start_proxy_subprocess,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", params=["argon", "openrouter", "gpt5-tools", "passthrough"])
def effort_proxy(request, tmp_path_factory: pytest.TempPathFactory):
    route = request.param
    requests: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"body": body, "headers": dict(self.headers.items())})
            model = body["model"]
            if self.path == "/v1/messages":
                result = {
                    "id": "msg_stub",
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
                events: list[dict[str, Any]] = [
                    {"type": "message_start", "message": {**result, "content": []}},
                    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 1}},
                    {"type": "message_stop"},
                ]
                streamed = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
            elif self.path == "/v1/chat/completions":
                result = {
                    "id": "chatcmpl-stub",
                    "object": "chat.completion",
                    "created": 0,
                    "model": model,
                    "choices": [
                        {"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
                events = [
                    {
                        **result,
                        "object": "chat.completion.chunk",
                        "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": None}],
                    },
                    {
                        **result,
                        "object": "chat.completion.chunk",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    },
                ]
                streamed = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
            else:
                self.send_error(404)
                return
            payload = streamed.encode() if body.get("stream") else json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if body.get("stream") else "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Forge-Launch", "must-not-return")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            return

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    home = tmp_path_factory.mktemp(f"effort-{route}")
    template = {
        "argon": "litellm-gemini",
        "openrouter": "openrouter-openai",
        "gpt5-tools": "litellm-openai",
        "passthrough": "anthropic-passthrough",
    }[route]
    mapped = {
        "argon": "vertex_ai/gemini-4-argon",
        "openrouter": "openai/gpt-6-astra",
        "gpt5-tools": "openai/gpt-5",
        "passthrough": "claude-opus-5-5",
    }[route]
    port = allocate_ephemeral_port()
    proxy_id = f"effort-{route}"
    upstream_url = f"http://127.0.0.1:{upstream.server_port}" + ("" if route == "passthrough" else "/v1")
    process = None
    try:
        _register_proxy_for_test(
            proxy_id=proxy_id,
            template=template,
            port=port,
            forge_home=home,
            upstream_base_url=upstream_url,
        )
        config_path = home / "proxies" / proxy_id / "proxy.yaml"
        config = yaml.safe_load(config_path.read_text())
        config["tiers"] = dict.fromkeys(("haiku", "sonnet", "opus"), mapped)
        config["tier_overrides"] = {tier: {"reasoning_effort": "high"} for tier in ("haiku", "sonnet", "opus")}
        if route == "passthrough":
            config["intercept"] = {"mode": "override"}
        config_path.write_text(yaml.safe_dump(config))
        process = _start_proxy_subprocess(
            template=template,
            proxy_id=proxy_id,
            port=port,
            forge_home=home,
            cwd=home,
            env={
                **os.environ,
                "FORGE_HOME": str(home),
                "PYTHON_DOTENV_DISABLED": "1",
                "LITELLM_API_KEY": "fixture-key",
                "OPENROUTER_API_KEY": "fixture-key",
                "ANTHROPIC_API_KEY": "fixture-key",
                "LITELLM_BASE_URL": upstream_url,
                "OPENROUTER_BASE_URL": upstream_url,
            },
        )
        yield f"http://127.0.0.1:{port}", route, requests
    finally:
        if process is not None:
            kill_process(process.pid)
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("stream", [False, True])
def test_reported_effort_matches_captured_outbound_request(effort_proxy, stream: bool) -> None:
    base_url, route, requests = effort_proxy
    requests.clear()
    launch = mint_run_id()
    requested = "low" if route == "passthrough" else "max"
    client_model = "claude-opus-4-6" if route == "passthrough" else "gemini-4-argon"
    with httpx.Client(base_url=base_url, timeout=30) as client:
        assert client.get("/", params={"forge_launch": launch}).json()["runtime"]["effort"] == {}
        response = client.post(
            "/v1/messages",
            headers={FORGE_LAUNCH_HEADER: launch, "X-Forge-Model-Tier": "opus", "X-Forge-Effort-Source": "client"},
            json={
                "model": client_model,
                "max_tokens": 64,
                "stream": stream,
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": requested},
                "messages": [{"role": "user", "content": "hello"}],
                "tools": [{"name": "Read", "input_schema": {"type": "object", "properties": {}}}],
            },
        )
        assert response.status_code == 200, response.text[:1000]
        assert "x-forge-launch" not in response.headers
        observation = client.get("/", params={"forge_launch": launch}).json()["runtime"]["effort"]["opus"]
        assert "effort" not in client.get("/").json()["runtime"]
        assert "effort" not in client.get("/", params={"forge_launch": "bad"}).json()["runtime"]
        assert client.get("/", params={"forge_launch": mint_run_id()}).json()["runtime"]["effort"] == {}

    assert len(requests) == 1
    upstream_body = requests[0]["body"]
    assert not any(name.lower().startswith("x-forge-") for name in requests[0]["headers"])
    assert observation["mapped_model"] == upstream_body["model"]
    assert observation["client_model"] == client_model
    assert observation["requested"] == requested
    assert observation["opt_in"] is True
    if route == "gpt5-tools":
        assert "reasoning_effort" not in upstream_body
        assert observation["wire"] == "dropped"
        assert observation["applied"] is None
        assert observation["resolved"] == "high"
        assert observation["note"]
    else:
        wire = {
            "argon": "thinkingConfig.thinkingLevel",
            "openrouter": "reasoning.effort",
            "passthrough": "output_config.effort",
        }[route]
        value = upstream_body
        for key in wire.split("."):
            value = value[key]
        assert observation["wire"] == wire
        assert observation["applied"] == value
        assert observation["source"] == ("override" if route == "passthrough" else "client")
    assert observation["tier_source"] == ("request" if route == "passthrough" else "forge.model_tier_header")
