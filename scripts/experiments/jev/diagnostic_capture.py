#!/usr/bin/env python3
"""Validate the frozen diagnostic proposal, or execute its separately authorized finite capture once."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

from forge.core.llm.credentials import CredentialManager
from forge.core.llm.errors import NoApiKeyError
from forge.core.reactive.env import new_root_run_identity
from forge.core.telemetry.downstream import mint_downstream_event_id
from forge.core.usage.correlation import mint_request_id
from forge.runtime_config import reset_runtime_config

# These standalone experiment modules are intentionally outside the installed package.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture_io  # noqa: E402
import diagnostic_manifest as manifest  # noqa: E402
import diagnostic_results as results  # noqa: E402

EVIDENCE_ROOT = manifest.ROOT / "docs/board/doing/jev_rule_pack/evidence"
WHOLE_RUN_SECONDS = 3000
DEADLINE_SECONDS = {"J": 30, "R": 45}
CATALOG_TIMEOUT_SECONDS = 30
MAX_CATALOG_BYTES = 5_000_000
MAX_RESPONSE_BYTES = 256_000
MAX_JOURNAL_BYTES = 32 * 1024 * 1024
GROUPING_ENV = (
    "FORGE_HOME",
    "FORGE_RUN_ID",
    "FORGE_ROOT_RUN_ID",
    "FORGE_PARENT_RUN_ID",
    "FORGE_SESSION",
    "FORGE_COMMAND",
    "FORGE_WORKFLOW",
    "FORGE_PROXY_ID",
    "FORGE_SUBPROCESS_PROXY",
    "FORGE_SUBPROCESS_BASE_URL",
    "FORGE_SUBPROCESS_PROXY_ID",
    "FORGE_SUBPROCESS_TEMPLATE",
    "FORGE_FORGE_ROOT",
    "FORGE_SIDECAR",
    "FORGE_TEMPLATE",
    "ANTHROPIC_CUSTOM_HEADERS",
)


def proposal_identity(plan: dict[str, Any]) -> str:
    """Bind replay protection to the study, independently of executable-source or availability flags."""
    identity = {
        key: plan[key]
        for key in (
            "proposal_kind",
            "diagnostic_version",
            "packet_sha256",
            "review_sha256",
            "catalog_sha256",
            "arms",
            "limits",
            "scoring",
            "payloads",
            "slots",
        )
    }
    return "diagnostic-" + manifest.digest(identity)


def implementation_hashes() -> dict[str, str]:
    """Capture executor provenance separately from the immutable provider request proposal."""
    paths = [
        Path(__file__).resolve(),
        Path(capture_io.__file__),
        Path(results.__file__),
    ]
    return {str(path.relative_to(manifest.ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def _scrub(value: Any, secret: str) -> Any:
    if isinstance(value, dict):
        return {key: _scrub(item, secret) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item, secret) for item in value]
    if isinstance(value, str):
        return re.sub(
            r"sk-(?:or-v1-)?[A-Za-z0-9_-]+",
            "[REDACTED]",
            value.replace(secret, "[REDACTED]"),
        )
    return value


async def _credentials(credentials: Any) -> str:
    resolved = (
        credentials
        if isinstance(credentials, Mapping)
        else await (credentials or CredentialManager.default()).get_credentials("openrouter")
    )
    if resolved.get("base_url") not in {
        "https://openrouter.ai/api/v1",
        "https://openrouter.ai/api/v1/",
    }:
        raise ValueError("Only the public https://openrouter.ai/api/v1 credential base is admitted")
    key = resolved.get("api_key")
    if not isinstance(key, str) or not key.strip() or len(key) > 8192 or "\n" in key or "\r" in key:
        raise ValueError("OpenRouter credentials are unavailable or invalid")
    return key


async def _local(function: Any, *args: Any, deadline: float) -> Any:
    """Bound admitted local work and check its deadline before any subsequent HTTP."""
    if time.monotonic() >= deadline:
        raise TimeoutError
    # These operations read/write already bounded files. Finish each OS write before
    # restoring process state: cancelling a background write cannot undo its effects.
    value = function(*args)
    if time.monotonic() >= deadline:
        raise TimeoutError
    return value


def _refuse_consumed(plan: dict[str, Any], evidence_root: Path) -> None:
    identifier = proposal_identity(plan)
    claim = evidence_root / ".diagnostic-proposal-claims" / (identifier + ".json")
    if claim.exists() or claim.is_symlink():
        raise ValueError("This diagnostic proposal is already consumed; no retry or resume is allowed")
    # This bounded retained-evidence check protects against an accidentally removed claim.
    journals = list(evidence_root.glob("*/capture.json"))
    if len(journals) > 128:
        raise ValueError("Retained evidence exceeds the bounded replay check")
    retained_bytes = 0
    for path in journals:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Unsafe retained capture journal")
        retained_bytes += path.stat().st_size
        if retained_bytes > MAX_JOURNAL_BYTES:
            raise ValueError("Retained evidence exceeds the bounded replay check")
        retained = manifest.read_json(path, MAX_JOURNAL_BYTES)
        prior = retained.get("manifest", {})
        if prior.get("proposal_kind") != "bounded_diagnostic_comparison":
            continue
        if proposal_identity(prior) == identifier:
            raise ValueError("This diagnostic proposal has retained execution evidence; no resume is allowed")


class BorrowedTransport(httpx.AsyncBaseTransport):
    """Injected transports belong to their caller and can serve both public GETs and paid fixture POSTs."""

    def __init__(self, delegate: httpx.AsyncBaseTransport) -> None:
        self.delegate = delegate

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self.delegate.handle_async_request(request)


def _claim(plan: dict[str, Any], output: Path, evidence_root: Path) -> Path:
    if not evidence_root.is_absolute() or not evidence_root.is_dir() or evidence_root.resolve() != evidence_root:
        raise ValueError("The retained evidence root must be an existing absolute directory")
    directory = evidence_root / ".diagnostic-proposal-claims"
    capture_io.private_directory(directory)
    path = directory / (proposal_identity(plan) + ".json")
    try:
        capture_io.write_exclusive(
            path,
            {
                "proposal_id": proposal_identity(plan),
                "manifest_sha256": plan["manifest_sha256"],
                "claimed_at": capture_io.utc_now(),
                "output": str(output),
                "resume": False,
            },
        )
    except FileExistsError as exc:
        raise ValueError("This diagnostic proposal is already consumed; no retry or resume is allowed") from exc
    return path


def _persist(output: Path, journal: dict[str, Any], limit: int) -> None:
    journal["updated_at"] = capture_io.utc_now()
    capture_io.atomic_json(output / "capture.json", journal, limit)


def _stop(journal: dict[str, Any], reason: str) -> None:
    if journal["status"] == "technical_stop" and journal["stop_reason"]:
        if reason != journal["stop_reason"]:
            journal.setdefault("secondary_failures", []).append(reason)
        return
    journal["status"] = "technical_stop"
    journal["stop_reason"] = reason


async def _attempt(
    client: httpx.AsyncClient,
    plan: dict[str, Any],
    slot: dict[str, Any],
    payload: dict[str, Any],
    journal: dict[str, Any],
    output: Path,
    identity: Any,
    key: str,
    whole_deadline: float,
) -> None:
    """Reserve one immutable slot durably, send once, and retain only allowlisted result evidence."""
    arm = slot["arm"]
    started = time.monotonic()
    call_deadline = min(
        whole_deadline,
        started + min(DEADLINE_SECONDS[arm], plan["arms"][arm]["deadline_seconds"]),
    )
    row: dict[str, Any] = {
        **slot,
        "dispatched": False,
        "state": "prepared",
        "failure": "interruption",
        "request_id": mint_request_id(),
        "downstream_event_id": mint_downstream_event_id(),
        "run_id": identity.run_id,
        "root_run_id": identity.root_run_id,
        "started_at": capture_io.utc_now(),
        "result": {},
    }
    row["event_id"] = "evt_" + row["downstream_event_id"]
    journal["attempts"].append(row)
    wire = manifest.wire_bytes(payload["body"])
    network_started: float | None = None
    network_seconds = 0.0
    limit = min(MAX_JOURNAL_BYTES, plan["limits"]["max_journal_bytes"])
    try:
        async with asyncio.timeout_at(call_deadline):
            if (
                len(wire) != payload["request_bytes"]
                or hashlib.sha256(wire).hexdigest() != slot["payload_sha256"]
                or len(wire) > plan["limits"]["max_request_bytes"]
                or journal["physical_requests"] >= plan["limits"]["max_physical_requests"]
            ):
                raise ValueError("wire_integrity")
            row.update(dispatched=True, state="sent_unknown")
            journal["physical_requests"] += 1
            await _local(_persist, output, journal, limit, deadline=call_deadline)
            if time.monotonic() >= call_deadline:
                raise TimeoutError
            network_started = time.monotonic()
            async with client.stream(
                "POST",
                plan["arms"][arm]["endpoint"],
                content=wire,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "X-Request-ID": row["request_id"],
                },
                timeout=max(0.001, call_deadline - time.monotonic()),
            ) as response:
                row["status_code"] = response.status_code
                raw = await capture_io.bounded_response(
                    response,
                    min(MAX_RESPONSE_BYTES, plan["limits"]["max_response_bytes"]),
                )
            network_seconds = time.monotonic() - network_started
            row["response_bytes"] = len(raw)
            row["received_body_sha256"] = hashlib.sha256(raw).hexdigest()
            assessed = results.assess_response(
                raw,
                row["status_code"],
                arm,
                payload,
                plan,
                journal["observed_models"].get(arm),
            )
            row["result"] = _scrub(assessed, key)
            row["failure"] = assessed["failure"]
            row["state"] = "failed" if row["failure"] else "completed"
            if not row["failure"]:
                journal["observed_models"].setdefault(arm, assessed["model"])
            if time.monotonic() >= call_deadline:
                raise TimeoutError
    except (TimeoutError, httpx.TimeoutException):
        row["failure"] = "whole_run_deadline" if time.monotonic() >= whole_deadline else "timeout"
    except asyncio.CancelledError:
        row["failure"] = "interruption"
    except httpx.HTTPError:
        row["failure"] = "network"
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        # Provider data, credential values and filesystem details never become error text.
        row["failure"] = "response_or_journal_overflow" if row.get("status_code") else "unsafe_persistence"
    finally:
        if network_started is not None and not network_seconds:
            network_seconds = time.monotonic() - network_started
        row["latency_ms"] = (time.monotonic() - started) * 1000
        row["network_ms"] = network_seconds * 1000
        row["local_ms"] = max(0.0, row["latency_ms"] - row["network_ms"])
        if row["failure"]:
            row["state"] = "sent_unknown" if row["dispatched"] and not row.get("response_bytes") else "failed"
            _stop(journal, row["failure"])
        # Final evidence flushes may finish after a deadline, but never authorize another HTTP call.
        # Keep a completed response distinct from a subsequent evidence-finalization deadline.
        row["result"]["failure"] = row["failure"]
        evidence_started = time.monotonic()
        try:
            _persist(output, journal, limit)
            if row["dispatched"]:
                capture_io.persist_telemetry(output / "forge-home", row, identity, plan, limit)
        except (OSError, ValueError):
            _stop(journal, "unsafe_persistence")
        row["evidence_finalization_ms"] = (time.monotonic() - evidence_started) * 1000
        if time.monotonic() >= call_deadline:
            journal["evidence_finalization_deadline"] = True
            _stop(journal, "whole_run_deadline" if time.monotonic() >= whole_deadline else "timeout")


async def run_capture(
    plan: dict[str, Any],
    review: dict[str, Any],
    catalog: dict[str, Any],
    output: Path,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    credentials: Any = None,
    catalog_transport: httpx.AsyncBaseTransport | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Execute one authorized proposal; injection replaces transport/auth only, never admission checks."""
    started = time.monotonic()
    deadline = started + min(WHOLE_RUN_SECONDS, 3000)
    async with asyncio.timeout_at(deadline):
        await _local(manifest.validate_manifest, plan, review, catalog, deadline=deadline)
        if (
            not output.is_absolute()
            or output.exists()
            or output.is_symlink()
            or not output.parent.is_dir()
            or output.parent.resolve() != output.parent
        ):
            raise ValueError("Choose a new absolute output directory under an existing parent")
        await _local(_refuse_consumed, plan, evidence_root or EVIDENCE_ROOT, deadline=deadline)
        key = await _credentials(credentials)
        injected_catalog = catalog_transport or transport
        catalog_delegate = (
            BorrowedTransport(injected_catalog) if injected_catalog is not None else httpx.AsyncHTTPTransport(retries=0)
        )
        async with httpx.AsyncClient(
            transport=catalog_delegate,
            follow_redirects=False,
            trust_env=False,
            timeout=CATALOG_TIMEOUT_SECONDS,
        ) as public:
            async with asyncio.timeout_at(min(deadline, time.monotonic() + CATALOG_TIMEOUT_SECONDS)):
                refreshed = await capture_io.refresh_catalog(public, catalog, MAX_CATALOG_BYTES)
        claim = await _local(_claim, plan, output, evidence_root or EVIDENCE_ROOT, deadline=deadline)
        output.mkdir(mode=0o700)
        capture_io.fsync_directory(output.parent)
        capture_io.private_directory(output / "forge-home")
    identities = {arm: new_root_run_identity() for arm in ("J", "R")}
    journal: dict[str, Any] = {
        "schema_version": 1,
        "started_at": capture_io.utc_now(),
        "status": "running",
        "stop_reason": None,
        "manifest": plan,
        "proposal_id": proposal_identity(plan),
        "proposal_claim": str(claim),
        "implementation_sha256": implementation_hashes(),
        "catalog_preflight": refreshed,
        "run_ids": {arm: identity.run_id for arm, identity in identities.items()},
        "physical_requests": 0,
        "attempts": [],
        "observed_models": {},
        "stopped_arms": {},
    }
    previous = {name: os.environ.get(name) for name in GROUPING_ENV}
    by_id = {row["payload_id"]: row for row in plan["payloads"]}
    limit = min(MAX_JOURNAL_BYTES, plan["limits"]["max_journal_bytes"])
    try:
        for name in GROUPING_ENV:
            os.environ.pop(name, None)
        os.environ["FORGE_HOME"] = str(output / "forge-home")
        reset_runtime_config()
        await _local(_persist, output, journal, limit, deadline=deadline)
        # A supplied fixture transport may be shared with the completed catalog client.
        delegate = BorrowedTransport(transport) if transport is not None else httpx.AsyncHTTPTransport(retries=0)
        async with httpx.AsyncClient(transport=delegate, follow_redirects=False, trust_env=False) as client:
            for slot in plan["slots"]:
                if slot["arm"] in journal["stopped_arms"]:
                    continue
                if time.monotonic() >= deadline:
                    _stop(journal, "whole_run_deadline")
                    break
                await _attempt(
                    client,
                    plan,
                    slot,
                    by_id[slot["payload_id"]],
                    journal,
                    output,
                    identities[slot["arm"]],
                    key,
                    deadline,
                )
                attempt = journal["attempts"][-1]
                print(
                    f"slot {slot['slot']}/72 {slot['arm']} {slot['case_id']} repetition {slot['repetition']}: {attempt['failure'] or 'completed'}",
                    flush=True,
                )
                if journal["status"] == "technical_stop":
                    break
                semantic = results.semantic_stop(plan, journal["attempts"], slot["arm"])
                if semantic:
                    journal["stopped_arms"][slot["arm"]] = semantic
                    print(
                        f"arm {slot['arm']} stopped: repeated sentinel disagreement",
                        flush=True,
                    )
                if len(journal["stopped_arms"]) == 2:
                    journal.update(status="semantic_stop", stop_reason="both_arms_semantic_stop")
                    break
        if journal["status"] == "running":
            journal["status"] = "completed"
    except asyncio.CancelledError:
        _stop(journal, "interruption")
    except TimeoutError:
        _stop(journal, "whole_run_deadline")
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        _stop(journal, "unsafe_persistence")
    finally:
        journal["elapsed_seconds"] = time.monotonic() - started
        journal["local_seconds"] = {
            arm: sum(
                row.get("local_ms", 0) + row.get("evidence_finalization_ms", 0)
                for row in journal["attempts"]
                if row["arm"] == arm
            )
            / 1000
            for arm in ("J", "R")
        }
        journal["undispatched_slots"] = [
            slot["slot"]
            for slot in plan["slots"]
            if slot["slot"] not in {row["slot"] for row in journal["attempts"] if row["dispatched"]}
        ]
        journal["ended_at"] = capture_io.utc_now()
        try:
            report = results.build_report(
                plan,
                journal["attempts"],
                stop_reason=journal["stop_reason"],
                stopped_arms=journal["stopped_arms"],
                local_seconds=journal["local_seconds"],
            )
            evidence_started = time.monotonic()
            capture_io.atomic_json(output / "report.json", report, limit)
            journal["final_evidence_seconds"] = time.monotonic() - evidence_started
            _persist(output, journal, limit)
        except (OSError, ValueError, TimeoutError):
            _stop(journal, "unsafe_persistence")
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            reset_runtime_config()
    return journal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.live != bool(args.output):
        parser.error("--live requires a new absolute --output; validation writes nothing and reads no credentials")
    try:
        plan, review, catalog = (
            manifest.read_json(args.manifest),
            manifest.read_json(args.review),
            manifest.read_json(args.catalog, 100_000),
        )
        if not args.live:
            print(json.dumps(manifest.validate_manifest(plan, review, catalog), indent=2))
            return 0
        journal = asyncio.run(run_capture(plan, review, catalog, args.output))
        print(
            json.dumps(
                {
                    "status": journal["status"],
                    "physical_requests": journal["physical_requests"],
                    "stop_reason": journal["stop_reason"],
                    "output": str(args.output),
                }
            ),
            flush=True,
        )
        return 1 if journal["status"] == "technical_stop" else 0
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RecursionError,
        TimeoutError,
        NoApiKeyError,
        httpx.HTTPError,
    ):
        parser.error(
            "Capture refused or stopped before safe completion; inspect retained local evidence. No retry or resume is allowed."
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
