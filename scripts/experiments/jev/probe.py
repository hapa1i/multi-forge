#!/usr/bin/env python3
"""Prepare or execute a fixed synthetic Decisions probe manifest."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from forge.core.judgments import (
    ChoiceQuestion,
    JudgmentError,
    NoulQuestion,
    OpenRouterJudgmentClient,
    ScoreQuestion,
)
from forge.core.judgments.openrouter import (
    DEFAULT_MODEL,
    MAX_RESPONSE_BYTES,
    build_payload,
    decisions_url,
)
from forge.core.judgments.types import JudgmentResponse, Question, validate_answers
from forge.core.llm.credentials import CredentialManager
from forge.core.llm.errors import NoApiKeyError
from forge.core.reactive.env import new_root_run_identity
from forge.runtime_config import reset_runtime_config

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
PRICE_PER_TOKEN = 0.000000042
PRICE_DATE = "2026-10-14"


def cases() -> list[tuple[str, str, Question]]:
    """Return synthetic single-question controls with no repository inputs."""
    return [
        (
            "choice",
            "A support ticket reports that the checkout button does nothing.",
            ChoiceQuestion(
                instructions="Which team owns this ticket?",
                criteria={
                    "payments": "Checkout and payment failures",
                    "account": "Login and profile failures",
                },
            ),
        ),
        (
            "noul",
            "The package arrived broken and the customer requests a replacement.",
            NoulQuestion(
                instructions="Is the customer reporting damage?",
                criteria={
                    "true": "The item arrived damaged",
                    "false": "The item arrived intact",
                },
            ),
        ),
        (
            "score",
            "One customer cannot complete a purchase; the service is available to everyone else.",
            ScoreQuestion(
                instructions="How urgent is this incident?",
                criteria=[
                    "Cosmetic issue",
                    "One customer blocked",
                    "Service-wide outage",
                ],
            ),
        ),
        (
            "malformed",
            "Synthetic schema rejection control.",
            NoulQuestion(
                instructions="Is this synthetic?",
                criteria={"true": "Synthetic example", "false": "Real incident"},
            ),
        ),
    ]


def manifest() -> dict[str, Any]:
    """Return the exact four-request proposal; this function performs no credential or network I/O."""
    requests = []
    for label, state, question in cases():
        payload = build_payload(DEFAULT_MODEL, state, {"check": question})
        if label == "malformed":
            payload["questions"] = []
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        requests.append(
            {
                "label": label,
                "payload": payload,
                "sha256": hashlib.sha256(serialized.encode()).hexdigest(),
                "expected_status": 400 if label == "malformed" else 200,
            }
        )
    return {
        "schema_version": 1,
        "stage": "early",
        "endpoint": ENDPOINT,
        "model": DEFAULT_MODEL,
        "requests": requests,
        "max_physical_requests": 4,
        "attempts_per_request": 1,
        "deadline_seconds": 30,
        "price_date": PRICE_DATE,
        "input_usd_per_token": PRICE_PER_TOKEN,
        "output_usd_per_token": 0,
        "estimated_max_usd": 4 * 32_000 * PRICE_PER_TOKEN,
        "per_request_allowance_usd": 32_000 * PRICE_PER_TOKEN,
        "budget_usd": 0.01,
        "data": "fixed synthetic examples only",
        "forge_home": "new isolated directory under output",
    }


def measurement_manifest() -> dict[str, Any]:
    """Prepare size, shared-state and latency controls with a fixed 25-request cap."""
    choice, noul, score = [item[2] for item in cases()[:3]]
    shared = "One customer reports a broken checkout button; other customers can still order. " * 20
    many = ChoiceQuestion(
        instructions="Which synthetic category fits?",
        criteria={f"category_{index}": f"The ticket explicitly says category {index}" for index in range(40)},
    )
    shapes: list[tuple[str, str, dict[str, Question]]] = [
        ("small", "A synthetic package arrived broken.", {"check": noul}),
        ("medium", "A synthetic package arrived broken. " * 120, {"check": noul}),
        ("near-budget", "A synthetic package arrived broken. " * 820, {"check": noul}),
        ("unicode", "这是一个虚构的包裹损坏案例。これは架空の破損例です。 " * 100, {"check": noul}),
        ("code", "def checkout(order):\n    return {'status': 'failed', 'synthetic': True}\n" * 80, {"check": noul}),
        ("many-criteria", "The ticket explicitly says category 17.", {"check": many}),
        ("shared-one", shared, {"damage": noul}),
        ("shared-three", shared, {"damage": noul, "owner": choice, "urgency": score}),
    ]
    requests = []
    for label, state, questions in shapes:
        payload = build_payload(DEFAULT_MODEL, state, questions)
        for repeat in range(3):
            requests.append(
                {
                    "label": f"{label}-{repeat + 1}",
                    "shape": label,
                    "payload": payload,
                    "expected_status": 200,
                    "per_request_allowance_usd": 32_000 * len(questions) * PRICE_PER_TOKEN,
                }
            )
    oversized = build_payload(DEFAULT_MODEL, "placeholder", {"check": noul})
    oversized["state"] = "x " * 60_000
    requests.append(
        {
            "label": "over-limit-1",
            "shape": "over-limit",
            "payload": oversized,
            "wire_control": True,
            "expected_status": [400, 413],
            "per_request_allowance_usd": 132_000 * PRICE_PER_TOKEN,
        }
    )
    for entry in requests:
        serialized = json.dumps(entry["payload"], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        entry["sha256"] = hashlib.sha256(serialized.encode()).hexdigest()
    return {
        "schema_version": 1,
        "stage": "measurement",
        "endpoint": ENDPOINT,
        "model": DEFAULT_MODEL,
        "resolved_model": "typesafe/jev-1.13-20260917",
        "requests": requests,
        "max_physical_requests": len(requests),
        "attempts_per_request": 1,
        "deadline_seconds": 30,
        "price_date": PRICE_DATE,
        "input_usd_per_token": PRICE_PER_TOKEN,
        "output_usd_per_token": 0,
        "estimated_max_usd": sum(entry["per_request_allowance_usd"] for entry in requests),
        "budget_usd": 0.05,
        "data": "fixed synthetic examples only",
        "forge_home": "new isolated directory under output",
    }


def check_response(body: Any, plan: dict[str, Any], entry: dict[str, Any]) -> str | None:
    """Stop on unexpected accounting or model identity without treating estimates as invoice caps."""
    if not isinstance(body, dict):
        return "unparseable_response"
    if "model" in body and body["model"] != "typesafe/jev-1.13-20260917":
        return "model_changed"
    usage = body.get("usage")
    if usage is not None:
        if not isinstance(usage, dict):
            return "invalid_usage"
        cost = usage.get("cost")
        allowance = (
            entry["per_request_allowance_usd"]
            if "per_request_allowance_usd" in entry
            else plan["per_request_allowance_usd"]
        )
        if cost is not None and (
            not isinstance(cost, (int, float))
            or isinstance(cost, bool)
            or not math.isfinite(cost)
            or cost < 0
            or cost > allowance
        ):
            return "unexpected_cost"
        inputs = usage.get("input_tokens")
        outputs = usage.get("output_tokens")
        if type(inputs) is not int or inputs < 0 or type(outputs) is not int or outputs < 0:
            return "invalid_usage"
        if cost is not None and abs(cost - inputs * PRICE_PER_TOKEN) > 0.000000001:
            return "pricing_changed"
    return None


def summarize(record: dict[str, Any]) -> dict[str, Any]:
    """Report nearest-rank percentiles and missing accounting explicitly, by declared shape."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry, result in zip(record["manifest"]["requests"], record["results"]):
        grouped.setdefault(entry.get("shape", entry["label"]), []).append(result)
    summary: dict[str, Any] = {}
    for shape, results in grouped.items():
        samples = sorted(result["elapsed_ms"] for result in results if "elapsed_ms" in result)
        usages = [response["body"].get("usage", {}) for result in results for response in result["responses"]]
        costs = [usage["cost"] for usage in usages if usage.get("cost") is not None]
        summary[shape] = {
            "samples": len(samples),
            "p50_ms": samples[math.ceil(len(samples) * 0.50) - 1] if samples else None,
            "p95_ms": samples[math.ceil(len(samples) * 0.95) - 1] if samples else None,
            "failures": sum(result["error"] is not None for result in results),
            "input_tokens": [usage.get("input_tokens") for usage in usages],
            "output_tokens": [usage.get("output_tokens") for usage in usages],
            "reported_usd": sum(costs) if costs else None,
            "missing_costs": len(usages) - len(costs),
        }
    return {
        "percentile_method": "nearest-rank; end-to-end including credentials, HTTP and telemetry",
        "physical_requests": record["physical_requests"],
        "shapes": summary,
    }


class CaptureTransport(httpx.AsyncBaseTransport):
    """Capture bounded synthetic responses without persisting request headers or secrets."""

    def __init__(self, delegate: httpx.AsyncBaseTransport, secret: str, cap: int) -> None:
        self.delegate = delegate
        self.secret = secret
        self.cap = cap
        self.count = 0
        self.wire_payload: dict[str, Any] | None = None
        self.expected_payload: dict[str, Any] | None = None
        self.records: list[dict[str, Any]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Count immediately before dispatch and retain only redacted response bodies."""
        if self.count >= self.cap:
            raise httpx.TransportError("Probe physical-request cap exhausted")
        payload = json.loads(request.content)
        if self.wire_payload is not None:
            payload = self.wire_payload
            headers = {key: value for key, value in request.headers.items() if key != "content-length"}
            request = httpx.Request(request.method, request.url, headers=headers, json=payload)
        if self.expected_payload is not None and payload != self.expected_payload:
            raise httpx.TransportError("Request differs from approved payload")
        if payload.get("provider", {}).get("zdr") is not True:
            raise httpx.TransportError("Probe requires ZDR")
        self.count += 1
        started = time.monotonic()
        response = await self.delegate.handle_async_request(request)
        chunks = bytearray()
        try:
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > MAX_RESPONSE_BYTES:
                    raise httpx.ReadError("Probe response exceeds limit")
        finally:
            await response.aclose()
        text = chunks.decode("utf-8", errors="replace").replace(self.secret, "[REDACTED]")
        text = re.sub(r"sk-(?:or-v1-)?[A-Za-z0-9_-]+", "[REDACTED]", text)
        try:
            body: Any = json.loads(text)
        except ValueError:
            body = {"unparseable_response": True}
        if isinstance(body, dict) and "user_id" in body:
            body["user_id"] = "[REDACTED]"
        self.records.append(
            {
                "status": response.status_code,
                "latency_ms": (time.monotonic() - started) * 1000,
                "body": body,
            }
        )
        return httpx.Response(
            response.status_code,
            # aiter_bytes has already decoded compression; do not decode it again downstream.
            headers={
                key: value
                for key, value in response.headers.items()
                if key not in {"content-encoding", "content-length", "transfer-encoding"}
            },
            content=bytes(chunks),
            request=request,
        )

    async def aclose(self) -> None:
        """Release the underlying connection pool."""
        await self.delegate.aclose()


class ProbeCredentials(CredentialManager):
    """Carry the already resolved key into an otherwise isolated probe home."""

    def __init__(self, resolved: dict[str, Any]) -> None:
        super().__init__()
        self.resolved = resolved

    async def get_credentials(self, provider: Any) -> dict[str, Any]:
        """Return only the OpenRouter credentials selected before isolation."""
        if provider != "openrouter":
            raise ValueError("Probe only supports OpenRouter")
        return self.resolved


async def run_live(plan: dict[str, Any], output: Path, *, resume: Path | None = None) -> int:
    """Execute an explicitly selected, unmodified manifest in a fresh Forge home."""
    proposal = measurement_manifest() if plan.get("stage") == "measurement" else manifest()
    if plan != proposal:
        raise ValueError("Manifest differs from the fixed proposal; regenerate and review it")
    if output.exists():
        raise ValueError("Choose a new output directory")
    results: list[dict[str, Any]] = []
    if resume:
        prior = json.loads(resume.read_text())
        results = prior["results"]
        if (
            prior["manifest"] != plan
            or prior["physical_requests"] != len(results)
            or not 0 < len(results) < len(plan["requests"])
        ):
            raise ValueError("Resume requires a partial capture from this exact manifest")
        classes: dict[str, type[ChoiceQuestion] | type[NoulQuestion] | type[ScoreQuestion]] = {
            "choice": ChoiceQuestion,
            "noul": NoulQuestion,
            "score": ScoreQuestion,
        }
        for result, entry in zip(results, plan["requests"]):
            if (
                result["label"] != entry["label"]
                or result["physical_requests"] != 1
                or len(result["responses"]) != 1
                or result["responses"][0]["status"] != 200
                or entry.get("wire_control")
                or entry["label"] == "malformed"
            ):
                raise ValueError("Resume cannot bypass a failed provider request")
            body = result["responses"][0]["body"]
            response = JudgmentResponse.model_validate(body)
            questions = {
                key: classes[value["type"]].model_validate(value)
                for key, value in entry["payload"]["questions"].items()
            }
            validate_answers(response, questions)
            if check_response(body, plan, entry):
                raise ValueError("Resume cannot bypass an accounting or model stop")
    creds = await CredentialManager.default().get_credentials("openrouter")
    if decisions_url(creds["base_url"]) != ENDPOINT:
        raise ValueError("This manifest admits only the public OpenRouter Decisions endpoint")
    output.mkdir(parents=True, mode=0o700)
    isolated = output / "forge-home"
    isolated.mkdir(mode=0o700)
    os.environ["FORGE_HOME"] = str(isolated.resolve())
    # Credential resolution may have cached the original home's provider-trace settings.
    reset_runtime_config()
    os.environ.update(new_root_run_identity().as_env())
    for name in ("FORGE_SESSION", "FORGE_PARENT_RUN_ID"):
        os.environ.pop(name, None)
    started_at = datetime.now(timezone.utc).isoformat()
    repo = Path(__file__).resolve().parents[3]
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True).stdout
    )
    implementation_hashes = {
        str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [Path(__file__).resolve(), *sorted((repo / "src/forge/core/judgments").glob("*.py"))]
    }
    remaining = plan["max_physical_requests"] - len(results)
    for entry in plan["requests"][len(results) :]:
        label = entry["label"]
        payload = entry["payload"]
        control = entry.get("wire_control") or label == "malformed"
        state = "Synthetic wire control" if control else payload["state"]
        question_classes: dict[str, type[ChoiceQuestion] | type[NoulQuestion] | type[ScoreQuestion]] = {
            "choice": ChoiceQuestion,
            "noul": NoulQuestion,
            "score": ScoreQuestion,
        }
        questions = (
            {"check": cases()[1][2]}
            if control
            else {
                key: question_classes[value["type"]].model_validate(value)
                for key, value in payload["questions"].items()
            }
        )
        transport = CaptureTransport(httpx.AsyncHTTPTransport(retries=0), creds["api_key"], remaining)
        transport.expected_payload = payload
        transport.wire_payload = payload if control else None
        client = OpenRouterJudgmentClient(credentials=ProbeCredentials(creds), transport=transport, max_attempts=1)
        error = None
        call_started = time.monotonic()
        try:
            await client.judge(
                state,
                questions,
                deadline=time.monotonic() + plan["deadline_seconds"],
            )
        except JudgmentError as exc:
            error = exc.kind
        remaining -= transport.count
        result = {
            "label": label,
            "elapsed_ms": (time.monotonic() - call_started) * 1000,
            "error": error,
            "physical_requests": transport.count,
            "responses": transport.records,
        }
        expected = entry["expected_status"]
        admitted = expected if isinstance(expected, list) else [expected]
        stop_reason = None
        if not transport.records or transport.records[-1]["status"] not in admitted or (error and not control):
            stop_reason = "unexpected_response"
        elif transport.records:
            stop_reason = check_response(transport.records[-1]["body"], plan, entry)
        result["stop_reason"] = stop_reason
        results.append(result)
        record = {
            "schema_version": 1,
            "started_at": started_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "revision": revision,
            "dirty": dirty,
            "implementation_sha256": implementation_hashes,
            "resumed_from_sha256": hashlib.sha256(resume.read_bytes()).hexdigest() if resume else None,
            "manifest": plan,
            "physical_requests": sum(item["physical_requests"] for item in results),
            "results": results,
        }
        (output / "capture.json").write_text(json.dumps(record, indent=2) + "\n")
        (output / "summary.json").write_text(json.dumps(summarize(record), indent=2) + "\n")
        if stop_reason:
            return 1
    return 0


def main() -> int:
    """Print a dry-run manifest unless explicitly admitted for live execution."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--stage", choices=["early", "measurement"], default="early")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--resume", type=Path, help="Continue an interrupted capture without repeating completed requests"
    )
    args = parser.parse_args()
    if not args.live:
        print(json.dumps(measurement_manifest() if args.stage == "measurement" else manifest(), indent=2))
        return 0
    if not args.manifest or not args.output:
        parser.error("--live requires a reviewed --manifest and a new --output directory")
    try:
        return asyncio.run(run_live(json.loads(args.manifest.read_text()), args.output, resume=args.resume))
    except (ValueError, OSError, NoApiKeyError) as exc:
        print(f"Probe refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
