"""Real native admission probes against a local upstream, run only in an offline container."""

from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import forge
from forge.core.invoker import (
    ClaudeHeadlessInvoker,
    CodexHeadlessInvoker,
    HeadlessRequest,
    HeadlessResult,
    prepare_codex_request,
)
from forge.core.reactive.routing import ModelRoute, RoutingResult
from forge.core.reactive.session_runner import SessionResult, run_claude_session
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.review.engine import _prepare_worker
from forge.review.models import ModelSpec

HOSTILE_ENV = {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "CLAUDE_CODE_FORK_SUBAGENT": "1",
    "CLAUDE_CODE_DISABLE_WORKFLOWS": "0",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "0",
}


def claude_events(tool: str) -> list[dict]:
    block = (
        {"type": "tool_use", "id": "tool_probe", "name": tool, "input": {}} if tool else {"type": "text", "text": ""}
    )
    value = (
        {"skill": "fork-probe"}
        if tool == "Skill"
        else {
            "description": "native probe",
            "prompt": "Reply PROBE_CHILD",
            "subagent_type": "general-purpose",
        }
    )
    delta = (
        {"type": "input_json_delta", "partial_json": json.dumps(value)}
        if tool
        else {"type": "text_delta", "text": "PROBE_DONE"}
    )
    return [
        {
            "type": "message_start",
            "message": {
                "id": "msg_probe",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-4-5",
                "content": [],
                "stop_reason": None,
                "usage": {"input_tokens": 10, "output_tokens": 1},
            },
        },
        {"type": "content_block_start", "index": 0, "content_block": block},
        {"type": "content_block_delta", "index": 0, "delta": delta},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use" if tool else "end_turn"},
            "usage": {"output_tokens": 2},
        },
        {"type": "message_stop"},
    ]


def codex_events(tool: str) -> list[dict]:
    item: dict[str, object] = {
        "type": "message",
        "id": "msg_probe",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": "PROBE_DONE", "annotations": []}],
    }
    if tool:
        item = {
            "type": "function_call",
            "id": "fc_probe",
            "call_id": "call_probe",
            "name": tool,
            "arguments": json.dumps({"message": "Reply PROBE_CHILD"}),
            "namespace": "multi_agent_v1",
        }
    if tool == "tool_search":
        item = {
            "type": "tool_search_call",
            "id": "ts_probe",
            "call_id": "call_search",
            "execution": "client",
            "status": "completed",
            "arguments": {"query": "spawn agent", "limit": 3},
        }
    response = {
        "id": "resp_probe",
        "object": "response",
        "status": "completed",
        "output": [item],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 2,
            "total_tokens": 12,
            "input_tokens_details": {"cached_tokens": 0},
        },
    }
    return [
        {
            "type": "response.created",
            "response": {**response, "status": "in_progress", "output": []},
        },
        {"type": "response.output_item.added", "output_index": 0, "item": item},
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        {"type": "response.completed", "response": response},
    ]


class Upstream(ThreadingHTTPServer):
    def __init__(self, runtime: str, tool: str):
        self.runtime = runtime
        self.tool = tool
        self.requests: list[dict] = []
        super().__init__(("127.0.0.1", 0), Handler)


class Handler(BaseHTTPRequestHandler):
    server: Upstream

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"data":[]}')

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        self.send_response(200)
        if not ("messages" in data or "input" in data):
            self.end_headers()
            self.wfile.write(b"{}")
            return
        self.server.requests.append(data)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        tool = self.server.tool if len(self.server.requests) == 1 else ""
        if self.server.runtime == "codex" and self.server.tool:
            # Agent tools are deferred and namespaced in the pinned runtime. Exercise discovery before admission.
            tool = (
                "tool_search"
                if len(self.server.requests) == 1
                else self.server.tool if len(self.server.requests) == 2 else ""
            )
        events = claude_events(tool) if self.server.runtime == "claude" else codex_events(tool)
        for event in events:
            self.wfile.write(("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode())

    def log_message(self, *args):
        pass


def configure(home: Path, runtime: str, base: str, bare: bool) -> dict[str, str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "TMPDIR": "/tmp",
        "USER": "probe",
        "FORGE_HOME": str(home / ".forge"),
        "PYTHON_DOTENV_DISABLED": "1",
        "DISABLE_AUTOUPDATER": "1",
    }
    if runtime == "claude":
        config = home / ".claude"
        skill = config / "skills/fork-probe"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: fork-probe\ndescription: native control probe\ncontext: fork\nagent: general-purpose\n---\nReply PROBE_CHILD.\n"
        )
        (config / "settings.json").write_text(json.dumps({"autoMemoryEnabled": True, "env": HOSTILE_ENV}))
        env.update(HOSTILE_ENV)
        env.update(ANTHROPIC_BASE_URL=base, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")
        env["ANTHROPIC_API_KEY" if bare else "ANTHROPIC_AUTH_TOKEN"] = "fixture-not-a-provider-key"
    else:
        config = home / ".codex"
        config.mkdir()
        env["CODEX_HOME"] = str(config)
        (config / "config.toml").write_text(
            'model = "gpt-5.4"\nmodel_provider = "fixture"\n[model_providers.fixture]\nname = "Fixture"\n'
            'wire_api = "responses"\nrequires_openai_auth = false\nbase_url = "' + base + '/v1"\n'
            "[agents]\nenabled = true\n[features]\nmulti_agent = true\n"
            "[memories]\nuse_memories = true\ngenerate_memories = true\n"
        )
    return env


def codex_request(repo: Path, worker: bool, resume_id: str | None = None) -> HeadlessRequest:
    # A local provider needs no authentication. This fixture bypasses only the external auth probe.
    preflight = CodexPreflight(
        installed=True,
        version="fixture",
        version_ok=True,
        auth_method="chatgpt_tokens",
        auth_source="codex_store",
        billing_mode="unknown",
        ready=True,
        blocking_reason=None,
        hook_seam="enrollment_gated",
        proxy_responses="native_direct",
        doctor_status="ok",
    )
    return prepare_codex_request(
        prompt="Reply PROBE_DONE",
        preflight=preflight,
        attribution=None,
        cwd=str(repo),
        sandbox="read-only",
        worker=worker,
        resume_thread_id=resume_id,
        timeout_seconds=30,
    )


def run_probe(runtime: str, tool: str, mode: str, bare: bool = False) -> dict:
    with tempfile.TemporaryDirectory(prefix="native-worker-") as root:
        home = Path(root)
        repo = home / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        server = Upstream(runtime, tool)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"
        env = configure(home, runtime, base, bare)
        calls: list[tuple[list[str], dict[str, str]]] = []
        run = subprocess.run

        def record(argv, **kwargs):
            if "-p" in argv:
                calls.append((list(argv), dict(kwargs["env"])))
            return run(argv, **kwargs)

        result: HeadlessResult | SessionResult | None
        try:
            with patch.dict(os.environ, env, clear=True):
                version = run(
                    [runtime, "--version"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=15,
                ).stdout.strip()
                if runtime == "codex":
                    resume_id = None
                    if mode == "resume":
                        server.tool = ""
                        seed = CodexHeadlessInvoker().run(codex_request(repo, worker=True))
                        assert seed.success, seed.stderr
                        resume_id = seed.runtime_session_id
                        assert resume_id
                        server.requests.clear()
                        server.tool = tool
                    request = codex_request(repo, worker=mode != "root", resume_id=resume_id)
                    calls.append((request.argv, request.env))
                    result = CodexHeadlessInvoker().run(request)
                elif mode == "consumer":
                    with patch(
                        "forge.core.reactive.session_runner.subprocess.run",
                        side_effect=record,
                    ):
                        result = run_claude_session(
                            "Reply PROBE_DONE",
                            worker=True,
                            model="claude-haiku-4-5",
                            base_url=base,
                            cwd=str(repo),
                            timeout_seconds=30,
                            extra_env=HOSTILE_ENV,
                            unset_env_vars=tuple(HOSTILE_ENV),
                        )
                elif mode == "legacy":
                    # The proposal's original switches admit fork-context Skill, even with Agent denied.
                    argv = [
                        "claude",
                        "-p",
                        "--model",
                        "claude-haiku-4-5",
                        "--disallowedTools",
                        "Agent",
                        "Workflow",
                        "SendMessage",
                    ]
                    legacy_env = dict(
                        env,
                        CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS="0",
                        CLAUDE_CODE_FORK_SUBAGENT="0",
                        CLAUDE_CODE_DISABLE_WORKFLOWS="1",
                        CLAUDE_CODE_DISABLE_AUTO_MEMORY="1",
                    )
                    calls.append((argv, legacy_env))
                    completed = run(
                        argv,
                        input="Reply PROBE_DONE",
                        env=legacy_env,
                        cwd=repo,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    assert completed.returncode == 0, completed.stderr
                    result = None
                else:
                    route = ModelRoute(
                        provider="openrouter",
                        credential="fixture",
                        family="anthropic",
                        template_id=None,
                        template_family=None,
                        model_ref="claude-haiku-4-5",
                    )
                    prepared = _prepare_worker(
                        ModelSpec(
                            name="probe",
                            model_id="claude-haiku-4-5",
                            family="anthropic",
                            description="fixture",
                        ),
                        RoutingResult(
                            base_url=base,
                            proxy_id=None,
                            template=None,
                            source="preferred_proxy",
                            route=route,
                            credential=None,
                        ),
                        prompt="Reply PROBE_DONE",
                        cwd=str(repo),
                        resume_id=None,
                        timeout_seconds=30,
                        attribution=None,
                    )
                    assert isinstance(prepared, HeadlessRequest), prepared
                    request = prepared
                    calls.append((request.argv, request.env))
                    result = ClaudeHeadlessInvoker().run(request)
                if result is not None:
                    assert result.success, result.error or result.stderr
                    assert "PROBE_DONE" in result.stdout
            assert server.requests, "The runtime never reached the local fixture"
            tools = sorted(
                {item.get("name", item.get("type", "")) for req in server.requests for item in req.get("tools", [])}
            )
            outputs: list[str] = []
            discovered: set[str] = set()
            for req in server.requests:
                for item in req.get("input", []):
                    if isinstance(item, dict) and item.get("type") == "tool_search_output":
                        for namespace in item.get("tools", []):
                            discovered.update(
                                f"{namespace['name']}.{tool['name']}" for tool in namespace.get("tools", [])
                            )
                outputs.extend(
                    item["output"]
                    for item in req.get("input", [])
                    if isinstance(item, dict) and item.get("type") == "function_call_output"
                )
                for message in req.get("messages", []):
                    content = message.get("content", [])
                    if isinstance(content, list):
                        outputs.extend(
                            str(item.get("content", "")) for item in content if item.get("type") == "tool_result"
                        )
            return {
                "runtime": runtime,
                "version": version,
                "mode": mode,
                "bare": bare,
                "injected_tool": tool,
                "requests": len(server.requests),
                "tools": tools,
                "tool_outputs": sorted({output.split("\n\n<system-reminder>")[0] for output in outputs}),
                "discovered_tools": sorted(discovered),
                "auto_memory_prompt": any(
                    "# auto memory" in block.get("text", "")
                    for req in server.requests
                    for block in req.get("system", [])
                    if isinstance(block, dict)
                ),
                "child_transcripts": len(list(home.rglob("agent-*.jsonl"))) if runtime == "claude" else None,
                "argv": calls[-1][0],
                "environment": {key: calls[-1][1][key] for key in HOSTILE_ENV if key in calls[-1][1]},
            }
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    cases: list[tuple[str, str, str, bool]] = [
        ("claude", "Skill", "legacy", False),
        ("claude", "Agent", "review", False),
        ("claude", "Skill", "review", False),
        ("claude", "Skill", "review", True),
        ("claude", "Workflow", "consumer", False),
        ("claude", "SendMessage", "consumer", False),
        ("claude", "Skill", "consumer", False),
        ("codex", "spawn_agent", "root", False),
        ("codex", "spawn_agent", "worker", False),
        ("codex", "spawn_agent", "resume", False),
    ]
    print(
        json.dumps(
            {
                "forge_version": importlib.metadata.version("multi-forge"),
                "forge_file": forge.__file__,
                "probes": [run_probe(*case) for case in cases],
            }
        )
    )
