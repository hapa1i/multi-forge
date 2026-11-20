"""Sessionless Codex and a real Forge Responses proxy with an offline upstream."""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
import yaml
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.auth.credentials_file import save_profile
from forge.core.paths import get_forge_home
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


@pytest.fixture
def local_responses_proxy(tmp_path):
    requests = []
    release_terminal = threading.Event()
    delta = b'data: {"type":"response.output_text.delta","delta":"first"}\n\n'
    terminal = b'data: {"type":"response.completed","response":{"usage":{"input_tokens":8,"output_tokens":2}}}\n\n'

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, self.headers, body))
            self.send_response(200)
            self.send_header("x-litellm-response-cost", "0.125")
            if body.get("stream"):
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(delta)
                self.wfile.flush()
                if release_terminal.wait(timeout=8):
                    self.wfile.write(terminal)
            else:
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"id":"resp_fixture","usage":{"input_tokens":8,"output_tokens":2}}')

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    proc = None
    try:
        proxy_id = "codex-fixture"
        template = "codex-responses-local"
        port = allocate_ephemeral_port()
        upstream_base = f"http://127.0.0.1:{upstream.server_port}/gateway/v1"
        forge_home = get_forge_home()
        _register_proxy_for_test(
            proxy_id=proxy_id, template=template, port=port, forge_home=forge_home, upstream_base_url=upstream_base
        )
        path = forge_home / "proxies" / proxy_id / "proxy.yaml"
        config = yaml.safe_load(path.read_text())
        config["costs"] = {"caps": {"per_day": 0.125}, "on_cap_hit": "reject"}
        path.write_text(yaml.safe_dump(config))
        proc = _start_proxy_subprocess(
            template=template,
            port=port,
            forge_home=forge_home,
            env={**os.environ, "PYTHON_DOTENV_DISABLED": "1", "OPENAI_API_KEY": "fixture-upstream"},
            cwd=tmp_path,
            proxy_id=proxy_id,
        )
        yield f"http://127.0.0.1:{port}", requests, release_terminal
    finally:
        release_terminal.set()
        if proc is not None:
            kill_process(proc.pid)
            proc.wait(timeout=5)
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    "filename",
    ["0.170.0-exec-gpt-6.2-astra-custom-output", "0.161.0-exec-gemini-4-carbon-function-output"],
)
def test_incremental_relay_preserves_opaque_reasoning_and_tool_results(local_responses_proxy, filename):
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
        assert json.loads(next(lines).removeprefix("data: "))["delta"] == "first"
        release_terminal.set()
        events = [json.loads(line[6:]) for line in lines if line.startswith("data: ")]
        assert [event["type"] for event in events] == ["response.completed"]
    assert len(requests) == 1
    path, sent_headers, sent = requests[0]
    assert path == "/gateway/v1/responses"
    assert sent_headers["openai-beta"] == "responses=v1"
    assert sent_headers["authorization"] == "Bearer fixture-upstream"
    assert "x-api-key" not in sent_headers
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
