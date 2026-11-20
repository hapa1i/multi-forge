"""Sessionless Codex and a real Forge Responses proxy with an offline upstream."""

import json
import os
import sys
import threading
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
            self.send_response(upstream.status)
            self.send_header("x-litellm-response-cost", "0.125")
            self.send_header("x-generation-id", "gen-test")
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
    assert sent == body
    assert sent["input"][-3:] == [opaque, call, result]


def test_cap_blocks_foreground_and_compaction_retries_and_reports_recovery(local_responses_proxy):
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
