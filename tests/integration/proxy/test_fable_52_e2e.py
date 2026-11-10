"""Exercise Fable 5.2 routing and wire contracts against isolated local upstreams."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from tests.fixtures.proxy import allocate_ephemeral_port, kill_process
from tests.integration.proxy.conftest import (
    FakeAnthropicUpstream,
    FakeOpenAIUpstream,
    _register_proxy_for_test,
    _start_proxy_subprocess,
)

pytestmark = pytest.mark.integration

_PROVIDER_CREDENTIALS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
    }
)


@pytest.fixture(
    scope="module",
    params=[
        ("litellm-anthropic-local", False, "anthropic/claude-fable-5-2"),
        ("openrouter-anthropic", True, "anthropic/claude-fable-5.2"),
        ("openrouter-anthropic", False, "anthropic/claude-opus-5.5"),
    ],
    ids=["litellm", "openrouter-fable", "openrouter-zdr"],
)
def fable_proxy(
    request: pytest.FixtureRequest, module_forge_home: Path, tmp_path_factory: pytest.TempPathFactory
) -> Generator[tuple[str, FakeOpenAIUpstream, str], None, None]:
    template, allow_non_zdr, expected_model = request.param
    requests: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            response = {"id": "fable-test", "model": body["model"], "created": 0}
            usage = {"prompt_tokens": 20, "completion_tokens": 2, "total_tokens": 22}
            if body.get("stream"):
                response["object"] = "chat.completion.chunk"
                chunks = [
                    {**response, "choices": [{"index": 0, "delta": {"role": "assistant", "content": "OK"}}]},
                    {**response, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                    {**response, "choices": [], "usage": usage},
                ]
                encoded = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
                content_type = "text/event-stream"
            else:
                encoded = json.dumps(
                    {
                        **response,
                        "object": "chat.completion",
                        "choices": [
                            {"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}
                        ],
                        "usage": usage,
                    }
                ).encode()
                content_type = "application/json"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    upstream = FakeOpenAIUpstream(base_url=f"http://127.0.0.1:{server.server_port}/v1", requests=requests)
    port = allocate_ephemeral_port()
    proxy_id = f"fable-test-{port}"
    proc = None
    try:
        _register_proxy_for_test(
            proxy_id=proxy_id,
            template=template,
            port=port,
            forge_home=module_forge_home,
            upstream_base_url=upstream.base_url,
        )
        if allow_non_zdr:
            path = module_forge_home / "proxies" / proxy_id / "proxy.yaml"
            snapshot = yaml.safe_load(path.read_text())
            snapshot["allow_non_zdr"] = True
            path.write_text(yaml.safe_dump(snapshot))
        # Withhold real provider keys so a broken upstream override cannot reach a paid endpoint.
        env = {key: value for key, value in os.environ.items() if key not in _PROVIDER_CREDENTIALS}
        env.update(
            {
                "FORGE_HOME": str(module_forge_home),
                "PYTHON_DOTENV_DISABLED": "1",
                "LITELLM_LOCAL_BASE_URL": upstream.base_url,
                "OPENROUTER_BASE_URL": upstream.base_url,
                "OPENROUTER_API_KEY": "test-key",
            }
        )
        proc = _start_proxy_subprocess(
            template=template,
            port=port,
            forge_home=module_forge_home,
            env=env,
            cwd=tmp_path_factory.mktemp("fable_proxy"),
            proxy_id=proxy_id,
        )
        yield f"http://127.0.0.1:{port}", upstream, expected_model
    finally:
        if proc is not None:
            kill_process(proc.pid)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("stream", [False, True])
def test_fable_alias_routes_with_supported_controls(
    fable_proxy: tuple[str, FakeOpenAIUpstream, str], stream: bool
) -> None:
    url, upstream, model = fable_proxy
    upstream.requests.clear()
    response = httpx.post(
        f"{url}/v1/messages",
        json={
            "model": "claude-fable",
            "max_tokens": 128,
            "stream": stream,
            "reasoning_effort": "max",
            "temperature": 0.7,
            "top_p": 0.9,
            "top_k": 40,
            "messages": [{"role": "user", "content": "Reply OK."}],
            "tools": [{"name": "ping", "input_schema": {"type": "object", "properties": {}}}],
            "tool_choice": {"type": "auto"},
        },
        timeout=30,
    )

    assert response.status_code == 200, response.text[:500]
    assert response.headers["X-Resolved-Model"] == model
    assert response.headers["X-Resolved-Tier"] == "opus"
    assert len(upstream.requests) == 1
    sent = upstream.requests[0]
    assert sent["model"] == model
    assert not {"temperature", "top_p", "top_k"}.intersection(sent)
    assert sent.get("reasoning_effort", sent.get("reasoning", {}).get("effort")) == "max"
    assert sent["tools"][0]["function"]["name"] == "ping"
    assert sent["tool_choice"] == "auto"
    if model == "anthropic/claude-opus-5.5":
        assert sent["provider"]["zdr"] is True
    if stream:
        assert "event: message_stop" in response.text
        assert "event: error" not in response.text
    else:
        assert response.json()["content"][0]["text"] == "OK"
        assert response.json()["usage"]["output_tokens"] == 2


@pytest.mark.parametrize("choice", [{"type": "any"}, {"type": "tool", "name": "ping"}])
def test_fable_forced_tools_refuse_before_upstream(
    fable_proxy: tuple[str, FakeOpenAIUpstream, str], choice: dict
) -> None:
    url, upstream, _ = fable_proxy
    upstream.requests.clear()
    response = httpx.post(
        f"{url}/v1/messages",
        json={
            "model": "fable",
            "max_tokens": 128,
            "messages": [{"role": "user", "content": "Ping"}],
            "tools": [{"name": "ping", "input_schema": {"type": "object", "properties": {}}}],
            "tool_choice": choice,
        },
        timeout=30,
    )

    assert response.status_code == 400, response.text[:500]
    assert "tool_choice" in response.json()["detail"]["message"]
    assert upstream.requests == []


def test_fable_passthrough_preserves_signed_prefix(
    proxy_server_fake_anthropic_passthrough: tuple[str, FakeAnthropicUpstream],
) -> None:
    url, upstream = proxy_server_fake_anthropic_passthrough
    upstream.requests.clear()
    body = {
        "model": "claude-fable-5-2",
        "max_tokens": 128,
        "system": "Use the ping tool.",
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
        "tools": [{"name": "ping", "input_schema": {"type": "object", "properties": {}}}],
        "messages": [
            {"role": "user", "content": "Ping"},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "", "signature": "opaque-fable-signature"},
                    {"type": "tool_use", "id": "tool_1", "name": "ping", "input": {}},
                ],
            },
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tool_1", "content": "OK"}]},
        ],
    }
    response = httpx.post(f"{url}/v1/messages", json=body, timeout=30)

    assert response.status_code == 529
    assert len(upstream.requests) == 1
    assert upstream.requests[0]["body"] == body
    assert response.content == upstream.response_body
