#!/usr/bin/env python3
"""Prepare a synthetic calibration capture; live execution requires its separately approved manifest."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
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

from forge.core.judgments import NoulQuestion, OpenRouterJudgmentClient
from forge.core.judgments.openrouter import (
    MAX_RESPONSE_BYTES,
    decisions_url,
    encode_payload,
)
from forge.core.judgments.types import JudgmentError
from forge.core.llm.credentials import CredentialManager
from forge.core.llm.errors import NoApiKeyError
from forge.core.reactive.env import new_root_run_identity
from forge.runtime_config import reset_runtime_config

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "docs/board/doing/jev_rule_pack/evidence/wrapper-corpus.json"
CAPTURE_EVIDENCE = CORPUS.parent
MAX_JOURNAL_BYTES = 32_000_000
ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
EXPECTED_MODEL = "typesafe/jev-1.13-20260917"
PRICE_PER_TOKEN = 0.000000042
WITHHELD_RESPONSE = "Response body withheld: malformed or unsupported JSON"
SENSITIVE_FIELDS = frozenset({"user_id", "account_id", "api_key", "access_token"})
CALIBRATION_CASES = {
    "module-forwarding",
    "module-direct-update",
    "module-injection",
    "method-argument-adapter",
    "validation-boundary",
    "validation-gratuitous",
    "preview-alias",
    "callback-protocol",
    "multi-file-wrapper",
}


def load_evaluator() -> Any:
    """Use the existing preparation and saved-prediction contracts without a second payload builder."""
    spec = importlib.util.spec_from_file_location(
        "jev_capture_evaluator", Path(__file__).with_name("rule-pack-eval.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


evaluator = load_evaluator()


def read_json(path: Path, limit: int = 1_000_000) -> Any:
    """Reject oversized, nonfinite, duplicate-key or excessively nested local JSON."""
    value = evaluator._read_json(path, limit)
    evaluator._canonical_bytes(value)
    return value


def implementation_hashes() -> dict[str, str]:
    """Bind the capture to its transport, preparation and rule implementation."""
    paths = [
        Path(__file__).resolve(),
        Path(__file__).with_name("rule-pack-eval.py"),
        *sorted((ROOT / "src/forge/core/judgments").glob("*.py")),
        *sorted((ROOT / "src/forge/policy/rule_pack").glob("*.py")),
    ]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def proposal_identity(plan: dict[str, Any]) -> str:
    """Keep a proposal stable across implementation edits, including historical manifests without an ID."""
    if not isinstance(plan, dict):
        raise ValueError("Expected a capture manifest object")
    if "proposal_id" in plan:
        identifier = plan["proposal_id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", identifier):
            raise ValueError("proposal_id must contain 1-80 lowercase letters, digits or hyphens")
        return identifier
    content = {key: value for key, value in plan.items() if key != "implementation_sha256"}
    return "calibration-" + hashlib.sha256(evaluator._canonical_bytes(content)).hexdigest()


def refuse_consumed_proposal(plan: dict[str, Any]) -> None:
    """Reject replay visible in retained A2 journals; this is not a global authorization ledger."""
    identifier = proposal_identity(plan)
    for path in sorted(CAPTURE_EVIDENCE.glob("*/capture.json")):
        try:
            journal = read_json(path, MAX_JOURNAL_BYTES)
            if not isinstance(journal, dict) or not isinstance(journal.get("manifest"), dict):
                raise ValueError("Expected a capture journal with a manifest")
            if proposal_identity(journal["manifest"]) != identifier:
                continue
            count = journal.get("physical_requests")
            attempts = journal.get("attempts")
            if type(count) is not int or count < 0 or not isinstance(attempts, list):
                raise ValueError("Invalid dispatch accounting")
            if any(not isinstance(row, dict) or type(row.get("dispatched")) is not bool for row in attempts):
                raise ValueError("Invalid attempt accounting")
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            raise ValueError(f"Cannot verify retained capture journal {path}; inspect and repair its evidence") from exc
        if count or any(row["dispatched"] for row in attempts):
            raise ValueError(
                f"Proposal {identifier} already dispatched requests in {path}. "
                "There is no resume; prepare and obtain separate approval for a new --proposal-id before repeating."
            )


def manifest(proposal_id: str | None = None) -> dict[str, Any]:
    """Build the fixed nine-request proposal without credential access or network I/O."""
    corpus = evaluator.Corpus.model_validate(read_json(CORPUS))
    prepared = evaluator.prepare(corpus, include_payloads=True)
    cases = {case.id: case for case in corpus.cases}
    requests = []
    for entry in prepared["cases"]:
        case = cases[entry["id"]]
        if case.split != "calibration" or entry["preparation"] != "model_input":
            continue
        if case.provenance.kind != "constructed" or case.adjudication is None:
            raise ValueError("Calibration capture requires human-adjudicated constructed cases")
        requests.append(
            {
                "case_id": case.id,
                "case_sha256": entry["case_sha256"],
                "payload_sha256": entry["payload_sha256"],
                "request_bytes": entry["request_bytes"],
                "payload": entry["payload"],
                "provenance": case.provenance.model_dump(),
            }
        )
    if {entry["case_id"] for entry in requests} != CALIBRATION_CASES or len(requests) != 9:
        raise ValueError("The fixed calibration membership changed; revise and review the capture plan")
    if any(len(entry["payload"]["questions"]) != 3 for entry in requests):
        raise ValueError("The approved cost bound requires three questions per request")
    plan = {
        "schema_version": 1,
        "stage": "constructed_calibration",
        "endpoint": ENDPOINT,
        "expected_model": EXPECTED_MODEL,
        "corpus_sha256": evaluator.corpus_digest(corpus),
        "prompt_sha256": prepared["prompt_sha256"],
        "implementation_sha256": implementation_hashes(),
        "split": "calibration",
        "repetitions": 1,
        "max_physical_requests": 9,
        "attempts_per_request": 1,
        "deadline_seconds": 30,
        "runtime_comparison_seconds": 5,
        "price_date": "2026-10-17",
        "input_usd_per_token": PRICE_PER_TOKEN,
        "output_usd_per_token": 0,
        "input_tokens_per_question_bound": 32_000,
        "questions_per_request": 3,
        "per_request_allowance_usd": 32_000 * 3 * PRICE_PER_TOKEN,
        "estimated_max_usd": 9 * 32_000 * 3 * PRICE_PER_TOKEN,
        "budget_usd": 0.05,
        "budget_kind": "planning estimate; post-response checks cannot guarantee an invoice cap",
        "data": "fixed constructed calibration actions; no repository history or transcripts",
        "forge_home": "new isolated directory under output",
        "requests": requests,
    }
    if proposal_id is not None:
        plan["proposal_id"] = proposal_id
    plan["proposal_id"] = proposal_identity(plan)
    return plan


def redact(text: str, secret: str) -> str:
    """Redact complete sensitive values; withhold text that cannot be safely traversed."""

    def redact_string(value: str) -> str:
        if secret:
            value = value.replace(secret, "[REDACTED]")
        return re.sub(r"sk-(?:or-v1-)?[A-Za-z0-9_-]+", "[REDACTED]", value)

    def redact_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                redact_string(key): "[REDACTED]" if key.lower() in SENSITIVE_FIELDS else redact_value(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [redact_value(item) for item in value]
        return redact_string(value) if isinstance(value, str) else value

    # Parse escaped spellings first. Do not retain malformed fragments that might hide identifiers.
    try:
        parsed = json.loads(text, object_pairs_hook=evaluator._unique_object)
        evaluator._canonical_bytes(parsed)
        return json.dumps(redact_value(parsed), ensure_ascii=True, allow_nan=False)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return WITHHELD_RESPONSE


def check_accounting(body: dict[str, Any], plan: dict[str, Any]) -> str | None:
    """Stop on model/pricing drift; absent reported cost remains unknown."""
    if body.get("model") != plan["expected_model"]:
        return "model_changed"
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return "invalid_usage"
    inputs, outputs, cost = (usage.get(name) for name in ("input_tokens", "output_tokens", "cost"))
    if type(inputs) is not int or inputs < 0 or type(outputs) is not int or outputs < 0:
        return "invalid_usage"
    if inputs > plan["input_tokens_per_question_bound"] * plan["questions_per_request"]:
        return "input_token_bound_exceeded"
    if cost is None:
        return None
    if type(cost) not in (int, float) or not math.isfinite(cost) or not 0 <= cost <= plan["per_request_allowance_usd"]:
        return "unexpected_cost"
    if abs(cost - inputs * plan["input_usd_per_token"]) > 0.000000001:
        return "pricing_changed"
    return None


def atomic_json(path: Path, value: Any) -> None:
    """Replace a complete artifact, never leave a partially written JSON document."""
    encoded = json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class CaptureTransport(httpx.AsyncBaseTransport):
    """Enforce the physical cap at dispatch and retain bounded response evidence."""

    def __init__(self, delegate: httpx.AsyncBaseTransport, journal: dict[str, Any], persist: Any, secret: str) -> None:
        self.delegate = delegate
        self.journal = journal
        self.persist = persist
        self.secret = secret

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Record an ambiguous attempt before network I/O, including on interruption."""
        plan = self.journal["manifest"]
        index = self.journal["physical_requests"]
        if index >= plan["max_physical_requests"]:
            raise httpx.TransportError("Capture physical-request cap exhausted")
        expected = plan["requests"][index]["payload"]
        if (
            request.method != "POST"
            or str(request.url) != ENDPOINT
            or request.content != encode_payload(expected)
            or expected.get("provider", {}).get("zdr") is not True
        ):
            raise httpx.TransportError("Request differs from the approved endpoint or exact ZDR payload")
        row = self.journal["attempts"][-1]
        request_id = request.headers.get("X-Request-ID")
        if request_id and re.fullmatch(r"req_[0-9a-f]{12}", request_id):
            row["request_id"] = request_id
        self.journal["physical_requests"] += 1
        row["dispatched"] = True
        self.persist()
        response = await self.delegate.handle_async_request(request)
        row["status_code"] = response.status_code
        chunks = bytearray()
        digest = hashlib.sha256()
        received = 0
        try:
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                digest.update(chunk)
                chunks.extend(chunk[: max(0, MAX_RESPONSE_BYTES - len(chunks))])
                if received > MAX_RESPONSE_BYTES:
                    row["response_truncated"] = True
                    raise httpx.ReadError("Capture response exceeds the byte limit")
        finally:
            row["response_bytes"] = received
            row["received_body_sha256"] = digest.hexdigest()
            row["response_body_redacted"] = redact(chunks.decode("utf-8", errors="replace"), self.secret)
            self.persist()
            await response.aclose()
        try:
            body = json.loads(chunks, object_pairs_hook=evaluator._unique_object)
            evaluator._canonical_bytes(body)
            if not isinstance(body, dict):
                raise ValueError("Response must be an object")
            row["body"] = json.loads(redact(json.dumps(body, ensure_ascii=True, allow_nan=False), self.secret))
        except (ValueError, UnicodeError, TypeError, RecursionError):
            row["protocol_failure"] = "invalid_json_response"
        return httpx.Response(
            response.status_code,
            content=bytes(chunks),
            request=request,
        )

    async def aclose(self) -> None:
        await self.delegate.aclose()


class CaptureCredentials(CredentialManager):
    """Carry only the resolved OpenRouter key into the isolated telemetry home."""

    def __init__(self, key: str) -> None:
        super().__init__()
        self.key = key

    async def get_credentials(self, provider: Any) -> dict[str, Any]:
        if provider != "openrouter":
            raise ValueError("Capture only supports OpenRouter")
        return {"api_key": self.key, "base_url": ENDPOINT}


def predictions(journal: dict[str, Any]) -> dict[str, Any]:
    """Export only completed/dispatched attempts in the evaluator's existing schema."""
    plan = journal["manifest"]
    rows = []
    for entry, attempt in zip(plan["requests"], journal["attempts"]):
        if not attempt["dispatched"]:
            continue
        rows.append(
            {
                "case_id": entry["case_id"],
                "case_sha256": entry["case_sha256"],
                "payload_sha256": entry["payload_sha256"],
                "repetition": 1,
                "response": attempt.get("body") if not attempt["failure"] else None,
                "failure": attempt["failure"],
                "latency_ms": attempt.get("latency_ms"),
                "status_code": attempt.get("status_code"),
                "response_bytes": attempt.get("response_bytes"),
            }
        )
    return evaluator.SavedPredictions(
        schema_version=2,
        source_kind="capture",
        source_reference="capture.json",
        expected_model=plan["expected_model"],
        corpus_sha256=plan["corpus_sha256"],
        prompt_sha256=plan["prompt_sha256"],
        split="calibration",
        repetitions=1,
        predictions=rows,
    ).model_dump()


async def run_live(plan: dict[str, Any], output: Path) -> int:
    """Run only an unchanged approved proposal, without retries or resume."""
    refuse_consumed_proposal(plan)
    if evaluator._canonical_bytes(plan) != evaluator._canonical_bytes(manifest(plan.get("proposal_id"))):
        raise ValueError("Manifest differs from the current fixed proposal; regenerate and review it")
    if not output.is_absolute() or output.exists():
        raise ValueError("Choose a new absolute output directory")
    resolved = await CredentialManager.default().get_credentials("openrouter")
    if decisions_url(resolved["base_url"]) != ENDPOINT:
        raise ValueError("This manifest admits only the public OpenRouter Decisions endpoint")
    output.mkdir(parents=True, mode=0o700)
    isolated = output / "forge-home"
    isolated.mkdir(mode=0o700)
    identity = new_root_run_identity()
    journal: dict[str, Any] = {
        "schema_version": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "revision": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip(),
        "dirty": bool(
            subprocess.run(
                ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
            ).stdout
        ),
        "implementation_sha256": implementation_hashes(),
        "manifest": plan,
        "run_id": identity.run_id,
        "physical_requests": 0,
        "attempts": [],
    }

    def persist() -> None:
        journal["updated_at"] = datetime.now(timezone.utc).isoformat()
        # The journal is authoritative if interruption falls between these atomic replacements.
        atomic_json(output / "capture.json", journal)
        atomic_json(output / "predictions.json", predictions(journal))

    names = ("FORGE_HOME", "FORGE_RUN_ID", "FORGE_ROOT_RUN_ID", "FORGE_PARENT_RUN_ID", "FORGE_SESSION")
    previous = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ.pop(name, None)
        os.environ.update(identity.as_env())
        os.environ["FORGE_HOME"] = str(isolated)
        reset_runtime_config()
        persist()
        for entry in plan["requests"]:
            attempt: dict[str, Any] = {"case_id": entry["case_id"], "dispatched": False, "failure": "interrupted"}
            journal["attempts"].append(attempt)
            transport = CaptureTransport(httpx.AsyncHTTPTransport(retries=0), journal, persist, resolved["api_key"])
            client = OpenRouterJudgmentClient(
                credentials=CaptureCredentials(resolved["api_key"]),
                transport=transport,
                max_attempts=1,
                command="jev-rule-pack-calibration",
            )
            payload = entry["payload"]
            started = time.monotonic()
            try:
                await client.judge(
                    payload["state"],
                    {name: NoulQuestion.model_validate(value) for name, value in payload["questions"].items()},
                    deadline=started + plan["deadline_seconds"],
                    run_identity=identity,
                )
                attempt["failure"] = attempt.get("protocol_failure") or check_accounting(attempt["body"], plan)
            except JudgmentError as exc:
                attempt["failure"] = attempt.get("protocol_failure") or exc.kind
            finally:
                attempt["latency_ms"] = (time.monotonic() - started) * 1000
                persist()
                await transport.aclose()
            if attempt["failure"]:
                return 1
        return 0
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        reset_runtime_config()


def main() -> int:
    """Print the proposal by default; execution cannot silently substitute a different plan."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--proposal-id", help="Name a new proposal for separate review; preparation only")
    args = parser.parse_args()
    if args.live != bool(args.manifest and args.output) or (not args.live and (args.manifest or args.output)):
        parser.error("--live requires a reviewed --manifest and a new absolute --output directory")
    if args.live and args.proposal_id:
        parser.error("--proposal-id is preparation-only; execution uses the reviewed manifest's proposal_id")
    try:
        if not args.live:
            print(json.dumps(manifest(args.proposal_id), indent=2, ensure_ascii=False, allow_nan=False))
            return 0
        return asyncio.run(run_live(read_json(args.manifest), args.output))
    except (OSError, ValueError, JudgmentError, NoApiKeyError, RecursionError, OverflowError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
