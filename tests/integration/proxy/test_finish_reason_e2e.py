"""Hermetic Vertex cutoff responses retain max_tokens through the translated HTTP proxy."""

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

from tests.fixtures.proxy import allocate_ephemeral_port, kill_process
from tests.integration.proxy.conftest import FakeOpenAIUpstream, _start_proxy_subprocess

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def cutoff_proxy(
    module_forge_home: Path, tmp_path_factory: pytest.TempPathFactory
) -> Generator[tuple[str, FakeOpenAIUpstream], None, None]:
    requests: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            tool_case = body["messages"][-1]["content"] == "partial tool"
            message: dict[str, Any] = {"content": "unfinished answer"}
            if tool_case:
                message = {
                    "tool_calls": [
                        {
                            "id": "call_cutoff",
                            "type": "function",
                            "function": {"name": "Read", "arguments": '{"file_path": "'},
                            **({"index": 0} if body.get("stream") else {}),
                        }
                    ]
                }
            response = {"id": "cutoff", "model": body["model"], "created": 0}
            usage = {
                "prompt_tokens": 4,
                "completion_tokens": body["max_tokens"],
                "total_tokens": body["max_tokens"] + 4,
            }
            if body.get("stream"):
                response.update(object="chat.completion.chunk")
                chunks = [
                    {**response, "choices": [{"index": 0, "delta": message}]},
                    {**response, "choices": [{"index": 0, "delta": {}, "finish_reason": "length"}]},
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
                            {"index": 0, "message": {"role": "assistant", **message}, "finish_reason": "length"}
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
    env = {**os.environ, "FORGE_HOME": str(module_forge_home), "PYTHON_DOTENV_DISABLED": "1"}
    env.update(LITELLM_BASE_URL=upstream.base_url, LITELLM_API_KEY="test-key")
    port = allocate_ephemeral_port()
    proc = None
    try:
        proc = _start_proxy_subprocess(
            template="litellm-gemini",
            port=port,
            forge_home=module_forge_home,
            env=env,
            cwd=tmp_path_factory.mktemp("cutoff_proxy"),
        )
        yield f"http://127.0.0.1:{port}", upstream
    finally:
        if proc is not None:
            kill_process(proc.pid)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("partial_tool", [False, True])
def test_vertex_cutoff_reaches_anthropic_client(
    cutoff_proxy: tuple[str, FakeOpenAIUpstream], stream: bool, partial_tool: bool
) -> None:
    base_url, upstream = cutoff_proxy
    upstream.requests.clear()
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{base_url}/v1/messages",
            headers={"x-api-key": "test"},
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 64_000,
                "stream": stream,
                "messages": [{"role": "user", "content": "partial tool" if partial_tool else "partial text"}],
                "tools": [{"name": "Read", "input_schema": {"type": "object", "properties": {}}}],
            },
        )
    assert response.status_code == 200, response.text[:500]
    expected_tokens = 64_000 if stream else 32_768
    if stream:
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        final = next(event for event in events if event["type"] == "message_delta" and "stop_reason" in event["delta"])
        assert final["delta"]["stop_reason"] == "max_tokens"
        assert final["usage"]["output_tokens"] == expected_tokens
        assert events[-1]["type"] == "message_stop"
    else:
        body = response.json()
        assert body["stop_reason"] == "max_tokens"
        assert body["usage"]["output_tokens"] == expected_tokens
        if partial_tool:
            assert any(block["type"] == "tool_use" for block in body["content"])
    assert len(upstream.requests) == 1
    assert upstream.requests[0]["model"] == "vertex_ai/gemini-4-argon"
    assert upstream.requests[0]["max_tokens"] == expected_tokens
