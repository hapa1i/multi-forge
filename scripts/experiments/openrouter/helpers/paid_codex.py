"""Stateless replay and isolated real-client checks for the approved Codex probe."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from codex_matrix import child_env, commands
from paid_diagnostics import envelope, sse_objects
from paid_guard import GUARD, REPO, Upstream
from paid_probe import response_summary
from responses_stub import MARKER, capture_shape, groups_of_tools, tools_in

READ = "cat fixture.txt"
WRITE = f"echo {MARKER} > proof.txt"
TOOL_INSTRUCTION = (
    "For a shell function use its command parameter. If the tool is functions.exec, use exactly "
    'text(await tools.exec_command({cmd:"COMMAND"})) replacing COMMAND with the specified command. '
    "Use no other tools or commands."
)
PROMPTS = (
    f"Read fixture.txt using exactly the local command {READ}. Report its contents. {TOOL_INSTRUCTION}",
    "Using the single word you read in the first turn, write proof.txt using exactly the command "
    "echo WORD > proof.txt, replacing WORD with the actual word. Then finish. " + TOOL_INSTRUCTION,
)


def check_inputs(manifest: dict, binary: Path | None = None) -> None:
    binary = (binary or Path(os.environ["OPENROUTER_RESPONSES_CODEX"])).resolve(strict=True)
    if hashlib.sha256(binary.read_bytes()).hexdigest() != manifest["binary"]["sha256"]:
        raise ValueError("Codex executable hash differs from approved manifest.")
    if not manifest["replay_fixtures"]:
        raise ValueError("No approved capture fixtures.")
    for spec in manifest["replay_fixtures"]:
        if spec.get("purpose", "tool") not in {"tool", "title"}:
            raise ValueError("Unknown fixture purpose.")
        path = (REPO / spec["path"]).resolve(strict=True)
        if not path.is_relative_to(REPO) or hashlib.sha256(path.read_bytes()).hexdigest() != spec["sha256"]:
            raise ValueError("Replay fixture path or checksum differs from approval.")
        body = envelope(path.read_bytes())
        if body.get("model") not in {
            manifest["models"]["default"],
            manifest["models"]["alternate"],
        }:
            raise ValueError("Replay fixture includes an unapproved model.")
        if (
            not isinstance(body.get("input"), list)
            or not all(item.get("type", "message") in {"message", "additional_tools"} for item in body["input"])
            or body.get("previous_response_id")
            or body.get("store") is True
        ):
            raise ValueError("Paid replay requires a sanitized, stateless first-turn fixture.")


def verify_tool(item: dict, command: str) -> bool:
    """Permit only the two literal synthetic commands. No response text is evaluated here."""
    name = item.get("name")
    if item["type"] == "custom_tool_call":
        if name not in {"exec", "functions.exec"} or item.get("namespace") not in {
            None,
            "functions",
        }:
            return False
        match = re.fullmatch(
            r'\s*text\(\s*await\s+tools\.exec_command\(\s*\{\s*(?:cmd|"cmd")\s*:\s*("(?:\\.|[^"\\])*")'
            r"\s*\}\s*\)\s*\)\s*;?\s*",
            item.get("input", ""),
        )
        return bool(match and json.loads(match.group(1)) == command)
    if item["type"] != "function_call" or name not in {
        "exec_command",
        "shell_command",
        "shell",
    }:
        return False
    args = json.loads(item["arguments"])
    key = "cmd" if name == "exec_command" else "command"
    if set(args) != {key}:
        return False
    value = args[key]
    if name == "shell":
        return (
            value in (["cat", "fixture.txt"], ["/bin/sh", "-c", command])
            if command == READ
            else value == ["/bin/sh", "-c", command]
        )
    return value == command


def items_safe(items: list[dict], command: str) -> list[dict]:
    calls = []
    for item in items:
        if item.get("type") in {"message", "reasoning", "compaction"}:
            continue
        if not verify_tool(item, command):
            raise ValueError(f"Unexpected output/tool outside the scratch task: {item.get('type')}/{item.get('name')}.")
        calls.append(item)
    return calls


def hosted_evidence(raw: bytes, streaming: bool) -> list[dict]:
    """Retain hosted tool lifecycle facts, including when a terminal never arrives."""
    observations = []
    events = sse_objects(raw) if streaming else [{"response": envelope(raw)}]
    for event in events:
        response = event.get("response") or {}
        items = list(response.get("output") or [])
        if isinstance(event.get("item"), dict):
            items.append(event["item"])
        for item in items:
            kind = item.get("type", "")
            if kind.endswith("_call") and kind not in ("function_call", "custom_tool_call", "local_shell_call"):
                row = {"type": kind[:80], "status": str(item.get("status", "unknown"))[:80]}
                if row not in observations:
                    observations.append(row)
    return observations


def metadata_warning(log_dir: Path) -> bool:
    # Keep diagnostics private; persist just the bounded text-search result.
    for name in ("stdout", "stderr"):
        path = log_dir / name
        if path.exists():
            with path.open("rb") as stream:
                lines = stream.read(65536)
                stream.seek(max(0, path.stat().st_size - 65536))
                lines += stream.read(65536)
            if b"fallback metadata" in lines.lower():
                return True
    return False


def require_local_tools(body: dict) -> None:
    for group in groups_of_tools(body):
        if any(kind not in {"function", "namespace", "custom"} for _, _, kind in tools_in(group)):
            raise ValueError("Fixture offers a hosted or unknown tool under required ZDR.")


def verify_title(items: list[dict], text_format: dict) -> int:
    schema = text_format["schema"]
    rule = schema["properties"]["title"]
    if (
        text_format.get("type") != "json_schema"
        or text_format.get("strict") is not True
        or schema.get("additionalProperties") is not False
        or schema.get("required") != ["title"]
        or set(schema["properties"]) != {"title"}
        or rule.get("type") != "string"
    ):
        raise ValueError("Unrecognized title fixture schema.")
    messages = [i for i in items if i.get("type") == "message"]
    if len(messages) != 1 or any(i.get("type") not in {"reasoning", "message"} for i in items):
        raise ValueError("Title control expected one assistant message.")
    parts = messages[0].get("content", [])
    if not parts or any(p.get("type") != "output_text" for p in parts):
        raise ValueError("Title control missing structured text.")
    parsed = envelope("".join(p["text"] for p in parts).encode())
    title = parsed.get("title")
    if (
        set(parsed) != {"title"}
        or not isinstance(title, str)
        or not rule["minLength"] <= len(title) <= rule["maxLength"]
    ):
        raise ValueError("Response violated the captured title schema.")
    return len(title)


def replay(api: Upstream, spec: dict, metadata: bool) -> dict:
    body = envelope((REPO / spec["path"]).read_bytes())
    require_local_tools(body)
    body["provider"] = dict(body.get("provider") or {}, zdr=True)
    # Begin with the approved capture's structure; replace only synthetic user prose
    # and retain placement of additional_tools and its namespace declarations.
    title = spec.get("purpose") == "title"
    prompt = "Give this synthetic task a short title: read a fixture and report its contents." if title else PROMPTS[0]
    user = next(i for i in reversed(body["input"]) if i.get("role") == "user")
    if isinstance(user.get("content"), str):
        user["content"] = prompt
    else:
        next(i for i in user["content"] if i.get("type") == "input_text")["text"] = prompt
    status, headers, raw = api.request("responses", body, metadata=metadata)
    result, first = response_summary(status, headers, raw, bool(body.get("stream")))
    items = result.get("output", [])
    if title:
        title_length = verify_title(items, body["text"]["format"])
        return {"fixture": spec, "response": first, "title_control": True, "title_length": title_length}
    calls = items_safe(items, READ)
    if len(calls) != 1 or not calls[0].get("call_id"):
        raise ValueError("Captured request produced no matching local read/call ID.")
    call = calls[0]
    output = {
        "type": call["type"] + "_output",
        "call_id": call["call_id"],
        "output": MARKER + "\n",
    }
    body["input"].extend([*items, output])
    status, headers, raw = api.request("responses", body, metadata=metadata)
    result, second = response_summary(status, headers, raw, bool(body.get("stream")))
    if items_safe(result.get("output", []), READ) or MARKER not in json.dumps(result.get("output", [])):
        raise ValueError("Follow-up failed to consume the matching fixture tool result.")
    return {
        "fixture": spec,
        "first": first,
        "followup": second,
        "encrypted_reasoning_replayed": any(i.get("encrypted_content") for i in items),
        "tool_replay_verified": True,
    }


def client_run(
    api: Upstream,
    model: str,
    required: bool,
    metadata: bool,
    evidence: dict,
    binary: Path,
) -> None:
    """Hold each complete upstream event stream until its scratch-tool requests have been verified."""
    secret = secrets.token_hex(24)
    record: dict = {
        "model": model,
        "required_zdr": required,
        "metadata_header": metadata,
        "requests": [],
        "turns": [],
    }
    evidence["client_runs"].append(record)
    errors: list[str] = []
    active_command = READ
    tools_seen = []

    class Bridge(BaseHTTPRequestHandler):
        def reply(self, status, content_type, data):
            self.send_response(status)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            try:
                if errors:
                    raise ValueError("Case stopped after first upstream diagnostic.")
                if self.path != "/v1/responses" or not hmac.compare_digest(
                    self.headers.get("Authorization", ""), "Bearer " + secret
                ):
                    raise ValueError("Unexpected method/path or loopback credential.")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 5 * 1024 * 1024:
                    raise ValueError("Invalid capture body size.")
                body = envelope(self.rfile.read(length))
                if body.get("model") != model or body.get("store") or body.get("previous_response_id"):
                    raise ValueError("Client changed approved model or requested stateful storage.")
                shape = capture_shape(body)
                if required:
                    require_local_tools(body)
                    body["provider"] = dict(body.get("provider") or {}, zdr=True)
                status, headers, raw = api.request("responses", body, metadata=metadata)
                observation = {
                    "path": self.path,
                    "shape": shape,
                    "http": status,
                    "turn": len(record["turns"]) + 1,
                }
                record["requests"].append(observation)
                if status != 200:
                    errors.append(f"Provider returned HTTP {status}.")
                    return self.reply(status, headers.get("content-type", "application/json"), raw)
                observation["hosted_tool_output"] = hosted_evidence(raw, bool(body.get("stream")))
                result, summary = response_summary(status, headers, raw, bool(body.get("stream")))
                observation["response"] = summary
                # Codex can act on output_item.done before seeing response.completed.
                # Only deliver native tool calls with matching final items at both boundaries.
                calls = items_safe(result.get("output", []), active_command)
                if body.get("stream"):
                    done = [e["item"] for e in sse_objects(raw) if e.get("type") == "response.output_item.done"]
                    done_calls = items_safe(done, active_command)
                    if done_calls != calls:
                        raise ValueError("Tool calls disagree between SSE item and terminal response.")
                tools_seen.extend([active_command] * len(calls))
                observation["local_fixture_calls"] = [
                    {
                        "type": c["type"],
                        "name": c.get("name"),
                        "operation": "read" if active_command == READ else "write",
                    }
                    for c in calls
                ]
                return self.reply(status, headers.get("content-type", "text/event-stream"), raw)
            except (ValueError, KeyError, OSError, StopIteration) as exc:
                if not errors:
                    errors.append(str(exc))
                self.reply(
                    400,
                    "application/json",
                    b'{"error":{"message":"Scratch probe stopped. Inspect local evidence."}}',
                )

        def do_GET(self):
            record["requests"].append({"path": self.path.split("?")[0], "http": 404, "forwarded": False})
            self.reply(
                404,
                "application/json",
                b'{"error":{"message":"No catalog on this probe"}}',
            )

        def log_message(self, format: str, *args) -> None:
            pass

    with (
        tempfile.TemporaryDirectory(prefix="forge-paid-codex-") as temp,
        ThreadingHTTPServer(("127.0.0.1", 0), Bridge) as gateway,
    ):
        root = Path(temp).resolve()
        env = child_env(root, binary)
        env.update({"FORGE_CODEX_PROXY_TOKEN": secret, "PYTHON_DOTENV_DISABLED": "1"})
        project, c_home = root / "work", root / "codex"
        (c_home / "config.toml").write_text(
            'check_for_update_on_startup = false\ncli_auth_credentials_store = "file"\n'
            "[analytics]\nenabled = false\n[feedback]\nenabled = false\n"
            f'[projects.{json.dumps(str(project))}]\ntrust_level = "trusted"\n'
        )
        (project / "fixture.txt").write_text(MARKER + "\n")
        thread = threading.Thread(target=gateway.serve_forever, daemon=True)
        thread.start()
        try:
            version = subprocess.check_output(
                [str(binary), "--version"],
                env=env,
                cwd=project,
                timeout=min(10, api.remaining()),
                text=True,
            )
            if api.manifest["binary"]["version"] not in version.split():
                raise ValueError("Retained executable version disagrees with manifest.")
            overrides = commands(
                binary,
                f"http://127.0.0.1:{gateway.server_port}/v1",
                model,
                "disabled" if required else "default",
                "normal",
            )
            session = None
            for turn, prompt in enumerate(PROMPTS):
                active_command = READ if turn == 0 else WRITE
                command = [*overrides, "exec"]
                if turn:
                    if not isinstance(session, str):
                        raise ValueError("Missing native resume identity.")
                    command += [
                        "resume",
                        "--json",
                        "--skip-git-repo-check",
                        session,
                        prompt,
                    ]
                else:
                    command += ["--json", "--skip-git-repo-check", prompt]
                output = root / f"run-{turn}"
                secs = min(120, api.remaining())
                if secs < 2:
                    raise ValueError("Insufficient time for bounded client turn.")
                ret = subprocess.run(
                    [
                        sys.executable,
                        str(GUARD),
                        "run",
                        "--seconds",
                        str(secs),
                        "--grace",
                        "1",
                        "--evidence",
                        str(output),
                        "--",
                        *command,
                    ],
                    env=env,
                    cwd=project,
                ).returncode
                record.setdefault("client_diagnostics", []).append(
                    {"turn": turn + 1, "returncode": ret, "fallback_metadata_warning": metadata_warning(output)}
                )
                if errors or ret:
                    raise ValueError(errors[0] if errors else f"Bounded Codex returned {ret}.")
                events = [
                    json.loads(line) for line in (output / "stdout").read_bytes().splitlines() if line.startswith(b"{")
                ]
                if turn == 0:
                    session = next(
                        (e.get("thread_id") for e in events if e.get("type") == "thread.started"),
                        None,
                    )
                    if not session or MARKER not in json.dumps(events) or READ not in tools_seen:
                        raise ValueError("Native read lacked tool, session or fixture marker.")
                elif WRITE not in tools_seen or (project / "proof.txt").read_text().strip() != MARKER:
                    raise ValueError("Native follow-up did not edit the scratch file correctly.")
                record["turns"].append({"turn": turn + 1, "verified": True})
        finally:
            gateway.shutdown()
            thread.join()
    if errors:
        raise ValueError(errors[0])


def stage_codex(api: Upstream, evidence: dict, *, cost_receipt: dict | None = None) -> None:
    if cost_receipt is None:
        cost_receipt = json.loads((api.ledger.directory / "cost.json").read_bytes())
    use_metadata = cost_receipt["try_metadata_on_codex"]
    evidence["client_runs"] = []
    binary = Path(os.environ["OPENROUTER_RESPONSES_CODEX"]).resolve()
    for model in (
        api.manifest["models"]["default"],
        api.manifest["models"]["alternate"],
    ):
        client_run(api, model, False, False, evidence, binary)
    evidence["replays"] = []
    for spec in api.manifest["replay_fixtures"]:
        evidence["replays"].append(replay(api, spec, use_metadata))
    if use_metadata:
        client_run(api, api.manifest["models"]["default"], True, True, evidence, binary)
