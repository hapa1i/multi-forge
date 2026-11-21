"""A bounded, offline Responses fixture server for real Codex clients."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

REFUSALS = {
    "hosted": (
        400,
        "invalid_request_error",
        "Hosted tools require allow_non_zdr=true.",
    ),
    "subresource": (
        400,
        "unsupported_operation",
        "This source supports only POST /v1/responses.",
    ),
    "unreported": (
        403,
        "unreported_cost",
        "Set costs.on_unreported_cost=allow and restart the proxy.",
    ),
    "unreported400": (
        400,
        "invalid_request_error",
        "Set costs.on_unreported_cost=allow and restart the proxy.",
    ),
    "zdr": (
        400,
        "zdr_unavailable",
        "No eligible endpoint. Inspect the model or set allow_non_zdr=true.",
    ),
    "cap": (429, "spend_cap_exceeded", "The proxy spend cap has been reached."),
    "cap_native": (
        429,
        "spend_cap_exceeded",
        "daily spend cap reached: $1.00 / $1.00. Adjust with: forge proxy set <id> costs.caps.per_day=<amount>",
    ),
}
MARKER = "FORGE_FIXTURE_173"
CALL_ID = "call_fixture_read"
MAX_BODY_BYTES = 8 * 1024 * 1024
UUID_TEXT = re.compile(r"[\da-fA-F]{8}-(?:[\da-fA-F]{4}-){3}[\da-fA-F]{12}")


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()


def request_items(body: dict) -> list[dict]:
    return [item for item in (body.get("input") or []) if isinstance(item, dict)]


def text_of(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(text_of(item) for item in value)
    if isinstance(value, dict):
        return text_of(value.get("text", value.get("content", "")))
    return ""


def tools_in(items: list, namespace: str = ""):
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("type") or "")
        yield namespace, name, item.get("type")
        yield from tools_in((item.get("tools") or []), name)


def groups_of_tools(body: dict):
    yield (body.get("tools") or [])
    for item in request_items(body):
        if item.get("type") == "additional_tools":
            yield (item.get("tools") or [])


def capture_shape(body: dict) -> dict:
    items = request_items(body)
    tools = [tool for group in groups_of_tools(body) for tool in tools_in(group)]
    outputs = [
        i
        for i in items
        if i.get("type")
        in (
            "function_call_output",
            "custom_tool_call_output",
            "local_shell_call_output",
        )
    ]
    messages = [text_of(i) for i in items if i.get("role") == "user"]
    return {
        "keys": sorted(body),
        "model": body.get("model"),
        "top_tool_types": sorted({t.get("type", "") for t in (body.get("tools") or []) if isinstance(t, dict)}),
        "tool_types": sorted({t for _, _, t in tools if t}),
        "function_names": [f"{ns}.{n}" if ns else n for ns, n, t in tools if t == "function"],
        "custom_names": [f"{ns}.{n}" if ns else n for ns, n, t in tools if t == "custom"],
        "additional_tools": any(i.get("type") == "additional_tools" for i in items),
        "hosted_web_search": any(t in ("web_search", "web_search_preview") for _, _, t in tools),
        "metadata_keys": sorted(body.get("client_metadata") or {}),
        "reasoning_keys": sorted(body.get("reasoning") or {}),
        "text_keys": sorted(body.get("text") or {}),
        "stream": body.get("stream"),
        "store": body.get("store"),
        "previous_response_id_present": body.get("previous_response_id") is not None,
        "item_types": [i.get("type", "message") for i in items],
        "fixture_call": any(
            i.get("type") in ("function_call", "custom_tool_call") and i.get("call_id") == CALL_ID for i in items
        ),
        "fixture_result": any(i.get("call_id") == CALL_ID and MARKER in text_of(i.get("output")) for i in outputs),
        "fixture_output_received": any(i.get("call_id") == CALL_ID for i in outputs),
        "followup": any("FORGE_FOLLOWUP" in msg for msg in messages),
        "title_request": bool(messages and messages[-1].startswith("Generate a concise, single-line task title")),
        "compaction_prompt": bool(messages and "CONTEXT CHECKPOINT COMPACTION" in messages[-1]),
        "compacted_history": any("FORGE_COMPACT_SUMMARY" in text_of(i) for i in items),
        "user_messages": len(messages),
    }


def synthetic_body(
    body: dict, *, preserve_probe_markers: bool = False, identifiers: dict[str, int] | None = None
) -> dict:
    """Remove client prose and volatile identifiers, retaining wire structure and tool schemas."""
    numbers = {} if identifiers is None else identifiers

    def synthetic_uuid(match: re.Match) -> str:
        value = match.group(0)
        original = UUID(value)
        # Visible fixture sequence numbers keep linked references equal without retaining real ID material.
        sequence = numbers.setdefault(value, len(numbers) + 1)
        data = bytearray(16)
        data[10:] = sequence.to_bytes(6, "big")
        if original.version == 7:
            # Replace the real creation time while keeping the observed UUIDv7 wire shape.
            data[:6] = (1_700_000_000_000).to_bytes(6, "big")
        data[6] = (data[6] & 15) | ((original.version or 4) << 4)
        data[8] = (data[8] & 63) | 128
        return str(UUID(bytes=bytes(data)))

    def metadata(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {k: metadata(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [metadata(v, key) for v in value]
        if key == "turn_started_at_unix_ms":
            return 1_700_000_000_000
        if not isinstance(value, str):
            return value
        if key == "x-codex-turn-metadata":
            return json_bytes(metadata(json.loads(value))).decode()
        if re.fullmatch(UUID_TEXT.pattern + r"(?::[0-9]+)?", value):
            return UUID_TEXT.sub(synthetic_uuid, value)
        if key == "agent_name":
            return "/synthetic/bin/codex"
        safe = {
            "history_initialization": {"new", "cold_resume"},
            "model": {"openai/gpt-6.2-astra", "google/gemini-4-carbon"},
            "reasoning_effort": {"low"},
            "request_kind": {"turn"},
            "sandbox": {"seatbelt"},
            "sandbox_mode": {"read-only", "workspace-write"},
            "thread_source": {"thread_title", "user"},
            "turn_trigger": {"exec", "user"},
        }
        return value if value in safe.get(key, set()) else "fixture"

    def redact(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            if key == "client_metadata":
                return metadata(value)
            return {k: redact(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [redact(item, key) for item in value]
        if not isinstance(value, str):
            return value
        if key in {"instructions", "description", "title", "text", "content", "output"}:
            if preserve_probe_markers and key in {"text", "content", "output"}:
                for marker in (MARKER, "CONTEXT CHECKPOINT COMPACTION", "FORGE_COMPACT_SUMMARY", "FORGE_FOLLOWUP"):
                    if marker in value:
                        if marker == MARKER and value.startswith('{"chunk_id":'):
                            return json_bytes(
                                {
                                    "chunk_id": "f1a2b3",
                                    "wall_time_seconds": 0.01,
                                    "exit_code": 0,
                                    "original_token_count": 5,
                                    "output": MARKER + "\n",
                                }
                            ).decode()
                        return marker
            if MARKER in value and key == "output":
                return MARKER
            return "Synthetic fixture."
        if key in {
            "id",
            "call_id",
            "prompt_cache_key",
            "session_id",
            "thread_id",
            "previous_response_id",
        }:
            if re.fullmatch(r"(?:[A-Za-z]{1,8}_)?" + UUID_TEXT.pattern, value):
                return UUID_TEXT.sub(synthetic_uuid, value)
            if value.startswith(
                (
                    "msg_fixture_",
                    "fc_fixture_",
                    "ctc_fixture_",
                    "call_fixture_",
                    "resp_fixture_",
                )
            ):
                return value
            return "fixture_" + hashlib.sha256(value.encode()).hexdigest()[:12]
        if key == "encrypted_content":
            return "synthetic-opaque-item"
        if key == "arguments":
            return json.dumps({"cmd": "cat fixture.txt"}) if "cat fixture.txt" in value else "{}"
        return value

    return redact(body)


def read_tool(body: dict) -> dict | None:
    """Only this fixed, read-only command may be emitted by the synthetic server."""
    forms = {
        "exec_command": {"cmd": "cat fixture.txt"},
        "shell_command": {"command": "cat fixture.txt"},
        "shell": {"command": ["cat", "fixture.txt"]},
    }
    for group in groups_of_tools(body):
        for namespace, name, kind in tools_in(group):
            if kind == "function" and name in forms:
                item = {
                    "type": "function_call",
                    "id": "fc_fixture_read",
                    "call_id": CALL_ID,
                    "name": name,
                    "arguments": json.dumps(forms[name]),
                    "status": "completed",
                }
                if namespace:
                    item["namespace"] = namespace
                return item
            if (namespace, name, kind) == ("functions", "exec", "custom"):
                return {
                    "type": "custom_tool_call",
                    "id": "ctc_fixture_read",
                    "call_id": CALL_ID,
                    "name": name,
                    "namespace": namespace,
                    "input": 'text(await tools.exec_command({cmd:"cat fixture.txt"}))',
                    "status": "completed",
                }
    return None


def assistant_message(text: str, number: int) -> dict:
    return {
        "type": "message",
        "id": f"msg_fixture_{number}",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def reply(body: dict, number: int, item: dict, tokens: int) -> tuple[str, bytes]:
    response = {
        "id": f"resp_fixture_{number}",
        "object": "response",
        "model": body.get("model"),
        "status": "completed",
        "output": [item],
        "usage": {
            "input_tokens": tokens,
            "output_tokens": 2,
            "total_tokens": tokens + 2,
            "input_tokens_details": {"cached_tokens": 0},
        },
    }
    if not body.get("stream"):
        return "application/json", json_bytes(response)
    events: list[dict[str, Any]] = [
        {
            "type": "response.created",
            "response": {**response, "output": [], "status": "in_progress"},
        },
        {"type": "response.output_item.added", "output_index": 0, "item": item},
    ]
    if item["type"] == "message":
        events.append(
            {
                "type": "response.output_text.delta",
                "item_id": item["id"],
                "output_index": 0,
                "content_index": 0,
                "delta": item["content"][0]["text"],
            }
        )
    events.extend(
        [
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": response},
        ]
    )
    stream = b"".join(b"event: " + e["type"].encode() + b"\ndata: " + json_bytes(e) + b"\n\n" for e in events)
    return "text/event-stream", stream


class ResponsesStub:
    def __init__(self, case_dir: Path, scenario: str = "normal", max_requests: int = 12):
        if scenario not in {"normal", "compaction", *REFUSALS}:
            raise ValueError(f"Unknown scenario {scenario}")
        if max_requests < 1:
            raise ValueError("A positive request ceiling is required")
        self.case_dir = Path(case_dir)
        self.scenario = scenario
        self.max_requests = max_requests
        self.records: list[dict] = []
        self._lock = threading.Lock()
        self._start = time.monotonic()
        self._counter = 0
        self._identifiers: dict[str, int] = {}

    def __enter__(self):
        self.case_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def dispatch(self):
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 <= size <= MAX_BODY_BYTES:
                        self.send_error(413)
                        return
                    data = self.rfile.read(size)
                    body = json.loads(data) if data else {}
                    if not isinstance(body, dict):
                        raise ValueError("Expected JSON object")
                    status, mime, payload = owner.respond(self.command, self.path, body)
                except (ValueError, UnicodeError):
                    self.send_error(400)
                    return
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(payload)))
                if status == 429 and owner.scenario == "cap_native":
                    self.send_header("X-Request-ID", "fixture-capped-request")
                    self.send_header("X-Spend-Warning", REFUSALS["cap_native"][2])
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            do_GET = do_POST = do_DELETE = dispatch

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self._server.server_port}/v1"
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._thread.join()
        self._server.server_close()

    def respond(self, method: str, url: str, body: dict) -> tuple[int, str, bytes]:
        parsed = urlsplit(url)
        with self._lock:
            self._counter += 1
            number = self._counter
            record = {
                "method": method,
                "path": parsed.path,
                "query_keys": sorted(parse_qs(parsed.query)),
                "elapsed_s": round(time.monotonic() - self._start, 3),
            }
            shape = capture_shape(body) if number <= self.max_requests else {}
            if body and number <= self.max_requests:
                record["shape"] = shape
                name = f"request-{number:02}.json"
                (self.case_dir / name).write_bytes(
                    json_bytes(synthetic_body(body, identifiers=self._identifiers)) + b"\n"
                )
                raw_dir = self.case_dir / "private-raw"
                raw_dir.mkdir(mode=0o700, exist_ok=True)
                (raw_dir / name).write_bytes(json_bytes(body) + b"\n")
                record["fixture"] = name
            status, mime, payload, sent = self._response(method, parsed.path, body, shape, number)
            record.update(status=status, sent=sent)
            self.records.append(record)
            with (self.case_dir / "requests.jsonl").open("ab") as output:
                output.write(json_bytes(record) + b"\n")
            return status, mime, payload

    def _response(self, method, path, body, shape, number):
        if number > self.max_requests:
            return (
                400,
                "application/json",
                json_bytes({"error": {"message": "FORGE_STUB_LIMIT"}}),
                "limit",
            )
        if method == "GET" and path in {"/v1/models", "/models"}:
            return (
                404,
                "application/json",
                json_bytes({"error": {"message": "No fixture catalog"}}),
                "catalog",
            )
        if self.scenario in REFUSALS:
            status, code, message = REFUSALS[self.scenario]
            marker = f"FORGE_REFUSAL_{self.scenario.upper()}"
            payload = {"error": {"type": code, "code": code, "message": f"{marker}: {message}"}}
            if self.scenario == "cap":
                payload = {
                    "type": "error",
                    "error": {"type": code, "message": f"{marker}: {message}"},
                }
            elif self.scenario == "cap_native":
                payload = {"type": "error", "error": {"type": code, "message": message}}
            return status, "application/json", json_bytes(payload), "refusal"
        if method == "POST" and path.endswith("/responses/compact"):
            out = {
                "id": "resp_fixture_compact",
                "object": "response.compaction",
                "output": [],
            }
            return 200, "application/json", json_bytes(out), "compaction"
        if method != "POST" or path != "/v1/responses":
            return (
                404,
                "application/json",
                json_bytes({"error": {"message": "Unknown fixture path"}}),
                "unsupported",
            )

        if shape["title_request"]:
            title = json_bytes({"title": "Read fixture"}).decode()
            mime, payload = reply(body, number, assistant_message(title, number), 10)
            return 200, mime, payload, "title"
        sent = "done"
        item = assistant_message("FORGE_PROBE_DONE", number)
        if self.scenario == "compaction":
            # A single over-limit completion triggers ordinary Codex compaction, then permits it to finish.
            tokens = 10 if any(r["path"] == path and r["sent"] != "title" for r in self.records) else 200_000
            if shape["compaction_prompt"]:
                sent = "compaction-reply"
                item = assistant_message("FORGE_COMPACT_SUMMARY", number)
            elif shape["followup"]:
                sent = "followup"
                item = assistant_message("FORGE_FOLLOWUP_DONE", number)
        else:
            tokens = 10
            if shape["followup"]:
                sent = "followup"
                item = assistant_message("FORGE_FOLLOWUP_DONE", number)
            elif not any(r["sent"] == "tool" for r in self.records):
                tool = read_tool(body)
                if tool is not None:
                    item, sent = tool, "tool"
                else:
                    item, sent = (
                        assistant_message("FORGE_TOOL_UNAVAILABLE", number),
                        "tool-unavailable",
                    )
            elif not shape["fixture_result"]:
                item, sent = (
                    assistant_message("FORGE_TOOL_RESULT_MISSING", number),
                    "tool-result-missing",
                )
        mime, payload = reply(body, number, item, tokens)
        return 200, mime, payload, sent


def export_fixtures(capture: Path, output: Path, public_path: Path) -> None:
    """Write synthetic replay candidates to a private staging directory for sanitize.sh."""
    groups: dict[tuple[str, str], list[tuple[Path, dict]]] = {}
    identifiers: dict[str, int] = {}
    for case in sorted(capture.glob("*__disabled__normal")):
        for record in json.loads((case / "requests.json").read_bytes()):
            if record["sent"] not in {"tool", "title"}:
                continue
            source = case / "private-raw" / record["fixture"]
            body = synthetic_body(json.loads(source.read_bytes()), identifiers=identifiers)
            # The model name (including its copy in serialized metadata) and UUIDs vary across runs.
            canonical = UUID_TEXT.sub("UUID", json.dumps(body, sort_keys=True)).replace(body["model"], "MODEL")
            groups.setdefault((record["sent"], canonical), []).append((source, body))

    fixture_dir = output / "fixtures"
    fixture_dir.mkdir(parents=True)
    replay, offline = [], []
    foreground = 0
    for (purpose, _), group in groups.items():
        choices = {source.parent.parent.name: (source, body) for source, body in group}
        # Exercise both slugs for older clients whose sanitized request layouts are otherwise identical.
        prefer_astra = purpose == "title" or foreground % 2 == 0
        if purpose == "tool":
            foreground += 1
        source, body = next((v for v in choices.values() if ("astra" in v[1]["model"]) == prefer_astra), group[0])
        replay.append(write_fixture(source, body, purpose, fixture_dir, public_path, sorted(choices)))

    compaction_case = "0.170.0__tui__gpt-6.2-astra__disabled__compaction"
    controls = (
        ("0.170.0__tui__gemini-4-carbon__default__normal", "tool", "hosted-control", "hosted_web_search"),
        ("0.161.0__exec__gemini-4-carbon__disabled__normal", "done", "function-output", "fixture_result"),
        ("0.170.0__exec__gpt-6.2-astra__disabled__normal", "done", "custom-output", "fixture_result"),
        (compaction_case, "compaction-reply", "compaction-prompt", "compaction_prompt"),
        (compaction_case, "followup", "compacted-followup", "compacted_history"),
    )
    for case_name, sent, purpose, required_flag in controls:
        case = capture / case_name
        record = next(r for r in json.loads((case / "requests.json").read_bytes()) if r["sent"] == sent)
        source = case / "private-raw" / record["fixture"]
        body = synthetic_body(
            json.loads(source.read_bytes()), preserve_probe_markers=purpose != "hosted-control", identifiers=identifiers
        )
        if not capture_shape(body)[required_flag]:
            raise ValueError(f"Missing wire evidence for {purpose}.")
        offline.append(write_fixture(source, body, purpose, fixture_dir, public_path, [case.name]))
    index = {
        "source_stage": "50-loopback",
        "grouping": "One representative for each complete synthetic foreground or title request body, "
        "ignoring the model slug and client UUIDs. Source cases list equivalent bodies. "
        "Hosted web, linked tool outputs and local compaction examples are for offline inspection only.",
        "replay_creations": sum(2 if spec["purpose"] == "tool" else 1 for spec in replay),
        "replay_fixtures": replay,
        "offline_fixtures": offline,
    }
    (output / "fixture-index.json").write_text(json.dumps(index, indent=2) + "\n")


def write_fixture(
    source: Path, body: dict, purpose: str, dest: Path, public_path: Path, equivalents: list[str]
) -> dict:
    version, frontend, model, _, _ = source.parent.parent.name.split("__")
    filename = f"{version}-{frontend}-{model}-{purpose}.json"
    encoded = (json.dumps(body, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode()
    (dest / filename).write_bytes(encoded)
    return {
        "path": (public_path / "fixtures" / filename).as_posix(),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "purpose": purpose,
        "model": body["model"],
        "codex_version": version,
        "case": source.parent.parent.name,
        "source_request": source.name,
        "source_cases": equivalents,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Export synthetic fixtures to a new private folder before sanitize.sh."
    )
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("public_path", type=Path, help="Repository-relative evidence path to record in the index")
    args = parser.parse_args()
    export_fixtures(args.capture, args.output, args.public_path)
