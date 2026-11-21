"""Sessionless Codex and a real Forge Responses proxy with an offline upstream."""

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.auth.credentials_file import save_profile
from forge.core.paths import get_forge_home
from forge.core.telemetry.downstream import read_downstream_records
from forge.proxy.proxies import ProxyRegistryStore
from forge.session.codex_invoke import invoke_codex_bare_proxy
from tests.fixtures.proxy import allocate_ephemeral_port, kill_process
from tests.integration.proxy.conftest import (
    _register_proxy_for_test,
    _start_proxy_subprocess,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("stored", [False, True], ids=["env-only", "credential-store"])
def test_bare_codex_child_and_nested_forge_credentials(stored, tmp_path: Path, monkeypatch, capfd):
    forge_home = tmp_path / "forge"
    forge_home.mkdir()
    monkeypatch.setenv("FORGE_HOME", str(forge_home))
    monkeypatch.setenv("FORGE_PROFILE", "default")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-parent")
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=fixture-dotenv\n")
    if stored:
        save_profile("default", {"OPENROUTER_API_KEY": "fixture-store"})

    child = tmp_path / "codex"
    child.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "assert 'OPENROUTER_API_KEY' not in os.environ\n"
        "assert os.environ['FORGE_CODEX_PROXY_TOKEN'] == 'forge-loopback'\n"
        "os.execvp('forge', ['forge', 'auth', 'status', '--json'])\n"
    )
    child.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    assert invoke_codex_bare_proxy(base_url="http://127.0.0.1:8105", cwd=str(tmp_path)) == 0
    status = json.loads(capfd.readouterr().out)
    router = next(cred for cred in status["credentials"] if cred["name"] == "openrouter")
    key = next(var for var in router["env_vars"] if var["name"] == "OPENROUTER_API_KEY")
    assert key["configured"] is stored
    assert key["source"] == ("file:default" if stored else "not configured")


def _codex_request(filename):
    board = Path(__file__).resolve().parents[3] / "docs/board"
    fixture = next(board.glob(f"*/codex_openrouter_responses/evidence/fixtures/{filename}.json"))
    return json.loads(fixture.read_bytes())


@dataclass
class ResponsesUpstream:
    base_url: str = ""
    requests: list = field(default_factory=list)
    release_terminal: threading.Event = field(default_factory=threading.Event)
    status: int = 200
    gateway_cost_header: str | None = "0.125"
    generation_id: str | None = "gen-test"
    drop_connection: bool = False
    reply: dict[str, Any] = field(
        default_factory=lambda: {
            "id": "gen-test",
            "status": "completed",
            "usage": {"input_tokens": 8, "output_tokens": 2, "cost": 0.125},
            "openrouter_metadata": {
                "endpoints": {
                    "available": [{"provider": "unused", "selected": False}, {"provider": "Azure", "selected": True}]
                }
            },
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "hi"}]}],
        }
    )
    repeat_terminal: bool = False
    omit_terminal: bool = False


@pytest.fixture
def responses_upstream():
    upstream = ResponsesUpstream()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            upstream.requests.append((self.path, self.headers, body))
            if upstream.drop_connection:
                self.close_connection = True
                return
            self.send_response(upstream.status)
            if upstream.gateway_cost_header is not None:
                self.send_header("x-litellm-response-cost", upstream.gateway_cost_header)
            if upstream.generation_id:
                self.send_header("x-generation-id", upstream.generation_id)
            self.send_header("X-Request-Cost", "9.999999")
            if self.path.endswith("/chat/completions"):
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {
                            "id": "gen-chat",
                            "created": 1,
                            "object": "chat.completion",
                            "model": body["model"],
                            "choices": [
                                {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "hi"}}
                            ],
                            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4, "cost": 0},
                        }
                    ).encode()
                )
            elif body.get("stream") and upstream.status == 200:
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b'data: {"type":"response.created","response":{"id":"gen-test"}}\n\n')
                self.wfile.write(b'data: {"type":"response.output_text.delta","delta":"first"}\n\n')
                self.wfile.flush()
                if upstream.release_terminal.wait(timeout=8) and not upstream.omit_terminal:
                    event = {"type": "response." + upstream.reply["status"], "response": upstream.reply}
                    self.wfile.write(
                        (b"data: " + json.dumps(event).encode() + b"\n\n") * (2 if upstream.repeat_terminal else 1)
                    )
            else:
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(upstream.reply).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    upstream.base_url = f"http://127.0.0.1:{server.server_port}/gateway/v1"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield upstream
    finally:
        upstream.release_terminal.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def proxy_template():
    return "codex-responses-local"


@pytest.fixture
def proxy_settings():
    return {"costs": {"caps": {"per_day": 0.125}, "on_cap_hit": "reject"}}


@pytest.fixture
def local_responses_proxy(tmp_path, responses_upstream, proxy_template, proxy_settings):
    proxy_id = "codex-fixture"
    port = allocate_ephemeral_port()
    forge_home = get_forge_home()
    _register_proxy_for_test(
        proxy_id=proxy_id,
        template=proxy_template,
        port=port,
        forge_home=forge_home,
        upstream_base_url=responses_upstream.base_url,
    )
    path = forge_home / "proxies" / proxy_id / "proxy.yaml"
    config = yaml.safe_load(path.read_text())
    config.update(proxy_settings)
    path.write_text(yaml.safe_dump(config))
    key = "OPENROUTER_API_KEY" if config["provider"] == "openrouter" else "OPENAI_API_KEY"
    proc = _start_proxy_subprocess(
        template=proxy_template,
        port=port,
        forge_home=forge_home,
        env={
            **os.environ,
            "PYTHON_DOTENV_DISABLED": "1",
            "OPENROUTER_BASE_URL": responses_upstream.base_url,
            key: "fixture-upstream",
        },
        cwd=tmp_path,
        proxy_id=proxy_id,
    )
    try:
        store = ProxyRegistryStore()
        registry = store.read()
        registry.proxies[proxy_id].pid = proc.pid
        registry.proxies[proxy_id].status = "healthy"
        store.write(registry)
        yield f"http://127.0.0.1:{port}", responses_upstream.requests, responses_upstream.release_terminal
    finally:
        responses_upstream.release_terminal.set()
        kill_process(proc.pid)
        proc.wait(timeout=5)


@pytest.mark.parametrize("proxy_template", ["codex-responses-local", "codex-responses-openrouter"])
@pytest.mark.parametrize(
    "filename",
    ["0.170.0-exec-gpt-6.2-astra-custom-output", "0.161.0-exec-gemini-4-carbon-function-output"],
)
def test_incremental_relay_preserves_opaque_reasoning_and_tool_results(local_responses_proxy, proxy_template, filename):
    base, requests, release_terminal = local_responses_proxy
    body = _codex_request(filename)
    call, result = body["input"][-2:]
    assert call["call_id"] == result["call_id"]
    opaque = {"id": "rs_fixture", "type": "reasoning", "summary": [], "encrypted_content": "opaque+/fixture=="}
    body["input"].insert(-2, opaque)
    headers = {"openai-beta": "responses=v1", "authorization": "Bearer fixture-child", "x-api-key": "fixture-inbound"}
    with httpx.stream("POST", base + "/v1/responses", json=body, headers=headers, timeout=10) as response:
        assert response.status_code == 200
        lines = response.iter_lines()
        data = (json.loads(line[6:]) for line in lines if line.startswith("data: "))
        assert next(data)["type"] == "response.created"
        assert next(data)["delta"] == "first"
        release_terminal.set()
        events = list(data)
        assert [event["type"] for event in events] == ["response.completed"]
    assert len(requests) == 1
    path, sent_headers, sent = requests[0]
    assert path == "/gateway/v1/responses"
    assert sent_headers["openai-beta"] == "responses=v1"
    assert sent_headers["authorization"] == "Bearer fixture-upstream"
    assert "x-api-key" not in sent_headers
    if proxy_template == "codex-responses-openrouter":
        assert sent_headers["x-openrouter-metadata"] == "enabled"
        del body["client_metadata"], body["prompt_cache_key"]
        body["provider"] = {"zdr": True}
        body["plugins"] = [{"id": "web", "enabled": False}]
    assert sent == body
    assert sent["input"][-3:] == [opaque, call, result]


@pytest.mark.parametrize("proxy_template", ["codex-responses-local", "codex-responses-openrouter"])
def test_cap_blocks_foreground_and_compaction_retries_and_reports_recovery(local_responses_proxy, proxy_template):
    base, requests, _ = local_responses_proxy
    foreground = _codex_request("0.170.0-tui-gpt-6.2-astra-tool")
    compaction = _codex_request("0.170.0-tui-gpt-6.2-astra-compaction-prompt")
    with httpx.Client(base_url=base, timeout=10) as client:
        admitted = client.post("/v1/responses", json={**foreground, "stream": False})
        assert admitted.status_code == 200
        for request in [foreground] + [compaction] * 6:
            refused = client.post("/v1/responses", json=request)
            assert refused.status_code == 429
            assert refused.json()["error"]["type"] == "spend_cap_exceeded"
            assert "$0.125 / $0.125" in refused.headers["X-Spend-Warning"]
            assert "forge proxy set codex-fixture costs.caps.per_day" in refused.headers["X-Spend-Warning"]
        costs = client.get("/").json()["metrics"]["costs"]
    assert len(requests) == 1
    assert costs["caps"]["daily"]["current_usd"] == costs["caps"]["daily"]["limit_usd"] == 0.125
    result = CliRunner().invoke(main, ["proxy", "metrics", "codex-fixture"])
    assert result.exit_code == 0, result.output
    assert "$0.125 / $0.125" in result.output
    assert "New generations are blocked." in result.output
    assert "forge proxy set codex-fixture costs.caps.per_day=<amount>" in result.output


@pytest.mark.parametrize("proxy_template", ["codex-responses-openrouter"])
@pytest.mark.parametrize(
    "proxy_settings",
    [
        {"allow_non_zdr": allow, "zdr_fallbacks": {"openai/gpt-6.2-astra": "google/gemini-4-carbon"}}
        for allow in (False, True)
    ],
)
def test_recorded_layouts_and_cross_family_policy(local_responses_proxy, proxy_template, proxy_settings):
    allow = proxy_settings["allow_non_zdr"]
    base, calls, release = local_responses_proxy
    release.set()
    live = httpx.get(base).json()["runtime"]["responses_policy"]
    assert live["required_zdr"] is (not allow)
    board = Path(__file__).resolve().parents[3] / "docs/board"
    paths = list(board.glob("*/codex_openrouter_responses/evidence/fixtures/*.json"))
    assert len(paths) == 18
    with httpx.Client(base_url=base, timeout=10) as client:
        for fixture in paths:
            body = json.loads(fixture.read_bytes())
            body["provider"] = {"zdr": False, "order": ["fixture"]}
            before = len(calls)
            reply = client.post("/v1/responses", json=body)
            if "hosted-control" in fixture.name and not allow:
                assert reply.status_code == 400 and "allow_non_zdr=true" in reply.json()["error"]["message"]
                assert len(calls) == before
                continue
            assert reply.status_code == 200, reply.text
            assert len(calls) == before + 1
            sent = calls[-1][2]
            del body["client_metadata"], body["prompt_cache_key"]
            if not allow:
                body["provider"]["zdr"] = True
                body["plugins"] = [{"id": "web", "enabled": False}]
                if body["model"] == "openai/gpt-6.2-astra":
                    body["model"] = "google/gemini-4-carbon"
            assert sent == body
        before = len(calls)
        for verb, path in [("GET", "prior/input_items"), ("POST", "compact"), ("DELETE", "prior")]:
            reply = client.request(verb, "/v1/responses/" + path)
            assert reply.status_code == 400 and reply.json()["error"]["code"] == "unsupported_operation"
        assert len(calls) == before
        messages = client.post(
            "/v1/messages", json={"model": "sonnet", "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]}
        )
        assert messages.status_code == 200, messages.text
        assert calls[-1][0].endswith("/chat/completions")


@pytest.mark.parametrize(
    ("proxy_template", "proxy_settings"),
    [
        (
            "codex-responses-openrouter",
            {"zdr_fallbacks": {slug: "google/gemini-4-carbon" for slug in ("openai/gpt-6.2-astra", "qwen/qwen4-max")}},
        ),
        ("codex-responses-local", {}),
        ("openrouter-openai-codex", {}),
    ],
)
def test_template_name_launch_uses_verified_proxy(
    local_responses_proxy, proxy_template, proxy_settings, tmp_path, monkeypatch
):
    child = tmp_path / "codex"
    captured = tmp_path / "argv.json"
    child.write_text(
        f"#!{sys.executable}\nimport json, sys, os\nfrom pathlib import Path\n"
        "if '--version' in sys.argv: print('codex-cli 0.170.0'); sys.exit()\n"
        "assert 'OPENROUTER_API_KEY' not in os.environ\n"
        f"Path({str(captured)!r}).write_text(json.dumps(sys.argv[1:]))\n"
    )
    child.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    for args in ([], ["--", "-m", "qwen/qwen4-max"]):
        result = CliRunner().invoke(main, ["codex", "start", "--proxy", proxy_template, *args])
        if proxy_template == "openrouter-openai-codex":
            assert result.exit_code == 1 and "Responses-capable proxy required" in result.output
            assert not captured.exists()
            continue
        assert result.exit_code == 0, result.output
        argv = json.loads(captured.read_bytes())
        assert ('web_search="disabled"' in argv) == (proxy_template == "codex-responses-openrouter")
        assert argv[argv.index("-m") + 1] == ("qwen/qwen4-max" if args else "openai/gpt-6.2-astra")
        if proxy_template == "codex-responses-openrouter":
            assert "dispatching google/gemini-4-carbon" in " ".join(result.output.split())


def _attempt(request_id):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        rows = read_downstream_records(proxy_id="codex-fixture", request_id=request_id)
        if rows and rows[0].request_mode is not None:
            assert len(rows) == 1
            return rows[0]
        time.sleep(0.025)
    pytest.fail(f"Missing completed trace for {request_id}")


def _forge(*args):
    result = CliRunner().invoke(main, list(args))
    assert result.exit_code == 0, (result.output, result.exception)
    return result.output


@pytest.mark.parametrize("proxy_template", ["codex-responses-openrouter"])
@pytest.mark.parametrize(
    "proxy_settings",
    [{"zdr_fallbacks": {"openai/gpt-6.2-astra": "google/gemini-4-carbon"}, "costs": {"caps": {"per_day": 0.1}}}],
)
def test_byok_fallback_cost_and_duplicate_terminal(
    local_responses_proxy, responses_upstream, proxy_template, proxy_settings
):
    base, calls, release = local_responses_proxy
    requested, dispatched = "openai/gpt-6.2-astra", "google/gemini-4-carbon"
    provider = responses_upstream
    usage = provider.reply["usage"]
    usage.update(cost=0, is_byok=True, cost_details={"upstream_inference_cost": 9.25})
    provider.reply["id"] = "resp-local"
    body = {"model": requested, "input": "hi"}
    with httpx.Client(base_url=base) as client:
        reply = client.post("/v1/responses", json=body)
        assert reply.headers["x-request-cost"] == "0.000000"
        first = _attempt(reply.headers["x-request-id"])
        assert (first.model, first.mapped_model, first.cost_micros) == (requested, dispatched, 0)
        assert (first.provider_response_id, first.provider_generation_id, first.selected_provider) == (
            "resp-local",
            "gen-test",
            "Azure",
        )
        assert client.get("/").json()["metrics"]["costs"]["caps"]["daily"]["current_usd"] == 0
        usage["cost"] = 0.1000005
        release.set()
        provider.repeat_terminal = True
        reply = client.post("/v1/responses", json={**body, "stream": True})
        assert reply.text.count('"type": "response.completed"') == 2
        row = _attempt(reply.headers["x-request-id"])
        assert row.cost_micros == row.reported_cost_micros == 100001
        assert (row.reporter, row.confidence, row.selected_provider) == ("openrouter", "reported", "Azure")
        metrics = client.get("/").json()["metrics"]
        assert metrics["costs"]["total_micros"] == 100001
        assert metrics["costs"]["caps"]["daily"]["current_usd"] == pytest.approx(0.100001)
        assert metrics["by_model"][dispatched]["requests"] == 2 and requested not in metrics["by_model"]
        assert client.post("/v1/responses", json=body).status_code == 429
    assert len(calls) == 2
    shown = _forge("telemetry", "trace", "show", row.request_id)
    assert "Requested model" in shown and requested in shown and dispatched in shown
    trace = json.loads(_forge("telemetry", "trace", "show", row.request_id, "--json"))
    assert (trace["requested_model"], trace["mapped_model"]) == (requested, dispatched)
    assert "gen-test" in _forge("telemetry", "trace", "explain", row.request_id, "--json")
    costs = json.loads(_forge("telemetry", "costs", "show", "codex-fixture", "--by-model", "--json"))
    assert costs["by_model"][dispatched]["cost_micros"] == 100001 and requested not in costs["by_model"]
    assert "OpenRouter account credit" in _forge("proxy", "metrics", "codex-fixture")


@pytest.mark.parametrize("proxy_template", ["codex-responses-openrouter"])
@pytest.mark.parametrize("proxy_settings", [{"costs": {"caps": {"per_day": 4.10}, "on_cap_hit": "warn"}}])
def test_zdr_refusal_retains_warn_header_at_exact_cap(local_responses_proxy, responses_upstream):
    base, calls, _ = local_responses_proxy
    body = {"model": "fixture/model", "input": "hi"}
    with httpx.Client(base_url=base) as client:
        for cost in (4.099999, 0.000001):
            responses_upstream.reply["usage"]["cost"] = cost
            paid = client.post("/v1/responses", json=body)
            assert paid.status_code == 200
            assert "X-Spend-Warning" not in paid.headers
        responses_upstream.status = 404
        responses_upstream.reply = {
            "error": {"message": "No endpoints found matching your data policy (Zero data retention)"}
        }
        for stream in (False, True):
            refusal = client.post("/v1/responses", json={**body, "stream": stream})
            assert refusal.status_code == 400
            assert refusal.json()["error"]["code"] == "zdr_unavailable"
            assert "$4.10 / $4.10" in refusal.headers["X-Spend-Warning"]
            assert "X-Request-ID" in refusal.headers
        assert len(calls) == 4


@pytest.mark.parametrize("proxy_template", ["codex-responses-openrouter"])
@pytest.mark.parametrize("proxy_settings", [{}])
@pytest.mark.parametrize(
    "case,stream",
    [
        ("completed", False),
        ("incomplete", True),
        ("absent-status", False),
        ("queued", False),
        ("failed", False),
        ("failed", True),
        ("http", True),
        ("http", False),
        ("transport", True),
        ("transport", False),
        ("eof", True),
        ("disconnect", True),
        ("account", False),
        ("request", True),
    ],
)
def test_next_create_after_missing_cost(
    local_responses_proxy, responses_upstream, proxy_template, proxy_settings, case, stream
):
    base, calls, release = local_responses_proxy
    provider = responses_upstream
    provider.generation_id = None
    provider.reply["id"] = "resp-only"
    del provider.reply["usage"]["cost"], provider.reply["openrouter_metadata"]
    provider.reply["status"] = case
    if case == "absent-status":
        del provider.reply["status"]
    if case in ("http", "account", "request"):
        provider.status = 404
        error: dict[str, Any] = {"message": "fixture missing"}
        if case == "account":
            error["metadata"] = {"ineligibility_reasons": [{"reason": "zdr-violation-by-account"}]}
        elif case == "request":
            error["message"] = (
                "No endpoints found matching your data policy (Zero data retention). Configure: https://openrouter.ai/settings/privacy"
            )
        provider.reply = {"error": error}
    provider.drop_connection = case == "transport"
    provider.omit_terminal = case in ("eof", "disconnect")
    if case != "disconnect":
        release.set()
    body = {"model": "fixture/model", "input": "hi"}
    with httpx.Client(base_url=base, timeout=10) as client:
        with client.stream("POST", "/v1/responses", json={**body, "stream": stream}) as response:
            expected = {
                "http": 404,
                "account": 400,
                "request": 400,
                "transport": 502,
                "absent-status": 502,
                "queued": 502,
            }.get(case, 200)
            assert response.status_code == expected
            assert "x-request-cost" not in response.headers
            if case == "disconnect":
                lines = response.iter_lines()
                assert "response.created" in next(lines)
                assert any("first" in line for line in lines)
            else:
                raw = response.read()
                if case in ("account", "request"):
                    assert b"ZDR" in raw and (b"settings/privacy" in raw) == (case == "account")
        row = _attempt(response.headers["x-request-id"])
        assert row.cost_micros is None and row.provider_generation_id is None and row.selected_provider is None
        if case == "disconnect":
            assert row.client_disconnected and row.provider_response_id == "gen-test"
        missing = case in ("completed", "incomplete", "absent-status", "queued")
        assert client.get("/").json()["runtime"]["responses_policy"]["unreported_cost_observed"] is missing
        release.set()
        provider.status, provider.drop_connection = 200, False
        provider.reply = {"id": "resp-next", "status": "completed", "usage": {"cost": 0}}
        result = client.post("/v1/responses", json=body)
        assert result.status_code == (400 if missing else 200)
        if missing:
            assert "costs.on_unreported_cost=allow" in result.json()["error"]["message"]
            msg = client.post(
                "/v1/messages",
                json={"model": "sonnet", "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]},
            )
            assert msg.status_code == 200
        assert len([c for c in calls if c[0].endswith("/responses")]) == (1 if missing else 2)


@pytest.mark.parametrize("stored", [False, True], ids=["env-only", "credential-store"])
def test_create_start_smoke_and_missing_cost_recovery(responses_upstream, monkeypatch, stored, tmp_path):
    provider = responses_upstream
    proxy_id = "smoke-acceptance"
    port = allocate_ephemeral_port()
    base = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("OPENROUTER_BASE_URL", provider.base_url)
    monkeypatch.setenv("FORGE_PROFILE", "default")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    key = "store-fixture" if stored else "env-fixture"
    if stored:
        save_profile("default", {"OPENROUTER_API_KEY": key})
    else:
        monkeypatch.setenv("OPENROUTER_API_KEY", key)
    child = tmp_path / "codex"
    child.write_text(
        f"#!{sys.executable}\nimport os,sys\nif '--version' in sys.argv: print('codex-cli 0.170.0')\nelif 'features' in sys.argv: print('hooks stable true')\nelif 'doctor' in sys.argv: print('{{}}')\nelse: assert 'OPENROUTER_API_KEY' not in os.environ and os.environ['FORGE_CODEX_PROXY_TOKEN'] == 'forge-loopback'\n"
    )
    child.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    runner = CliRunner()
    provider.reply["usage"].pop("cost")
    try:
        create = runner.invoke(
            main,
            [
                "proxy",
                "create",
                "codex-responses-openrouter",
                "--name",
                proxy_id,
                "--port",
                str(port),
                "--base-url",
                provider.base_url,
                "--json",
                "--smoke-test",
            ],
        )
        assert create.exit_code == 1, (create.output, create.exception)
        payload = json.loads(create.stdout)
        assert payload["status"] == "healthy" and not payload["smoke_test"]["passed"]
        assert f"forge proxy set {proxy_id} costs.on_unreported_cost=allow" in payload["smoke_test"]["detail"]
        assert len(provider.requests) == 1
        assert provider.requests[0][1]["authorization"] == "Bearer " + key
        again = runner.invoke(main, ["proxy", "start", proxy_id, "--smoke-test"])
        assert again.exit_code == 1 and "costs.on_unreported_cost=allow" in again.output
        assert len(provider.requests) == 1
        _forge("proxy", "set", proxy_id, "costs.caps.per_day=0.25")
        _forge("proxy", "stop", proxy_id)
        provider.reply["usage"]["cost"] = 0.125
        assert "Smoke test passed" in _forge("proxy", "start", proxy_id, "--smoke-test")
        assert len(provider.requests) == 2
        assert not httpx.get(base).json()["runtime"]["responses_policy"]["unreported_cost_observed"]
        preflight = runner.invoke(main, ["runtime", "preflight", "codex", "--proxy", proxy_id, "--json"])
        assert json.loads(preflight.stdout)["proxy_responses"] == "proxy_supported"
        _forge("codex", "start", "--proxy", proxy_id)
        _forge("proxy", "set", proxy_id, "costs.on_unreported_cost=allow")
        _forge("proxy", "stop", proxy_id)
        provider.reply["usage"].pop("cost")
        assert "Smoke test passed" in _forge("proxy", "start", proxy_id, "--smoke-test")
        restarted = httpx.get(base).json()
        assert restarted["runtime"]["responses_policy"]["on_unreported_cost"] == "allow"
        assert restarted["metrics"]["costs"]["caps"]["daily"]["current_usd"] == 0.125
        assert "Unreported OpenRouter" in _forge("codex", "start", "--proxy", proxy_id)
        assert len(provider.requests) == 3
    finally:
        runner.invoke(main, ["proxy", "stop", proxy_id])


def test_unpriced_litellm_responses_still_serves(local_responses_proxy, responses_upstream):
    base, calls, _ = local_responses_proxy
    responses_upstream.gateway_cost_header = None
    responses_upstream.reply["usage"].pop("cost")
    with httpx.Client(base_url=base) as client:
        for _ in range(2):
            response = client.post("/v1/responses", json={"model": "local/model", "input": "hi"})
            assert response.status_code == 200 and "x-request-cost" not in response.headers
        assert client.get("/").json()["metrics"]["costs"]["total_micros"] == 0
    assert len(calls) == 2
