#!/usr/bin/env python3
"""Explicit, approval-bound OpenRouter Responses stages; selftest uses loopback exclusively."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from paid_diagnostics import envelope, sse_objects
from paid_guard import (
    ACCEPTED_REFUSAL,
    ASTRA,
    CODEX_CREDIT_REFUSAL,
    COST_PREREQUISITE,
    LEDGER_ROOT,
    QWEN_FLAGGED_MANIFEST_SHA256,
    STAGES,
    ZDR_PREREQUISITE,
    Ledger,
    Upstream,
    approved_manifest,
    dump,
    tiny,
)

# This fingerprint identifies the reconstructed account-level refusal in the Qwen regression fixture.
QWEN_ACCOUNT_404_SHA256 = "6ae1793c7b1c43899a5569ce8adf967485e631f164e20024034e64e9a1e623ab"
QWEN_FLAGGED_404_SHA256 = "1c77a1dda340b6aef7f83c07465f232af64cfaea2f3b4270fd269add4a499eca"
QWEN_FLAGGED_RECEIPT_SHA256 = "9010c657c3f705f3f4944f717fb8c8309190de5c36bb744d0803f6c19d413206"


def response_summary(status: int, hdr: dict, raw: bytes, stream: bool) -> tuple[dict, dict]:
    if status != 200:
        raise ValueError(f"Responses request returned HTTP {status}.")
    terminal = None
    if stream:
        events = list(sse_objects(raw))
        if any(e.get("type") in ("error", "response.failed") or e.get("error") for e in events):
            raise ValueError("Stream included a provider error event.")
        terminals = [
            event
            for event in events
            if event.get("type") in ("response.completed", "response.incomplete", "response.failed")
        ]
        if terminals:
            terminal = terminals[-1]["type"]
            result = terminals[-1]["response"]
        else:
            raise ValueError("Stream had no terminal Responses event.")
        objects = [event.get("response", {}) for event in events] + events
    else:
        result = envelope(raw)
        objects = [result]
    if result.get("status") not in {"completed", "incomplete"} or result.get("error"):
        raise ValueError("Responses returned an error or lacked a completed/incomplete result.")
    selected = []
    selected_endpoints = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        routes = (obj.get("openrouter_metadata") or {}).get("endpoints", {}).get("available", [])
        for route in routes:
            if route.get("selected") is True and isinstance(route.get("provider"), str):
                if route["provider"] not in selected:
                    selected.append(route["provider"])
                endpoint = {
                    k: route[k][:160]
                    for k in ("provider", "model", "endpoint", "endpoint_id", "id", "name", "tag")
                    if isinstance(route.get(k), str)
                }
                if endpoint not in selected_endpoints:
                    selected_endpoints.append(endpoint)
    usage = result.get("usage") or {}
    return result, {
        "status": result.get("status"),
        "terminal": terminal,
        "usage_cost": usage.get("cost"),
        "usage_cost_present": "cost" in usage,
        "usage_keys": sorted(usage),
        "response_id": result.get("id"),
        "generation_header": hdr.get("x-generation-id"),
        "selected": selected,
        "selected_endpoints": selected_endpoints,
        "output_types": [item.get("type") for item in result.get("output", [])],
    }


def is_zdr_refusal(diagnostic: dict, *, account_zdr: bool = False) -> bool:
    """Match the refusal to the policy scope that the selected control measures."""
    if account_zdr or "ineligibility_reasons" in diagnostic:
        reasons = diagnostic.get("ineligibility_reasons")
        if not reasons or diagnostic.get("ineligibility_reasons_omitted"):
            return False
        accepted = {"zdr-violation-by-request"}
        if account_zdr:
            accepted.add("zdr-violation-by-account")
        return all(reason["reason"] in accepted and reason.get("endpoint_count", 0) > 0 for reason in reasons)
    matched = False
    for error in (diagnostic, diagnostic.get("upstream", {})):
        code = str(error.get("code", "")).lower().replace("-", "_")
        message = re.sub(r"https?://\S+", "", str(error.get("message", "")), flags=re.I).lower()
        if re.search(r"\b(?:accounts?|guardrails?)\b", code.replace("_", " ") + " " + message):
            return False
        policy = re.search(r"\bzdr\b|\bzero[- ]data[- ]retention\b", message)
        no_route = re.search(
            r"\b(?:no|none)\b.{0,100}\b(?:endpoints?|providers?|routes?)\b"
            r"|\b(?:endpoints?|providers?|routes?)\b.{0,100}\b(?:unavailable|ineligible|not available)\b",
            message,
        )
        if code in {"zdr_unavailable", "no_zdr_endpoints", "no_eligible_zdr_endpoints", "zdr_not_supported"} or (
            policy and no_route
        ):
            matched = True
    return matched


def _pinned_receipt(pin: dict, manifest_dir: Path) -> dict:
    relative = Path(pin["path"])
    directory = manifest_dir.resolve()
    path = (directory / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(directory):
        raise ValueError("Historical receipt must be relative to and inside its manifest directory.")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != pin["sha256"]:
        raise ValueError("Historical receipt SHA-256 differs from the approved pin.")
    return envelope(raw)


def verify_prerequisite(manifest: dict, manifest_dir: Path) -> dict:
    pin = manifest.get("prerequisite")
    if pin != ZDR_PREREQUISITE:
        raise ValueError("Cost and Codex require the published passing stage 60 receipt.")
    receipt = _pinned_receipt(pin, manifest_dir)
    baseline = receipt["historical_baseline"]
    refusal = receipt["accepted_refusal"]
    positive = receipt["positive"]
    if (
        receipt.get("stage") != pin["stage"]
        or receipt.get("manifest_sha256") != pin["manifest_sha256"]
        or receipt.get("criterion") != pin["criterion"]
        or receipt.get("verdict") != "passed"
        or receipt.get("independent_request_zdr") != "unverified"
        or baseline.get("model") != "qwen/qwen4-max"
        or baseline.get("receipt_sha256") != "6a04008c3b2921062d4346be4f11e695101bbb737fb8e9dea5f339c9d5b69d7d"
        or baseline.get("body_sha256") != QWEN_ACCOUNT_404_SHA256
        or refusal.get("receipt_sha256") != QWEN_FLAGGED_RECEIPT_SHA256
        or refusal.get("body_sha256") != QWEN_FLAGGED_404_SHA256
        or receipt["catalog"].get("positive_model") != ASTRA
        or positive.get("http") != 200
        or positive["response"].get("status") != "completed"
        or "message" not in positive["response"].get("output_types", [])
        or receipt["requests"][-1] != {"model": ASTRA, "operation": "responses", "status": 200}
    ):
        raise ValueError("Stage 60 receipt lacks the accepted Qwen refusals or the completed Astra control.")
    return pin


def verified_cost_receipt(manifest: dict, manifest_dir: Path) -> dict:
    """Recover the live routing-metadata decision for a fresh stage 80 ledger."""
    if manifest.get("prerequisite") != COST_PREREQUISITE or manifest.get("previous_attempt") != CODEX_CREDIT_REFUSAL:
        raise ValueError("Standalone Codex requires its exact stage 70 and 80 receipt pins.")
    cost = _pinned_receipt(COST_PREREQUISITE, manifest_dir)
    if (
        cost.get("stage") != "cost"
        or cost.get("manifest_sha256") != COST_PREREQUISITE["manifest_sha256"]
        or cost.get("verdict") != "passed"
        or cost.get("lookup_control_indexed") is not True
        or type(cost.get("try_metadata_on_codex")) is not bool
    ):
        raise ValueError("Stage 70 lacks a passing cost receipt and routing-metadata decision.")
    verify_prerequisite(cost, manifest_dir)
    previous = _pinned_receipt(CODEX_CREDIT_REFUSAL, manifest_dir)
    if (
        previous.get("manifest_sha256") != cost["manifest_sha256"]
        or previous.get("stage") != "codex"
        or previous.get("verdict") != "inconclusive"
        or previous["requests"][-1].get("status") != 402
    ):
        raise ValueError("Previous stage 80 receipt does not record the credit refusal.")
    return cost


def _historical_baseline(control: dict, model: str, positive_model: str, manifest_dir: Path) -> dict:
    pin = control["baseline"]
    receipt = _pinned_receipt(pin, manifest_dir)
    baseline = receipt["baseline"]
    requests = [r for r in receipt["requests"] if r["operation"] == "responses"]
    if (
        receipt.get("stage") != "zdr"
        or receipt.get("verdict") != "inconclusive"
        or receipt["catalog"]["positive_model"] != positive_model
        or receipt["catalog"]["negative_model_ids"] != sorted({model, control["canonical_slug"]})
        or control.get("reasoning_effort") != "none"
        or baseline.get("http") != 404
        or baseline["error"].get("sha256") != QWEN_ACCOUNT_404_SHA256
        or pin["body_sha256"] != QWEN_ACCOUNT_404_SHA256
        or len(requests) != 1
        or requests[0].get("model") != model
        or requests[0].get("status") != 404
        or requests[0].get("error") != baseline["error"]
    ):
        raise ValueError("Historical baseline does not match the verified Qwen account ZDR refusal.")
    return {
        "path": pin["path"],
        "receipt_sha256": pin["sha256"],
        "body_sha256": QWEN_ACCOUNT_404_SHA256,
        "http": 404,
        "model": model,
        "reason": "zdr-violation-by-account",
    }


def _accepted_refusal(control: dict, baseline: dict, manifest_dir: Path) -> dict:
    pin = control["accepted_refusal"]
    if pin["sha256"] != QWEN_FLAGGED_RECEIPT_SHA256 or pin["body_sha256"] != QWEN_FLAGGED_404_SHA256:
        raise ValueError("Continuation must pin the exact accepted Qwen refusal and its response body.")
    receipt = _pinned_receipt(pin, manifest_dir)
    refusal = receipt["refusal"]
    error = refusal["error"]
    attempts = [r for r in receipt["requests"] if r["operation"] == "responses"]
    if (
        receipt.get("stage") != "zdr"
        or receipt.get("criterion") != "account_zdr"
        or receipt.get("manifest_sha256") != QWEN_FLAGGED_MANIFEST_SHA256
        or receipt.get("verdict") != "inconclusive"
        or receipt.get("historical_baseline") != baseline
        or receipt.get("independent_request_zdr") != "unverified"
        or refusal.get("http") != 404
        or error.get("code") != 404
        or error.get("sha256") != QWEN_FLAGGED_404_SHA256
        or attempts != [{"model": baseline["model"], "operation": "responses", "status": 404, "error": error}]
    ):
        raise ValueError("Historical receipt does not match the accepted Qwen refusal under account ZDR.")
    return {
        "path": pin["path"],
        "receipt_sha256": pin["sha256"],
        "body_sha256": QWEN_FLAGGED_404_SHA256,
        "http": 404,
        "model": baseline["model"],
        "message": error["message"],
        "manifest_sha256": QWEN_FLAGGED_MANIFEST_SHA256,
    }


def stage_zdr(api: Upstream, evidence: dict, *, manifest_dir: Path | None = None) -> None:
    primary, excluded = (api.manifest["models"][role] for role in ("default", "non_zdr"))
    control = api.manifest.get("zdr_control", {})
    canonical = control.get("canonical_slug", excluded)
    if not isinstance(primary, str) or not isinstance(excluded, str) or not isinstance(canonical, str):
        raise ValueError("ZDR controls require concrete model IDs.")
    account_zdr = api.manifest.get("stages") == ["zdr"]
    controls = [("refusal", excluded, True), ("positive", primary, True)]
    if account_zdr:
        evidence["criterion"] = control["criterion"]
        evidence["independent_request_zdr"] = "unverified"
        if manifest_dir is None:
            raise ValueError("Historical baseline verification requires the manifest directory.")
        evidence["historical_baseline"] = _historical_baseline(control, excluded, primary, manifest_dir)
        if control["criterion"] == ACCEPTED_REFUSAL:
            evidence["accepted_refusal"] = _accepted_refusal(control, evidence["historical_baseline"], manifest_dir)
            controls = [("positive", primary, True)]
    else:
        controls.insert(0, ("baseline", excluded, False))
    excluded_ids = sorted({excluded, canonical})
    status, _, raw = api.request("endpoints/zdr")
    if status != 200:
        raise ValueError(f"ZDR catalog HTTP {status}.")
    rows = envelope(raw)["data"]
    if account_zdr:
        if not isinstance(rows, list):
            raise ValueError("ZDR catalog did not return an endpoint list.")
        for row in rows:
            model_id = row.get("model_id") if isinstance(row, dict) else None
            if not isinstance(model_id, str) or not re.fullmatch(r"\S+", model_id):
                raise ValueError("ZDR catalog contains an endpoint without a readable model ID.")
    models = {obj.get("model_id") for obj in rows if isinstance(obj, dict)}
    evidence["catalog"] = {
        "epoch": time.time(),
        "entries": len(rows),
        "included": primary in models,
        "excluded": models.isdisjoint(excluded_ids),
        "positive_model": primary,
        "negative_model_ids": excluded_ids,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    if primary not in models or not models.isdisjoint(excluded_ids):
        raise ValueError("Same-day catalog invalidates one of the approved model controls. Revisit manifest.")
    for label, model, required in controls:
        body = tiny(model)
        if label != "positive" and "reasoning_effort" in control:
            body["reasoning"] = {"effort": control["reasoning_effort"]}
        if required:
            body["provider"] = {"zdr": True}
        status, headers, raw = api.request("responses", body)
        evidence[label] = {"http": status}
        # Stage 60 requests are serial. Copy the transport's scrubbed diagnostic before any verdict can raise.
        error = api.observations[-1].get("error") or {}
        if error:
            evidence[label]["error"] = error
        if label == "refusal":
            if status == 200:
                raise ValueError("STOP: ZDR-required request for unlisted model was served or returned HTTP 200.")
            if status not in {400, 403, 404, 422} or not is_zdr_refusal(error, account_zdr=account_zdr):
                raise ValueError("Upstream refusal does not establish a ZDR policy denial.")
        else:
            result, evidence[label]["response"] = response_summary(status, headers, raw, False)
            if result.get("status") != "completed" or not any(
                isinstance(part, dict)
                and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
                and part["text"].strip()
                for item in result.get("output") or []
                if isinstance(item, dict) and item.get("type") == "message" and item.get("role") == "assistant"
                for part in item.get("content") or []
            ):
                raise ValueError(f"The {label} control did not return completed text.")


def stage_cost(api: Upstream, evidence: dict) -> None:
    model = api.manifest["models"]["default"]
    samples = evidence["samples"] = []
    lookup_ids = []
    for streaming in (False, True):
        for metadata in (False, True):
            body = dict(tiny(model), stream=streaming, provider={"zdr": True})
            status, headers, raw = api.request("responses", body, metadata=metadata)
            _, summary = response_summary(status, headers, raw, streaming)
            samples.append(dict(summary, streaming=streaming, metadata=metadata))
            for candidate in (summary["generation_header"], summary["response_id"]):
                if candidate and candidate not in lookup_ids:
                    lookup_ids.append(candidate)
    control = {
        "model": model,
        "messages": [{"role": "user", "content": "Respond with the single word OK."}],
        "max_tokens": 128,
        "provider": {"zdr": True},
    }
    status, _, raw = api.request("chat/completions", control)
    data = envelope(raw)
    choices = data.get("choices") or []
    if (
        status != 200
        or data.get("error")
        or not data.get("id")
        or not choices
        or choices[0].get("finish_reason") != "stop"
        or not (choices[0].get("message") or {}).get("content")
    ):
        raise ValueError("Completed Chat Completions control failed.")
    control_id = data["id"]
    lookup_ids = list(dict.fromkeys([control_id, *lookup_ids]))
    api.observed_generation_ids.update(lookup_ids)
    results = evidence["lookups"] = {candidate: [] for candidate in lookup_ids}
    lookup_budget = api.manifest["limits"]["stage_attempts"]["cost"]["metadata"] - 1  # key check
    for delay in (0, 4, 12):
        if delay:
            time.sleep(min(delay, api.remaining()))
        for candidate, checks in results.items():
            if not lookup_budget or (checks and checks[-1]["present"]):
                continue
            lookup_budget -= 1
            status, _, raw = api.request("generation", remote_id=candidate)
            if status not in (200, 404):
                raise ValueError(f"Unexpected generation lookup HTTP {status}.")
            record = envelope(raw).get("data") if status == 200 else None
            resolved = record.get("id") if isinstance(record, dict) else None
            checks.append({"http": status, "present": resolved == candidate, "remote_id": resolved})
        if not lookup_budget or all(checks and checks[-1]["present"] for checks in results.values()):
            break
    evidence["completed_control"] = control_id
    evidence["lookup_control_indexed"] = bool(results[control_id] and results[control_id][-1]["present"])
    evidence["identity_verdicts"] = {
        candidate: "verified" if checks and checks[-1]["present"] else "unconfirmed"
        for candidate, checks in results.items()
    }
    evidence["try_metadata_on_codex"] = any(
        s["streaming"] and s["metadata"] and len(s["selected"]) == 1 for s in samples
    )
    evidence["cost_coverage"] = {
        mode: [s["usage_cost"] for s in samples if s["streaming"] == streaming]
        for mode, streaming in (("unary", False), ("stream", True))
    }
    if not evidence["lookup_control_indexed"]:
        raise ValueError("Completed Chat Completions indexing control remained unconfirmed. Stop before Codex probes.")


def run_stage(stage: str) -> dict:
    """Run one manifest-bound stage and return its receipt location and verdict."""
    manifest, digest = approved_manifest()
    if stage not in manifest["stages"]:
        raise ValueError(f"Stage {stage} is outside this approval.")
    manifest_dir = Path(os.environ["OPENROUTER_RESPONSES_MANIFEST"]).resolve().parent
    cost_receipt = None
    if manifest["stages"] == ["codex"]:
        cost_receipt = verified_cost_receipt(manifest, manifest_dir)
    elif manifest["stages"] == ["cost", "codex"]:
        verify_prerequisite(manifest, manifest_dir)
    key = os.environ.get("OPENROUTER_PROBE_API_KEY")
    if not key:
        raise ValueError("Dedicated OPENROUTER_PROBE_API_KEY missing.")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise ValueError("Dedicated probe key is malformed.")
    from paid_codex import check_inputs, stage_codex

    fixtures = check_inputs(manifest, manifest_dir) if stage == "codex" else []
    ledger = Ledger(Path(LEDGER_ROOT).expanduser() / digest, manifest["limits"])
    deadline = ledger.begin(stage, key=key)
    api = Upstream(manifest, ledger, stage, deadline, key)
    evidence: dict = {
        "stage": stage,
        "manifest_sha256": digest,
        "verdict": "inconclusive",
    }
    if "prerequisite" in manifest:
        evidence["prerequisite"] = manifest["prerequisite"]
    if cost_receipt is not None:
        evidence["previous_attempt"] = manifest["previous_attempt"]
    try:
        evidence["credit"] = api.validate_credit_limit()
        if stage == "zdr":
            stage_zdr(api, evidence, manifest_dir=manifest_dir)
        elif stage == "cost":
            stage_cost(api, evidence)
        else:
            stage_codex(api, evidence, fixtures, cost_receipt=cost_receipt)
        evidence["verdict"] = "passed"
    except (
        ValueError,
        OSError,
        KeyError,
        subprocess.SubprocessError,
        http.client.HTTPException,
    ) as exc:
        evidence["reason"] = str(exc).replace(key, "<redacted>")[:1000]
        error = api.observations[-1].get("error", {}) if api.observations else {}
        if error.get("message"):
            evidence["reason"] += " " + error["message"]
    finally:
        evidence["requests"] = api.observations
        dump(ledger.directory / f"{stage}.json", evidence)
        ledger.finish(stage, evidence["verdict"])
    return {
        "stage": stage,
        "verdict": evidence["verdict"],
        "result": str(ledger.directory / f"{stage}.json"),
        **{k: evidence[k] for k in ("criterion", "reason") if k in evidence},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=[*STAGES, "selftest"])
    parser.add_argument(
        "--selftest-codex",
        type=Path,
        help="Use the pinned native Codex executable for the loopback tasks.",
    )
    parser.add_argument(
        "--selftest-manifest",
        type=Path,
        help="Exercise the manifest's account ZDR controls or its exported Codex fixtures entirely on loopback.",
    )
    args = parser.parse_args()
    os.umask(0o077)
    if args.stage == "selftest":
        from paid_selftest import selftest

        print(json.dumps(selftest(args.selftest_codex, args.selftest_manifest), sort_keys=True))
        return 0
    result = run_stage(args.stage)
    print(json.dumps(result))
    return int(result["verdict"] != "passed")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyError, OSError, ValueError) as exc:
        sys.exit(str(exc))
