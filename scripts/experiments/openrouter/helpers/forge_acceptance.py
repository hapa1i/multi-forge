"""Run two native TUI turns per model through a saved Forge proxy, with counted egress."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from contextlib import contextmanager, nullcontext
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from codex_matrix import MODELS, child_env, run_tui
from paid_codex import PROMPTS, READ, WRITE, require_local_tools, verify_tool
from paid_guard import LEDGER_ROOT, Ledger, Upstream, dump
from paid_selftest import FixtureServer, FixtureUpstream
from responses_stub import MARKER, capture_shape

from forge.proxy.sse_framing import SseJsonDataFramer


def require(ok, message):
    if not ok:
        raise ValueError(message)


@contextmanager
def serving(server):
    with server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/api/v1"
        finally:
            server.shutdown()
            thread.join()


class AcceptanceUpstream(Upstream):
    def __init__(self, manifest, ledger, deadline, key, fixture):
        super().__init__(manifest, ledger, "tui", deadline, key)
        self.fixture = fixture
        self.model = None
        self.lookup_id = None
        self.lookups = []
        self.generations = []
        self.refusals = []

    def _connect(self, timeout):
        if self.fixture:
            return http.client.HTTPConnection("127.0.0.1", self.fixture.server_port, timeout=timeout)
        return super()._connect(timeout)

    def forward_create(self, handler, raw):
        require(not self.refusals, "Acceptance stopped after a previous upstream failure")
        body = json.loads(raw)
        require(
            handler.path == "/api/v1/responses" and self.model in MODELS and body.get("model") == self.model,
            "Unexpected route or model",
        )
        require(
            body.get("store") is False and body.get("stream") is True and body.get("provider", {}).get("zdr") is True,
            "Expected a stateless ZDR stream",
        )
        require(
            not {"client_metadata", "prompt_cache_key", "models", "previous_response_id"}.intersection(body),
            "Unexpected routing, identifier or state",
        )
        require(handler.headers.get("x-openrouter-metadata") == "enabled", "Missing routing metadata header")
        require_local_tools(body)
        self.ledger.reserve(self.stage, "generation", "responses")
        conn = self._connect(min(60, self.remaining()))
        timer = None
        row = {
            "model": self.model,
            "kind": "title" if capture_shape(body)["title_request"] else "turn",
            "cost": None,
            "generation_id": None,
            "openai_beta": handler.headers.get("openai-beta"),
        }
        inputs = [item for item in body.get("input", []) if isinstance(item, dict)]
        outputs = {
            item.get("call_id"): item.get("output")
            for item in inputs
            if item.get("type") in ("function_call_output", "custom_tool_call_output")
        }
        calls = [
            item
            for item in inputs
            if item.get("type") in ("function_call", "custom_tool_call") and item.get("call_id") in outputs
        ]
        row["read_result_observed"] = any(
            verify_tool(call, READ) and MARKER in str(outputs[call["call_id"]]) for call in calls
        )
        row["write_result_observed"] = any(verify_tool(call, WRITE) for call in calls)
        row["encrypted_reasoning_replayed"] = any(
            item.get("type") == "reasoning" and bool(item.get("encrypted_content")) for item in inputs
        )
        self.generations.append(row)

        def observe(event):
            if isinstance(event, dict) and event.get("type") in ("response.completed", "response.incomplete"):
                data = event.get("response") or {}
                row["cost"] = (data.get("usage") or {}).get("cost")

        framer = SseJsonDataFramer(observe)
        try:
            conn.connect()
            sock = conn.sock
            require(sock is not None, "Cannot bound the upstream socket")

            def expire():
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            timer = threading.Timer(self.remaining(), expire)
            timer.start()
            headers = {
                k: v
                for k, v in handler.headers.items()
                if k.lower()
                in ("authorization", "content-type", "openai-beta", "x-openrouter-metadata", "user-agent", "accept")
            }
            conn.request("POST", handler.path, raw, headers)
            upstream = conn.getresponse()
            row["status"] = upstream.status
            if upstream.status != 200:
                self.refusals.append(f"Generation returned HTTP {upstream.status}")
            row["generation_id"] = upstream.getheader("x-generation-id")
            handler.send_response(upstream.status)
            for name, value in upstream.getheaders():
                if name.lower() not in (
                    "connection",
                    "transfer-encoding",
                    "content-length",
                    "server",
                    "date",
                    "set-cookie",
                ):
                    handler.send_header(name, value)
            handler.end_headers()
            handler.response_started = True
            while chunk := upstream.read1(65536):
                framer.feed(chunk)
                handler.wfile.write(chunk)
                handler.wfile.flush()
            if row["cost"] is None:
                self.refusals.append("Generation ended without terminal cost")
        finally:
            if timer:
                timer.cancel()
            conn.close()


def gateway(api):
    class Handler(BaseHTTPRequestHandler):
        response_started = False

        def do_POST(self):
            try:
                require(self.headers.get("authorization") == f"Bearer {api.key}", "Incorrect proxy credential")
                api.forward_create(self, self.rfile.read(int(self.headers["content-length"])))
            except (OSError, ValueError, http.client.HTTPException) as exc:
                api.refusals.append(type(exc).__name__ + ": " + str(exc))
                if self.response_started:
                    self.close_connection = True
                else:
                    self.send_error(400)

        def do_GET(self):
            try:
                target = urlsplit(self.path)
                remote_id = parse_qs(target.query).get("id")
                require(
                    self.headers.get("authorization") == f"Bearer {api.key}"
                    and target.path == "/api/v1/generation"
                    and remote_id == [api.lookup_id]
                    and api.lookup_id
                    and sum(r["id"] == api.lookup_id for r in api.lookups) < 3,
                    "Unapproved metadata lookup",
                )
                status, _, raw = api.request("generation", remote_id=api.lookup_id)
                api.lookups.append({"id": api.lookup_id, "status": status})
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(raw)
            except (OSError, ValueError) as exc:
                api.refusals.append(type(exc).__name__ + ": " + str(exc))
                self.send_error(400)

        def log_message(self, fmt, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def sha256(path):
    with path.open("rb") as src:
        return hashlib.file_digest(src, "sha256").hexdigest()


def exercise_tuis(api, root, binary, forge, proxy_id, forge_home, receipt):
    for role, slug in api.manifest["models"].items():
        case = root / role
        case.mkdir()
        native = child_env(case, binary)
        native.update(FORGE_HOME=forge_home, PYTHON_DOTENV_DISABLED="1")
        work = case / "work"
        (work / "fixture.txt").write_text(MARKER + "\n")
        (case / "codex/config.toml").write_text(
            'check_for_update_on_startup=false\ncli_auth_credentials_store="file"\n[analytics]\nenabled=false\n[feedback]\nenabled=false\n[projects.'
            + json.dumps(str(work))
            + ']\ntrust_level="trusted"\n'
        )
        api.model = slug
        args = [
            forge,
            "codex",
            "start",
            "--proxy",
            proxy_id,
            "--",
            *(["-m", slug] if role == "alternate" else []),
            "-a",
            "never",
        ]
        outcome = run_tui(args, "acceptance", case, work, native, int(min(270, api.remaining())), prompts=PROMPTS)
        proof = work / "proof.txt"
        receipt["models"][slug] = {
            "stop": outcome["stop"],
            "followup_sent": outcome["followup_sent"],
            "fallback_metadata_warning": outcome["fallback_metadata_warning"],
            "edit_verified": proof.is_file() and proof.read_text().strip() == MARKER,
        }
        require(
            outcome["stop"] == "turn_ended" and outcome["followup_sent"] and receipt["models"][slug]["edit_verified"],
            f"Unverified scratch edit for {slug}",
        )
        require(
            not api.refusals and all(r.get("status") == 200 and r["cost"] is not None for r in api.generations),
            "Refused, failed or unpriced create",
        )


def verify_accounting(api, cli, proxy_id, receipt):
    cost_view = cli("telemetry", "costs", "show", proxy_id, "--by-model", as_json=True)["by_model"]
    live_metrics = cli("proxy", "metrics", proxy_id, as_json=True)
    metrics = live_metrics.get("metrics", live_metrics)
    require(set(cost_view) == set(MODELS), "Unexpected cost model totals")
    trace_rows = cli("telemetry", "trace", "list", as_json=True)
    for slug in MODELS:
        generates = [r for r in api.generations if r["model"] == slug]
        require(
            any(r["read_result_observed"] for r in generates) and any(r["write_result_observed"] for r in generates),
            "Missing matched read or edit continuation",
        )
        require(
            len(generates) == cost_view[slug]["requests"] and len(generates) == metrics["by_model"][slug]["requests"],
            "Attempt counts differ",
        )
        traces = {r["provider_generation_id"]: r for r in trace_rows if r["mapped_model"] == slug}
        require(len(traces) == len(generates), "Generation identities or traces missing")
        for dispatch in generates:
            local_trace = traces.get(dispatch["generation_id"])
            require(local_trace and local_trace["reported_cost_micros"] is not None, "Missing trace charge")
            raw_micros = Decimal(str(dispatch["cost"])) * 1_000_000
            require(abs(raw_micros - local_trace["reported_cost_micros"]) <= Decimal("0.5"), "Request cost differs")
        local = cost_view[slug]["cost_micros"]
        require(sum(t["reported_cost_micros"] for t in traces.values()) == local, "Trace and model totals differ")
        primary = next(r for r in generates if r["kind"] == "turn")
        request_id = traces[primary["generation_id"]]["request_id"]
        trace = cli("telemetry", "trace", "show", request_id, as_json=True)
        explain = cli("telemetry", "trace", "explain", request_id, as_json=True)
        require(trace["mapped_model"] == slug and trace["selected_provider"] and explain, "Incomplete dispatch trace")
        api.lookup_id = trace["provider_generation_id"]
        for delay in (0, 4, 12):
            require(api.remaining() > delay, "Deadline before reconciliation")
            time.sleep(delay)
            entry = cli("model", "backend", "reconcile", "openrouter", "--request-id", request_id, as_json=True)[
                "entries"
            ][0]
            if entry["bucket"] == "joined":
                break
            require(entry["bucket"] == "missing-remote" and api.lookups[-1]["status"] == 404, "Unable to reconcile")
        require(
            entry["bucket"] == "joined"
            and entry["remote_cost_micros"] is not None
            and abs(entry["local_cost_micros"] - entry["remote_cost_micros"]) <= 1,
            "Remote charge unavailable or inconsistent",
        )
        receipt["models"][slug].update(
            read_and_edit_matched=True,
            attempts=len(generates),
            cost_micros=local,
            selected_provider=trace["selected_provider"],
            request_id=request_id,
            reconcile=entry["bucket"],
            lookup_statuses=[r["status"] for r in api.lookups if r["id"] == api.lookup_id],
        )
    require(
        sum(row["cost_micros"] for row in cost_view.values()) == metrics["costs"]["total_micros"],
        "Metrics and local ledger totals differ",
    )


def perform(api, root, binary, base, receipt):
    forge = str(Path(sys.executable).with_name("forge"))
    env = child_env(root, binary)
    proxy_id = "codex-acceptance"
    env.update(
        FORGE_HOME=str(root / "forge"),
        PYTHON_DOTENV_DISABLED="1",
        FORGE_DEBUG="1",
        OPENROUTER_API_KEY=api.key,
        OPENROUTER_BASE_URL=base,
    )
    template = api.manifest["template"]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    address = f"http://127.0.0.1:{port}"

    def cli(*args, as_json=False):
        result = subprocess.run(
            [forge, *args, *(["--json"] if as_json else [])],
            env=env,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=min(35, api.remaining()),
            check=True,
        )
        return json.loads(result.stdout) if as_json else result.stdout

    cli("proxy", "create", template, "--name", proxy_id, "--port", str(port), "--base-url", base, "--no-start")
    cli("proxy", "set", proxy_id, "costs.caps.per_day=0.50")
    try:
        cli("proxy", "start", proxy_id)
        live = httpx.get(address, trust_env=False).json()
        policy = live["runtime"]["responses_policy"]
        costs = live["metrics"]["costs"]
        require(
            live["is_proxy"]
            and live["proxy"]["proxy_id"] == proxy_id
            and live["template"] == template
            and costs["on_cap_hit"] == "reject"
            and costs["caps"]["daily"]["limit_usd"] == 0.5
            and policy["on_unreported_cost"] == "reject"
            and policy["required_zdr"]
            and policy["requested_default_model"] == MODELS[0],
            "Unexpected live proxy policy",
        )
        receipt["proxy"] = {
            "id": proxy_id,
            "template": template,
            "cost_scope": policy["cost_scope"],
            "cap_usd": 0.5,
            "required_zdr": True,
        }
        exercise_tuis(api, root, binary, forge, proxy_id, env["FORGE_HOME"], receipt)
        api.model = None
        paths = Counter()
        for log in (Path(env["FORGE_HOME"]) / "logs/proxy").glob("proxy.*.log*"):
            for path, method in re.findall(
                r" (/[^ ]*) \[[^\]\s]+\] (GET|POST|DELETE)$", log.read_text(errors="replace"), re.MULTILINE
            ):
                paths[f"{method} {path}"] += 1
        require(paths["POST /v1/responses"] == len(api.generations), "Client and provider create counts differ")
        receipt["ingress"] = dict(paths)
        receipt["catalog_requests"] = sum(n for path, n in paths.items() if path.endswith("/models"))
        verify_accounting(api, cli, proxy_id, receipt)
    finally:
        subprocess.run(
            [forge, "proxy", "stop", proxy_id], env=env, cwd=root, capture_output=True, timeout=12, check=True
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--selftest", action="store_true")
    mode.add_argument("--approved-sha256")
    args = parser.parse_args()
    raw = args.manifest.read_bytes()
    manifest = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    binary = args.binary.resolve()
    require(sha256(binary) == manifest["binary"]["sha256"] and binary.name == "codex", "Codex binary digest mismatch")
    pin = manifest["prerequisite"]
    require(sha256(args.manifest.parent / pin["path"]) == pin["sha256"], "Stage 80 receipt mismatch")
    require(
        manifest["origin"] == "https://openrouter.ai"
        and tuple(manifest["models"].values()) == MODELS
        and tuple(p + " " + manifest["tool_instruction"] for p in manifest["prompts"]) == PROMPTS
        and manifest["fixture_value"] == MARKER,
        "Manifest does not describe this native task",
    )
    require(
        manifest["ledger_root"] == LEDGER_ROOT
        and manifest["template"] == "codex-responses-openrouter"
        and manifest["forge_cap"] == {"per_day_usd": 0.5, "on_cap_hit": "reject", "on_unreported_cost": "reject"}
        and manifest["limits"]
        == {
            "usd": 5,
            "seconds": 900,
            "generation_attempts": 16,
            "metadata_attempts": 7,
            "stage_attempts": {"tui": {"generation": 16, "metadata": 7}},
        },
        "Unsupported acceptance limits",
    )
    require(not args.output.exists(), "Choose a new receipt path")
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="forge-responses-acceptance-") as scratch:
        root = Path(scratch).resolve()
        fixture = None
        if args.selftest:
            fixture = FixtureServer(("127.0.0.1", 0), FixtureUpstream)
            fixture.key_limit, fixture.native_tui = 5, True
            fixture.hits, fixture.get_paths = [], []
            key = "selftest-loopback"
            ledger_dir = root / "ledger"
        else:
            require(args.approved_sha256 == digest, "Operator approval must match the full manifest SHA-256")
            key = os.environ["OPENROUTER_PROBE_API_KEY"]
            require(bool(key), "A dedicated acceptance key is required")
            ledger_dir = Path(LEDGER_ROOT).expanduser() / digest
        with serving(fixture) if fixture else nullcontext():
            ledger = Ledger(ledger_dir, manifest["limits"], stage_order=("tui",))
            api = AcceptanceUpstream(manifest, ledger, ledger.begin("tui"), key, fixture)
            receipt = {
                "mode": "loopback" if fixture else "paid",
                "manifest_sha256": digest,
                "binary": manifest["binary"],
                "models": {},
                "verdict": "failed",
            }
            try:
                receipt["credit"] = api.validate_credit_limit()
                require(receipt["credit"]["usd_remaining"] >= 3, "At least $3 of dedicated credit is required")
                with serving(gateway(api)) as base:
                    perform(api, root, binary, base, receipt)
                require(not api.refusals, "Unexpected egress refusal")
                receipt["verdict"] = "passed"
            finally:
                receipt["generations"] = api.generations
                with ledger.locked() as state:
                    receipt["metadata_reads"] = sum(a["kind"] == "metadata" for a in state["attempts"])
                    receipt["reserved_creates"] = sum(a["kind"] == "generation" for a in state["attempts"])
                receipt["refusals"] = api.refusals
                ledger.finish("tui", receipt["verdict"])
                dump(args.output, receipt)
    print(f"{receipt['verdict']} {digest[:8]}: {len(api.generations)} creates, {receipt['metadata_reads']} reads")


if __name__ == "__main__":
    main()
