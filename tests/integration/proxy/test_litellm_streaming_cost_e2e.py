"""Pinned LiteLLM streamed usage reaches proxy telemetry and caps without paid calls."""

from __future__ import annotations

import copy
import json
import os
import socket
import threading
import time
from collections.abc import Generator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.paths import get_forge_home
from forge.core.telemetry.downstream import read_downstream_records
from tests.fixtures.proxy import allocate_ephemeral_port, kill_process
from tests.integration.proxy.conftest import (
    RegisteredProxyServer,
    _register_proxy_for_test,
    _start_proxy_subprocess,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def pinned_gateway_chunks() -> list[dict[str, Any]]:
    def forbid_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Pinned LiteLLM stream fixture must not contact a provider")

    with pytest.MonkeyPatch.context() as isolated:
        isolated.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
        isolated.setattr(socket.socket, "connect", forbid_network)
        import litellm

        response = litellm.ModelResponse(
            model="gemini/gemini-3.8-flash",
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            usage={"prompt_tokens": 120, "completion_tokens": 3, "total_tokens": 123},
        )
        stream = litellm.completion(
            model="gemini/gemini-3.8-flash",
            messages=[{"role": "user", "content": "offline cost fixture"}],
            api_key="fixture-key",
            mock_response=response,
            stream=True,
            stream_options={"include_usage": True},
        )
        chunks = [chunk.model_dump(exclude_none=True) for chunk in stream]
    usage_chunks = [chunk["usage"] for chunk in chunks if chunk.get("usage")]
    assert len(usage_chunks) == 1
    assert usage_chunks[0]["prompt_tokens"] == 120
    assert usage_chunks[0]["completion_tokens"] == 3
    assert usage_chunks[0]["cost"] > 0
    return chunks


@dataclass
class StreamCostProxy:
    proxy: RegisteredProxyServer
    requests: list[dict[str, Any]]
    cost_micros: int | None
    has_usage: bool


@pytest.fixture(params=["gateway-cost", "missing-cost", "missing-usage", "zero-cost"])
def stream_cost_proxy(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    pinned_gateway_chunks: list[dict[str, Any]],
) -> Generator[StreamCostProxy, None, None]:
    chunks = copy.deepcopy(pinned_gateway_chunks)
    usage = next(chunk["usage"] for chunk in chunks if chunk.get("usage"))
    if request.param == "missing-cost":
        usage.pop("cost")
    elif request.param == "missing-usage":
        chunks = [chunk for chunk in chunks if not chunk.get("usage")]
    elif request.param == "zero-cost":
        usage["cost"] = 0.0
    has_usage = request.param != "missing-usage"
    cost_usd = usage.get("cost") if has_usage else None
    cost_micros = round(cost_usd * 1_000_000) if cost_usd is not None else None
    payload = ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
    requests: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("x-litellm-response-cost", "999")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            return

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    proc = None
    try:
        forge_home = get_forge_home()
        template = "litellm-gemini-test"
        proxy_id = "stream-cost"
        port = allocate_ephemeral_port()
        upstream_url = f"http://127.0.0.1:{upstream.server_port}/v1"
        _register_proxy_for_test(
            proxy_id=proxy_id,
            template=template,
            port=port,
            forge_home=forge_home,
            upstream_base_url=upstream_url,
        )
        proxy_path = forge_home / "proxies" / proxy_id / "proxy.yaml"
        config = yaml.safe_load(proxy_path.read_text())
        # One charged response fits; two cross the cap. Duplicate accounting would reject the second request.
        config["costs"] = {
            "caps": {"per_day": max((cost_micros or 0) * 1.5, 1) / 1_000_000},
            "on_cap_hit": "reject",
        }
        proxy_path.write_text(yaml.safe_dump(config, sort_keys=False))
        env = {
            **os.environ,
            "FORGE_HOME": str(forge_home),
            "PYTHON_DOTENV_DISABLED": "1",
            "LITELLM_LOCAL_BASE_URL": upstream_url,
            "LITELLM_API_KEY": "fixture-key",
        }
        proc = _start_proxy_subprocess(
            template=template,
            port=port,
            forge_home=forge_home,
            env=env,
            cwd=tmp_path,
            proxy_id=proxy_id,
        )
        yield StreamCostProxy(
            RegisteredProxyServer(proxy_id, template, f"http://127.0.0.1:{port}", port, forge_home),
            requests,
            cost_micros,
            has_usage,
        )
    finally:
        if proc is not None:
            kill_process(proc.pid)
            proc.wait(timeout=5)
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)


def test_litellm_stream_cost_telemetry_and_caps(
    stream_cost_proxy: StreamCostProxy,
) -> None:
    case = stream_cost_proxy
    payload = {
        "model": "haiku",
        "max_tokens": 8,
        "stream": True,
        "messages": [{"role": "user", "content": "offline cost fixture"}],
    }
    with httpx.Client(timeout=30) as client:
        for number in (1, 2):
            response = client.post(
                f"{case.proxy.base_url}/v1/messages",
                json=payload,
                headers={"x-api-key": "test"},
            )
            assert response.status_code == 200, response.text
            assert "X-Request-Cost" not in response.headers
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            assert events[-1]["type"] == "message_stop"
            assert not [event for event in events if event["type"] == "error"]
            if case.has_usage:
                final = next(
                    event for event in events if event["type"] == "message_delta" and event["delta"].get("stop_reason")
                )
                assert final["usage"]["input_tokens"] == 120
                assert final["usage"]["output_tokens"] == 3

            deadline = time.monotonic() + 5
            while True:
                records = read_downstream_records(kind="attempt")
                if len(records) >= number or time.monotonic() >= deadline:
                    break
                time.sleep(0.05)
            assert len(records) == number
            record = records[-1]
            assert record.proxy_id == case.proxy.proxy_id
            assert record.cost_micros == case.cost_micros
            assert (record.reporter, record.confidence) == (
                ("litellm", "gateway_calculated") if case.cost_micros is not None else (None, "unavailable")
            )
            assert (record.input_tokens, record.output_tokens) == ((120, 3) if case.has_usage else (0, 0))
            assert record.failed is False

            metrics = client.get(f"{case.proxy.base_url}/").json()["metrics"]
            expected_total = (case.cost_micros or 0) * number
            assert metrics["total_requests"] == number
            assert metrics["costs"]["total_micros"] == expected_total
            assert metrics["costs"]["caps"]["daily"]["current_usd"] == pytest.approx(expected_total / 1_000_000)
            assert metrics["costs"]["reported_request_count"] == (number if case.cost_micros is not None else 0)
            assert metrics["costs"]["unavailable_request_count"] == (number if case.cost_micros is None else 0)

        if case.cost_micros:
            refused = client.post(f"{case.proxy.base_url}/v1/messages", json=payload)
            assert refused.status_code == 429
            assert refused.json()["error"]["type"] == "spend_cap_exceeded"
            assert len(case.requests) == 2
        else:
            assert metrics["costs"]["caps"]["daily"]["current_usd"] == 0

    assert all(body["stream_options"] == {"include_usage": True} for body in case.requests)
    assert len({record.downstream_event_id for record in records}) == 2
    runner = CliRunner()
    costs = runner.invoke(
        main,
        ["telemetry", "costs", "show", case.proxy.proxy_id, "--by-model", "--json"],
    )
    assert costs.exit_code == 0, costs.output
    summary = json.loads(costs.stdout)
    assert summary["total_cost_micros"] == (case.cost_micros or 0) * 2
    assert summary["reported_requests"] == (2 if case.cost_micros is not None else 0)
    assert summary["unavailable_requests"] == (2 if case.cost_micros is None else 0)
    shown_metrics = runner.invoke(main, ["proxy", "metrics", case.proxy.proxy_id, "--json"])
    assert shown_metrics.exit_code == 0, shown_metrics.output
    assert json.loads(shown_metrics.stdout)["costs"]["total_micros"] == summary["total_cost_micros"]
