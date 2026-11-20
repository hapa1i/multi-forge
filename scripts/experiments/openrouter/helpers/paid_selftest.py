"""Offline exercise of the paid transport, stage oracles and descendant deadline."""

from __future__ import annotations

import concurrent.futures
import hashlib
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from paid_codex import (
    PROMPTS,
    READ,
    WRITE,
    check_inputs,
    client_run,
    replay,
    stage_codex,
)
from paid_diagnostics import provider_diagnostic
from paid_guard import (
    ACCEPTED_REFUSAL,
    GUARD,
    Ledger,
    Upstream,
    dump,
    validate_manifest,
)
from paid_probe import (
    is_zdr_refusal,
    response_summary,
    run_stage,
    stage_cost,
    stage_zdr,
    tiny,
    verify_prerequisite,
)
from responses_stub import MARKER, assistant_message, capture_shape, read_tool, text_of


class FixtureServer(ThreadingHTTPServer):
    hits: list[str]
    get_paths: list[str]
    key_limit: float = 1
    force_error = False
    trickle = False
    zdr_requests: list[dict] | None = None
    zdr_models = ["stub/default"]
    account_zdr_model: str | None = None


class FixtureUpstream(BaseHTTPRequestHandler):

    def send_json(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        server = cast(FixtureServer, self.server)
        server.get_paths.append(self.path)
        if self.path.endswith("/key"):
            self.send_json(
                {
                    "data": {
                        "limit": server.key_limit,
                        "limit_remaining": server.key_limit,
                        "limit_reset": None,
                        "include_byok_in_limit": True,
                    }
                }
            )
        elif self.path.endswith("/endpoints/zdr"):
            self.send_json({"data": [{"model_id": m} for m in server.zdr_models]})
        elif self.path.startswith("/api/v1/generation?"):
            self.send_json({"data": {"id": parse_qs(urlsplit(self.path).query)["id"][0]}})
        else:
            self.send_json({}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        server = cast(FixtureServer, self.server)
        server.hits.append(self.path)
        if server.trickle:
            self.send_response(200)
            self.end_headers()
            try:
                for _ in range(40):
                    self.wfile.write(b" ")
                    time.sleep(0.05)
            except OSError:
                pass
            return
        if server.force_error:
            self.send_json(
                {
                    "error": {
                        "message": "No Responses route. Authorization: Bearer fake-credential",
                        "code": 502,
                        "metadata": {
                            "provider_name": "Fixture",
                            "raw": json.dumps(
                                {
                                    "error": {
                                        "message": "Missing endpoint for " + body["input"],
                                        "code": "no_endpoint",
                                        "input": body["input"],
                                    }
                                }
                            ),
                        },
                    }
                },
                502,
            )
            return
        if self.path == "/api/v1/chat/completions":
            return self.send_json(
                {"id": "gen-control", "choices": [{"finish_reason": "stop", "message": {"content": "OK"}}]}
            )
        if self.path != "/api/v1/responses":
            return self.send_json({}, 404)
        if server.zdr_requests is not None:
            server.zdr_requests.append(body)
        if body["model"] == server.account_zdr_model:
            return self.send_json(
                {
                    "error": {
                        "code": 404,
                        "message": "ZDR violation (account settings)",
                        "metadata": {
                            "ineligibility_reasons": [
                                {
                                    "reason": "zdr-violation-by-account",
                                    "endpoint_count": 1,
                                    "configure_url": "https://openrouter.ai/settings/privacy",
                                }
                            ]
                        },
                    }
                },
                404,
            )
        if body["model"] == "stub/excluded" and body.get("provider", {}).get("zdr"):
            return self.send_json(
                {"error": {"code": 404, "message": "No endpoints matching ZDR policy"}},
                404,
            )
        item = assistant_message(MARKER, 1)
        if isinstance(body["input"], list):
            writing = any(i.get("role") == "user" and PROMPTS[1] in text_of(i) for i in body["input"])
            title = any(
                i.get("role") == "user" and "Give this synthetic task a short title" in text_of(i)
                for i in body["input"]
            )
            if title:
                item = assistant_message(json.dumps({"title": "Read fixture"}), 1)
            template = None if title else read_tool(body)
            if template:
                if writing:
                    template["id"] += "_write"
                    template["call_id"] += "_write"
                    if template["type"] == "custom_tool_call":
                        template["input"] = template["input"].replace(READ, WRITE)
                    else:
                        template["arguments"] = template["arguments"].replace(READ, WRITE)
                if not any(
                    i.get("call_id") == template["call_id"] and i.get("type", "").endswith("_output")
                    for i in body["input"]
                ):
                    item = template
        result = {
            "id": "resp-fixture",
            "status": "completed",
            "output": [item],
            "usage": {"cost": 0},
        }
        if self.headers.get("X-OpenRouter-Metadata") == "enabled":
            result["openrouter_metadata"] = {
                "endpoints": {"available": [{"selected": True, "provider": "local", "endpoint": "loopback"}]}
            }
        if not body.get("stream"):
            return self.send_json(result)
        result.update(
            {
                "object": "response",
                "model": body.get("model"),
                "usage": {
                    "cost": 0,
                    "input_tokens": 8,
                    "output_tokens": 2,
                    "total_tokens": 10,
                },
            }
        )
        events = [
            {
                "type": "response.created",
                "response": dict(result, output=[], status="in_progress"),
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
                {"type": "response.completed", "response": result},
            ]
        )
        raw = b"".join(b"event: " + e["type"].encode() + b"\ndata: " + json.dumps(e).encode() + b"\n\n" for e in events)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args) -> None:
        pass


def check_diagnostics() -> None:
    secret = "fixture-bearer"
    error = {"message": "Provider failed on fixture-bearer", "code": "unavailable"}
    body = {"input": "private fixture prompt"}
    failed = {"status": "failed", "error": error}
    for media, wire in (
        ("application/json", json.dumps(failed).encode()),
        (
            "text/event-stream",
            b"data: " + json.dumps({"type": "response.failed", "response": failed}).encode() + b"\n\n",
        ),
        ("text/event-stream", b"data: " + json.dumps({"type": "error", **error}).encode() + b"\n\n"),
        ("text/event-stream", b"event: error\ndata: " + json.dumps(error).encode() + b"\n\n"),
    ):
        result = provider_diagnostic(200, {"content-type": media, "x-request-id": "fixture-req"}, wire, body, secret)
        if (
            not result
            or result.get("message") != "Provider failed on <redacted>"
            or result.get("request_id") != "fixture-req"
        ):
            raise ValueError(f"Lost or exposed a provider error on an HTTP 200 {media} response.")
    for media, wire in (
        ("application/json", b"not JSON: private fixture prompt"),
        ("text/html", b"<h1>private fixture prompt</h1>"),
    ):
        result = provider_diagnostic(404, {"content-type": media}, wire, body, secret)
        if not result or set(result) != {"format", "bytes", "sha256"} or result["format"] != "unparsed":
            raise ValueError("Malformed/HTML provider error leaked its body or lost its fingerprint.")
    result = provider_diagnostic(
        404, {"content-type": "text/plain"}, b"Route missing\nprivate fixture prompt", body, secret
    )
    if not result or result.get("message") != "Route missing":
        raise ValueError("Plain provider diagnostic did not preserve only the first line.")
    intro = (
        "0 endpoints out of 1 requested are available matching your guardrail restrictions and data policy. "
        "We removed them for the following reasons (an endpoint may have matched multiple reasons):"
    )
    # Synthetic continuation lines exercise extraction without assuming what a previous live 404 contained.
    allowed = [
        "1 endpoint does not support zero-data retention (ZDR).",
        "Blocked by your allowed providers list: 1 endpoint.",
        "3. Safety retention: 1/1 endpoints.",
        "Data collection: 1 endpoint.",
        "Provider allowlist: 1 endpoint.",
        "Model allowlist: 1 endpoint.",
    ]
    message = "\n".join(
        [
            intro,
            "",
            "- " + allowed[0],
            "• " + allowed[1],
            "- " + allowed[0],
            "- guardrail: fixture-bearer",
            "- data policy: private fixture prompt",
            "- guardrail: selected providers",
            "- Guardrail: Authorization: Bearer fixture-bearer",
            "- guardrail at /private/tmp/probe.py:71",
            "- guardrail settings: https://example.com/private",
            "Your guardrail has a custom annotation.",
            "unexpected continuation",
            *allowed[2:],
        ]
    )
    wire = json.dumps({"error": {"code": 404, "message": message}}).encode()
    result = provider_diagnostic(
        404, {"content-type": "application/json"}, wire, {"input": "selected providers"}, secret
    )
    if not result or result.get("message") != intro or result.get("routing_reasons") != allowed:
        raise ValueError("Routing refusal lost a policy reason or retained private or unknown continuation text.")
    for media, wire in (
        ("text/plain", message.encode()),
        ("application/json", json.dumps({"error": {"message": "Provider failed\n- " + allowed[0]}}).encode()),
    ):
        result = provider_diagnostic(404, {"content-type": media}, wire, body, secret)
        if not result or "routing_reasons" in result:
            raise ValueError("Arbitrary multiline error was treated as a structured routing refusal.")
    echoed = "line of private fixture text\nsecond private line"
    for message in ("Failed on: " + echoed, 'Rejected "api_key": "private_value_987"'):
        raw = json.dumps({"error": {"message": message}}).encode()
        result = provider_diagnostic(404, {}, raw, {"input": echoed}, secret)
        if not result or "<redacted>" not in result["message"] or "private" in result["message"]:
            raise ValueError("Credential assignment or multiline request escaped diagnostic redaction.")
    if is_zdr_refusal({"message": "No available endpoints. See https://openrouter.ai/settings/privacy?zdr=true"}):
        raise ValueError("A settings link alone must not prove ZDR enforcement.")
    if not is_zdr_refusal({"upstream": {"code": "no_zdr_endpoints"}}):
        raise ValueError("An explicit upstream ZDR routing code was lost.")
    stream = b'data: {"type":"response.completed","response":{"status":"completed"}}\n\nevent: error\ndata: {"message":"upstream failed"}\n\n'
    try:
        response_summary(200, {}, stream, True)
    except ValueError as exc:
        if "provider error event" not in str(exc):
            raise
    else:
        raise ValueError("A stream with a provider error was accepted as completed.")


def check_account_zdr(server: FixtureServer, api: Upstream, digest: str, manifest_dir: Path) -> dict:
    """Verify the complete stage-60 manifest on loopback against the historical one-word task."""
    server.zdr_models = ["openai/gpt-6.2-astra"]
    server.account_zdr_model = "qwen/qwen4-max"
    server.zdr_requests = []
    evidence: dict = {}
    try:
        api.validate_credit_limit()
        stage_zdr(api, evidence, manifest_dir=manifest_dir)
        expected = {
            "input": "Respond with the single word OK.",
            "max_output_tokens": 128,
            "store": False,
            "provider": {"zdr": True},
        }
        bodies = server.zdr_requests
        criterion = api.manifest["zdr_control"]["criterion"]
        expected_bodies = [dict(expected, model="openai/gpt-6.2-astra")]
        expected_operations = [("key", 200), ("endpoints/zdr", 200)]
        if criterion == "account_zdr":
            expected_bodies.insert(0, dict(expected, model="qwen/qwen4-max", reasoning={"effort": "none"}))
            expected_operations.append(("responses", 404))
        expected_operations.append(("responses", 200))
        if bodies != expected_bodies:
            raise ValueError("The account ZDR stage sent an unexpected request body or count.")
        if [(r["operation"], r["status"]) for r in api.observations] != expected_operations:
            raise ValueError("The account ZDR stage used unexpected operations or statuses.")
        if evidence["criterion"] != criterion or evidence["independent_request_zdr"] != "unverified":
            raise ValueError("Account enforcement was reported as independent request enforcement.")
        return {
            "manifest_sha256": digest,
            "criterion": evidence["criterion"],
            "independent_request_zdr": evidence["independent_request_zdr"],
            "historical_baseline": evidence["historical_baseline"],
            **({"accepted_refusal": evidence["accepted_refusal"]} if criterion == ACCEPTED_REFUSAL else {}),
            "requests": api.observations,
            "generation_bodies": bodies,
            "positive_status": evidence["positive"]["response"]["status"],
        }
    finally:
        server.account_zdr_model = None
        server.zdr_models = ["stub/default"]
        server.zdr_requests = None


def check_cost_codex(
    server: FixtureServer, transport: type[Upstream], manifest_path: Path, binary: Path, directory: Path
) -> dict:
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    validate_manifest(manifest)
    prerequisite = verify_prerequisite(manifest, manifest_path.parent)
    check_inputs(manifest, binary)
    ledger = Ledger(directory, manifest["limits"])
    cost = transport(manifest, ledger, "cost", ledger.begin("cost", key="dummy"), "dummy")
    cost.validate_credit_limit()
    cost_result: dict = {}
    stage_cost(cost, cost_result)
    if [r["operation"] for r in cost.observations] != [
        "key",
        *["responses"] * 4,
        "chat/completions",
        *["generation"] * 2,
    ]:
        raise ValueError("Cost controls used unexpected operations on loopback.")
    if cost_result["cost_coverage"] != {"unary": [0, 0], "stream": [0, 0]} or not cost_result["try_metadata_on_codex"]:
        raise ValueError("Cost controls lost the stub's explicit zero cost or selected streaming provider.")
    dump(directory / "cost.json", cost_result)
    ledger.finish("cost", "passed")

    codex = transport(manifest, ledger, "codex", ledger.begin("codex", key="dummy"), "dummy")
    codex.validate_credit_limit()
    codex_result: dict = {}
    server.zdr_requests = []
    try:
        with patch.dict(os.environ, {"OPENROUTER_RESPONSES_CODEX": str(binary)}):
            stage_codex(codex, codex_result)
        bodies = server.zdr_requests
    finally:
        server.zdr_requests = None
    ledger.finish("codex", "passed")
    return {
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "prerequisite": prerequisite,
        "cost": {"generation": 5, "metadata": len(cost.observations) - 5},
        **codex_report(manifest, codex_result, codex.observations, bodies),
    }


def codex_report(manifest: dict, codex_result: dict, observations: list[dict], bodies: list[dict]) -> dict:
    selected_endpoint = [{"provider": "local", "endpoint": "loopback"}]
    native = []
    for run in codex_result["client_runs"]:
        responses = [r["response"] for r in run["requests"] if "response" in r]
        if len(run["turns"]) != 2 or not all(t["verified"] for t in run["turns"]) or not responses:
            raise ValueError("A native run did not finish the scratch read, resume, and edit.")
        expected_route = selected_endpoint if run["metadata_header"] else []
        if any(r["selected_endpoints"] != expected_route for r in responses):
            raise ValueError("Native response routing evidence disagrees with the metadata header.")
        native.append({k: run[k] for k in ("model", "required_zdr", "metadata_header")} | {"creates": len(responses)})
    default = manifest["models"]["default"]
    alternate = manifest["models"]["alternate"]
    if [(r["model"], r["required_zdr"], r["metadata_header"]) for r in native] != [
        (default, False, False),
        (alternate, False, False),
        (default, True, True),
    ]:
        raise ValueError("Native controls did not exercise both raw baselines and the optional metadata run.")
    raw_creates = native[0]["creates"] + native[1]["creates"]
    if any("zdr" in (body.get("provider") or {}) for body in bodies[:raw_creates]) or any(
        (body.get("provider") or {}).get("zdr") is not True for body in bodies[raw_creates:]
    ):
        raise ValueError("Native baselines or the explicit ZDR controls sent the wrong provider settings.")

    replays = codex_result["replays"]
    if [r["fixture"] for r in replays] != manifest["replay_fixtures"]:
        raise ValueError("Stage 80 did not replay the fixtures in the approved manifest.")
    fixture_posts = {"tool": 0, "title": 0}
    for replayed in replays:
        purpose = replayed["fixture"]["purpose"]
        if not replayed.get("title_control" if purpose == "title" else "tool_replay_verified"):
            raise ValueError("Published fixture replay did not pass.")
        replies = [replayed["response"]] if purpose == "title" else [replayed["first"], replayed["followup"]]
        if any(reply["selected_endpoints"] != selected_endpoint for reply in replies):
            raise ValueError("A policy replay lacked the selected endpoint from the metadata control.")
        fixture_posts[purpose] += len(replies)
    creates = sum(r["creates"] for r in native) + sum(fixture_posts.values())
    if len(bodies) != creates or [r["operation"] for r in observations] != ["key", *["responses"] * creates]:
        raise ValueError("Codex used unexpected operations or retried a fixture on loopback.")
    return {
        "codex": {"generation": creates, "metadata": 1},
        "native_runs": native,
        "published_fixture_replays": len(replays),
        "published_fixture_posts": fixture_posts,
    }


def check_codex_only(
    server: FixtureServer, transport: type[Upstream], manifest_path: Path, binary: Path, root: Path
) -> dict:
    raw = manifest_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    manifest = json.loads(raw)
    server.key_limit = manifest["limits"]["usd"]
    server.zdr_requests = []
    native_inputs = []

    def record_native_input(body: dict) -> dict:
        # Snapshot before the bridge applies policy to the third native run.
        native_inputs.append(deepcopy(body))
        return capture_shape(body)

    env = {
        "OPENROUTER_RESPONSES_MANIFEST": str(manifest_path),
        "OPENROUTER_RESPONSES_APPROVED_SHA256": digest,
        "OPENROUTER_RESPONSES_CODEX": str(binary),
        "OPENROUTER_PROBE_API_KEY": "dummy",
    }
    with (
        patch.dict(os.environ, env),
        patch("paid_probe.LEDGER_ROOT", str(root)),
        patch("paid_probe.Upstream", transport),
        patch("paid_codex.capture_shape", side_effect=record_native_input),
    ):
        outcome = run_stage("codex")
    if outcome["verdict"] != "passed":
        raise ValueError(f"Standalone Codex loopback failed: {outcome.get('reason')}")
    receipt = json.loads(Path(outcome["result"]).read_bytes())
    report = codex_report(manifest, receipt, receipt["requests"], server.zdr_requests)
    raw_count = sum(r["creates"] for r in report["native_runs"] if not r["required_zdr"])
    baselines = server.zdr_requests[:raw_count]
    if baselines != native_inputs[:raw_count] or any("max_output_tokens" in body for body in baselines):
        raise ValueError("A native baseline changed in transit or acquired an output-token limit.")
    if server.get_paths != ["/api/v1/key"] or server.hits != ["/api/v1/responses"] * report["codex"]["generation"]:
        raise ValueError("The loopback listener received an operation outside standalone stage 80.")
    return {
        "kind": "loopback-only",
        "verdict": "passed",
        "stages": manifest["stages"],
        "manifest_sha256": digest,
        "prerequisite": receipt["prerequisite"],
        "previous_attempt": receipt["previous_attempt"],
        "simulated_credit": receipt["credit"],
        "unmodified_native_baseline_posts": raw_count,
        "native_baseline_posts_with_max_output_tokens": 0,
        "explicit_zdr_posts": len(server.zdr_requests) - raw_count,
        **report,
    }


def selftest(binary: Path | None = None, manifest_path: Path | None = None) -> dict:
    with (
        tempfile.TemporaryDirectory(prefix="forge-paid-guard-") as temp,
        FixtureServer(("127.0.0.1", 0), FixtureUpstream) as server,
    ):
        root = Path(temp)
        server.hits = []
        server.get_paths = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        class Local(Upstream):
            def _connect(self, timeout: float) -> http.client.HTTPConnection:
                return http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=timeout)

        limits = {
            "seconds": 30,
            "usd": 1,
            "generation_attempts": 2,
            "metadata_attempts": 1,
            "stage_attempts": {"zdr": {"generation": 2, "metadata": 1}},
        }
        models = {
            "default": "stub/default",
            "alternate": "stub/alternate",
            "non_zdr": "stub/excluded",
        }
        manifest = {
            "models": models,
            "limits": limits,
            "zdr_control": {"canonical_slug": "stub/excluded-dated", "reasoning_effort": "none"},
        }

        def attempt(_):
            api = Local(manifest, Ledger(root / "budget", limits), "zdr", deadline, "dummy")
            try:
                api.request("responses", tiny("stub/default"))
            except ValueError as exc:
                if "budget exhausted before dispatch" not in str(exc):
                    raise
                return False
            return True

        try:
            manifest_bytes = manifest_path.read_bytes() if manifest_path else None
            planned = json.loads(manifest_bytes) if manifest_bytes is not None else {}
            if manifest_path and planned.get("stages") == ["codex"]:
                if not binary:
                    raise ValueError("Provide --selftest-codex to exercise the pinned binary.")
                return check_codex_only(server, Local, manifest_path, binary, root)
            ledger = Ledger(root / "budget", limits)
            deadline = ledger.begin("zdr")
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                accepted = sum(pool.map(attempt, range(6)))
            count = len(server.hits)
            if accepted != 2 or count != 2:
                raise ValueError("Concurrent reservation guard failed.")
            failure = Ledger(root / "error", limits)
            failure_api = Local(manifest, failure, "zdr", failure.begin("zdr"), "dummy")
            server.force_error = True
            failed_stage: dict = {}
            try:
                stage_zdr(failure_api, failed_stage)
            except ValueError as exc:
                if "HTTP 502" not in str(exc):
                    raise
            else:
                raise ValueError("Unexpected provider error was accepted.")
            finally:
                server.force_error = False
            if len(server.hits) != count + 1:
                raise ValueError("Paid stage continued after a synthetic upstream failure.")
            diagnostic = failed_stage["baseline"]["error"]
            if (
                diagnostic != failure_api.observations[-1]["error"]
                or diagnostic["code"] != 502
                or diagnostic["message"] != "No Responses route. <redacted>"
                or diagnostic["provider"] != "Fixture"
                or diagnostic["upstream"] != {"message": "Missing endpoint for <redacted>", "code": "no_endpoint"}
            ):
                raise ValueError("Failed baseline receipt lost the provider diagnostic or exposed the echoed request.")
            check_diagnostics()
            catalog_guard = Ledger(root / "canonical", limits)
            catalog_api = Local(manifest, catalog_guard, "zdr", catalog_guard.begin("zdr"), "dummy")
            server.zdr_models = ["stub/default", "stub/excluded-dated"]
            try:
                stage_zdr(catalog_api, {})
            except ValueError as exc:
                if "catalog invalidates" not in str(exc):
                    raise
            else:
                raise ValueError("The dated canonical model had an eligible endpoint.")
            finally:
                server.zdr_models = ["stub/default"]
            timeout_ledger = Ledger(root / "timeout", limits)
            timeout_ledger.begin("zdr")
            started = time.monotonic()
            slow = Local(manifest, timeout_ledger, "zdr", started + 0.35, "dummy")
            server.trickle = True
            try:
                slow.request("responses", tiny("stub/default"))
            except (ValueError, OSError, http.client.HTTPException):
                elapsed = time.monotonic() - started
                if not 0.25 < elapsed < 1.5:
                    raise ValueError("Close-delimited trickle exceeded or missed its deadline.")
            else:
                raise ValueError("Transport accepted a stream beyond its deadline.")
            finally:
                server.trickle = False
            limits = {
                "seconds": 30,
                "usd": 1,
                "generation_attempts": 12,
                "metadata_attempts": 20,
                "stage_attempts": {
                    stage: {"generation": maximum, "metadata": 16}
                    for stage, maximum in (("zdr", 3), ("cost", 5), ("codex", 4))
                },
            }
            manifest["limits"] = limits
            ledger = Ledger(root / "stages", limits)
            for stage, function in (("zdr", stage_zdr), ("cost", stage_cost)):
                api = Local(manifest, ledger, stage, ledger.begin(stage), "dummy")
                api.validate_credit_limit()
                evidence: dict = {}
                server.zdr_requests = [] if stage == "zdr" else None
                function(api, evidence)
                if server.zdr_requests is not None:
                    baseline, refused, positive = server.zdr_requests
                    if (
                        baseline.get("reasoning") != {"effort": "none"}
                        or "reasoning" in positive
                        or refused != dict(baseline, provider={"zdr": True})
                    ):
                        raise ValueError("Paired controls must differ only in required ZDR.")
                ledger.finish(stage, "passed")
            if any(v != 0 for sample in evidence["cost_coverage"].values() for v in sample):
                raise ValueError("Reported zero lost in fixture cost records.")
            api = Local(manifest, ledger, "codex", ledger.begin("codex"), "dummy")
            sample = root / "sample.json"
            summary = []
            for schema in (
                {"type": "function", "name": "exec_command"},
                {
                    "type": "namespace",
                    "name": "functions",
                    "tools": [{"type": "custom", "name": "exec"}],
                },
            ):
                sample.write_text(
                    json.dumps(
                        {
                            "model": models["default"],
                            "stream": True,
                            "store": False,
                            "tools": [schema],
                            "input": [{"role": "user", "content": "task"}],
                        }
                    )
                )
                result = replay(api, {"path": str(sample)}, True)
                summary.append(result["tool_replay_verified"])
            native = {}
            verified_fixtures = 0
            fixture_posts = {"tool": 0, "title": 0}
            account_zdr = {}
            cost_codex = {}
            if manifest_path and manifest_bytes is not None and planned.get("stages") == ["zdr"]:
                validate_manifest(planned)
                scoped_ledger = Ledger(root / "account-zdr", planned["limits"])
                scoped = Local(planned, scoped_ledger, "zdr", scoped_ledger.begin("zdr"), "dummy")
                account_zdr = check_account_zdr(
                    server, scoped, hashlib.sha256(manifest_bytes).hexdigest(), manifest_path.parent
                )
                scoped_ledger.finish("zdr", "passed")
            elif manifest_path and planned.get("stages") == ["cost", "codex"]:
                if not binary:
                    raise ValueError("Provide --selftest-codex to exercise the approved native executable.")
                cost_codex = check_cost_codex(server, Local, manifest_path, binary, root / "cost-codex")
            elif manifest_path:
                if not binary:
                    raise ValueError("Provide --selftest-codex to validate the manifest's executable identity.")
                check_inputs(planned, binary)
                fixture_ledger = Ledger(root / "fixtures", planned["limits"])
                fixture_ledger.begin("zdr")
                fixture_ledger.finish("zdr", "passed")
                fixture_ledger.begin("cost")
                fixture_ledger.finish("cost", "passed")
                fixture_api = Local(planned, fixture_ledger, "codex", fixture_ledger.begin("codex"), "dummy")
                for spec in planned["replay_fixtures"]:
                    before = len(server.hits)
                    result = replay(fixture_api, spec, True)
                    paths = server.hits[before:]
                    key, expected = ("title_control", 1) if spec["purpose"] == "title" else ("tool_replay_verified", 2)
                    if not result.get(key) or paths != ["/api/v1/responses"] * expected:
                        raise ValueError("Published fixture replay failed its completion or creation count.")
                    fixture_posts[spec["purpose"]] += len(paths)
                    verified_fixtures += 1
            if binary and not cost_codex:
                native_limits = {
                    "seconds": 180,
                    "usd": 1,
                    "generation_attempts": 18,
                    "metadata_attempts": 1,
                    "stage_attempts": {"zdr": {"generation": 18, "metadata": 1}},
                }
                native_models = {
                    "default": "openai/gpt-6.2-astra",
                    "alternate": "google/gemini-4-carbon",
                }
                native_manifest = {
                    "models": native_models,
                    "limits": native_limits,
                    "binary": {"version": "0.170.0"},
                }
                ledger = Ledger(root / "native", native_limits)
                native_api = Local(native_manifest, ledger, "zdr", ledger.begin("zdr"), "dummy")
                for model in native_models.values():
                    proof: dict = {"client_runs": []}
                    client_run(native_api, model, True, True, proof, binary.resolve())
                    run = proof["client_runs"][0]
                    creates = [r for r in run["requests"] if "response" in r]
                    if not creates or any(
                        r["response"]["selected_endpoints"] != [{"provider": "local", "endpoint": "loopback"}]
                        for r in creates
                    ):
                        raise ValueError("Metadata header failed its native-client round trip.")
                    native[model] = {
                        "verified_turns": len(run["turns"]),
                        "requests": len(run["requests"]),
                        "scratch_edit_verified": True,
                        "metadata_header": True,
                    }
        finally:
            server.shutdown()
            thread.join()
        snippet = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True); time.sleep(60)"
        command = [
            sys.executable,
            str(GUARD),
            "run",
            "--seconds",
            "1.5",
            "--grace",
            "1",
            "--evidence",
            str(root / "guard"),
            "--",
            sys.executable,
            "-c",
            snippet,
        ]
        proc = subprocess.run(
            command,
            timeout=12,
            env={"PATH": os.defpath + ":/opt/homebrew/bin:/usr/local/bin"},
        )
        result = json.loads((root / "guard/process-result.json").read_text())
        if proc.returncode == 0 or result["remaining"] or not result["survivors_before_sweep"]:
            raise ValueError("Process-tree deadline lacked a verified descendant sweep.")
        return {
            "kind": "loopback-only",
            "attempted": 6,
            "accepted": accepted,
            "received": count,
            "canned_zdr_controls": "passed",
            **({"account_zdr": account_zdr} if account_zdr else {}),
            "unexpected_upstream_error_stops": True,
            "sanitized_provider_errors": True,
            "trickling_close_delimited_cutoff_seconds": round(elapsed, 3),
            "canned_unary_stream_metadata_cost": "passed",
            "canned_function_and_custom_tool_replay": all(summary),
            **(
                {"cost_codex": cost_codex}
                if cost_codex
                else {
                    "native": native,
                    "published_fixture_replays": verified_fixtures,
                    "published_fixture_posts": fixture_posts,
                }
            ),
            "separately_opened_ledgers": 6,
            "deadline_seconds": 1.5,
            "elapsed_seconds": result["elapsed_seconds"],
            "detached_survivors_swept": len(result["survivors_before_sweep"]),
            "remaining_processes": 0,
        }
