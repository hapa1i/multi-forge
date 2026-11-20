"""Manifest-bound accounting and the sole upstream HTTP transport for Responses probes."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import http.client
import json
import math
import os
import re
import socket
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from paid_diagnostics import provider_diagnostic

REPO = Path(__file__).resolve().parents[4]
LEDGER_ROOT = "~/.cache/forge-openrouter-probe/response-approvals"
STAGES = ("zdr", "cost", "codex")
ACCOUNT_ZDR_OPERATIONS = ["GET /api/v1/key", "GET /api/v1/endpoints/zdr", "POST /api/v1/responses"]
ACCEPTED_REFUSAL = "account_zdr_accepted_refusal"
ASTRA = "openai/gpt-6.2-astra"
QWEN_FLAGGED_MANIFEST_SHA256 = "2feeec7f089df57f2927735a7f36d0e5244bb4afb4844971c0924f641a2e0163"
COST_CODEX_OPERATIONS = [
    "GET /api/v1/key",
    "POST /api/v1/responses",
    "POST /api/v1/chat/completions",
    "GET /api/v1/generation?id=<observed ID>",
]
ZDR_PREREQUISITE = {
    "stage": "zdr",
    "criterion": ACCEPTED_REFUSAL,
    "path": "evidence/paid-1ee865aa/zdr.json",
    "sha256": "dd050601a5c88c32f93fd077d81e620ccd7881457e5babee23a0ad8b70ca7dfb",
    "manifest_sha256": "1ee865aae6c817e5b16d72f8ec1fed98db0a49d0aa865b5e4c48674cd4e2a2bc",
}
COST_CODEX_MANIFEST_SHA256 = "0a6ac1d0ad98fa597a9b3e65027097cb2e71d724d7b4c399d820cf94d464c20d"
COST_PREREQUISITE = {
    "stage": "cost",
    "path": "evidence/paid-0a6ac1d0/cost.json",
    "sha256": "be8a91623f06bc10ea312c631dc84867c4846c02f9296db7f96a0cb809ca671a",
    "manifest_sha256": COST_CODEX_MANIFEST_SHA256,
}
CODEX_CREDIT_REFUSAL = {
    "stage": "codex",
    "path": "evidence/paid-0a6ac1d0/codex.json",
    "sha256": "7517c4d6100bcfeaf792562ae0c3c71673286d9817581271a0dc07587fcc0dc9",
    "manifest_sha256": COST_CODEX_MANIFEST_SHA256,
}
PATHS = {"responses", "chat/completions", "key", "endpoints/zdr", "generation"}
GUARD = REPO / "scripts/experiments/codex-hooks/probe-runtime.py"


def dump(path: Path, value: Any) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def tiny(model: str) -> dict:
    return {
        "model": model,
        "input": "Respond with the single word OK.",
        "max_output_tokens": 128,
        "store": False,
    }


def approved_manifest() -> tuple[dict, str]:
    path = os.environ.get("OPENROUTER_RESPONSES_MANIFEST")
    if not path:
        raise ValueError("Paid dispatch requires OPENROUTER_RESPONSES_MANIFEST and its operator-approved SHA-256.")
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if os.environ.get("OPENROUTER_RESPONSES_APPROVED_SHA256") != digest:
        raise ValueError("Paid dispatch requires operator approval for this exact manifest SHA-256.")
    manifest = json.loads(raw)
    validate_manifest(manifest)
    return manifest, digest


def validate_manifest(manifest: dict) -> None:
    stages = manifest["stages"]
    if (
        manifest["schema"] != 1
        or manifest["ledger_root"] != LEDGER_ROOT
        or stages
        not in (
            list(STAGES),
            ["zdr"],
            ["cost", "codex"],
            ["codex"],
        )
    ):
        raise ValueError("Unsupported manifest schema, ledger, or stage order.")
    limits = manifest["limits"]
    criterion = manifest.get("zdr_control", {}).get("criterion")
    if stages == ["zdr"]:
        if criterion not in ("account_zdr", ACCEPTED_REFUSAL):
            raise ValueError("Stage-60-only approval requires an account ZDR criterion.")
        if manifest["origin"] != "https://openrouter.ai" or manifest["operations"] != ACCOUNT_ZDR_OPERATIONS:
            raise ValueError("Account ZDR requires the OpenRouter origin, key and catalog reads, and Responses only.")
        if set(manifest["models"]) != {"default", "non_zdr"}:
            raise ValueError("Account ZDR requires only the positive and negative model roles.")
        generation_limit = 2
        if criterion == ACCEPTED_REFUSAL:
            if manifest.get("continues_manifest_sha256") != QWEN_FLAGGED_MANIFEST_SHA256:
                raise ValueError("Continuation must identify the manifest that produced the accepted Qwen refusal.")
            if manifest["models"] != {"default": ASTRA, "non_zdr": "qwen/qwen4-max"}:
                raise ValueError("The accepted Qwen refusal permits only the Astra positive control.")
            generation_limit = 1
        if (
            limits["generation_attempts"] != generation_limit
            or limits["metadata_attempts"] != 2
            or limits["stage_attempts"] != {"zdr": {"generation": generation_limit, "metadata": 2}}
        ):
            raise ValueError(f"Stage 60 requires {generation_limit} generation and two metadata reservations.")
    elif stages in (["cost", "codex"], ["codex"]):
        stage_attempts = {"codex": {"generation": 40, "metadata": 1}}
        if stages == ["codex"]:
            prerequisite = COST_PREREQUISITE
            operations = ["GET /api/v1/key", "POST /api/v1/responses"]
            ceiling = 5
            if manifest.get("previous_attempt") != CODEX_CREDIT_REFUSAL:
                raise ValueError("Standalone Codex requires the pinned stage 80 credit refusal.")
            setup = manifest["key_setup"]
            if (
                setup.get("operation") != "POST /api/v1/keys"
                or setup.get("max_attempts") != 1
                or setup.get("limit_usd") != ceiling
                or setup.get("minimum_remaining_usd") != 3
                or setup.get("limit_reset", "absent") is not None
                or setup.get("include_byok_in_limit") is not True
                or setup.get("expires_in_minutes") != 20
            ):
                raise ValueError("Standalone Codex requires the specified $5 probe key setup.")
        else:
            prerequisite = ZDR_PREREQUISITE
            operations = COST_CODEX_OPERATIONS
            ceiling = 2
            stage_attempts["cost"] = {"generation": 5, "metadata": 16}
        if manifest.get("prerequisite") != prerequisite or criterion is not None:
            raise ValueError("The manifest must pin the passing receipt for the preceding stage.")
        if manifest.get("origin") != "https://openrouter.ai" or manifest.get("operations") != operations:
            raise ValueError("Codex probes require the scoped OpenRouter origin and operations.")
        if manifest["models"] != {"default": ASTRA, "alternate": "google/gemini-4-carbon"}:
            raise ValueError("Codex probes require the approved Astra and Gemini models.")
        if limits != {
            "generation_attempts": sum(s["generation"] for s in stage_attempts.values()),
            "metadata_attempts": sum(s["metadata"] for s in stage_attempts.values()),
            "seconds": 900,
            "usd": ceiling,
            "stage_attempts": stage_attempts,
        }:
            raise ValueError("The requested budgets differ from the Codex probe limits.")
    elif criterion is not None or "prerequisite" in manifest:
        raise ValueError("Unsupported ZDR criterion or prerequisite for a three-stage manifest.")
    if not 0 < limits["usd"] < float("inf"):
        raise ValueError("A finite positive USD ceiling is mandatory.")
    for value in (
        limits["generation_attempts"],
        limits["metadata_attempts"],
        limits["seconds"],
    ):
        if type(value) is not int or value <= 0:
            raise ValueError("Positive integer attempt ceilings and wall-clock deadline are mandatory.")
    for s in stages:
        for kind in ("generation", "metadata"):
            value = limits["stage_attempts"][s][kind]
            if type(value) is not int or value <= 0:
                raise ValueError(f"Invalid {s}/{kind} ceiling.")
    if any(not isinstance(model, str) or not model.strip() for model in manifest["models"].values()):
        raise ValueError("A concrete model is required for each role.")


class Ledger:
    """Persist reservations before dispatch, including attempts with uncertain outcomes."""

    def __init__(self, directory: Path, limits: dict):
        self.directory = directory
        self.limits = limits
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)

    @contextlib.contextmanager
    def locked(self):
        with (self.directory / "lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.directory / "state.json"
            state = (
                json.loads(path.read_text())
                if path.exists()
                else {
                    "deadline": time.time() + self.limits["seconds"],
                    "stages": {},
                    "attempts": [],
                }
            )
            yield state
            dump(path, state)

    def begin(self, stage: str, *, key: str | None = None) -> float:
        stages = [s for s in STAGES if s in self.limits["stage_attempts"]]
        if stage not in stages:
            raise ValueError(f"Stage {stage} is outside this approval.")
        with self.locked() as state:
            if stage in state["stages"]:
                raise ValueError(f"{stage} already started under this approval. Inspect retained evidence.")
            if any(state["stages"].get(s) != "passed" for s in stages[: stages.index(stage)]):
                raise ValueError(f"An earlier stage has no passing verdict for {stage}.")
            if stages == ["cost", "codex"]:
                if not key:
                    raise ValueError("Cost and Codex must share one dedicated key.")
                fingerprint = hashlib.sha256(key.encode()).hexdigest()
                if stage == "cost":
                    state["key_sha256"] = fingerprint
                elif state.get("key_sha256") != fingerprint:
                    raise ValueError("Cost and Codex must share the same dedicated key and its spending limit.")
            remaining = state["deadline"] - time.time()
            if remaining <= 0:
                raise ValueError("Approved wall-clock window expired.")
            state["stages"][stage] = "running"
        return time.monotonic() + remaining

    def reserve(self, stage: str, kind: str, operation: str) -> None:
        with self.locked() as state:
            if state["stages"].get(stage) != "running" or time.time() >= state["deadline"]:
                raise ValueError("Stage inactive or paid deadline expired.")
            prior = [a for a in state["attempts"] if a["kind"] == kind]
            stage_max = self.limits["stage_attempts"][stage][kind]
            if len(prior) >= self.limits[kind + "_attempts"] or sum(a["stage"] == stage for a in prior) >= stage_max:
                raise ValueError(f"Approved {kind} request budget exhausted before dispatch.")
            state["attempts"].append(
                {
                    "stage": stage,
                    "kind": kind,
                    "operation": operation,
                    "time": time.time(),
                }
            )

    def finish(self, stage: str, verdict: str) -> None:
        with self.locked() as state:
            state["stages"][stage] = verdict


class Upstream:
    def __init__(self, manifest: dict, ledger: Ledger, stage: str, deadline: float, key: str):
        self.manifest, self.ledger, self.stage, self.deadline, self.key = (
            manifest,
            ledger,
            stage,
            deadline,
            key,
        )
        self.observations: list[dict] = []
        self.observed_generation_ids: set[str] = set()

    def remaining(self) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise ValueError("Approved wall-clock window expired.")
        return left

    def _connect(self, timeout: float) -> http.client.HTTPConnection:
        return http.client.HTTPSConnection("openrouter.ai", timeout=timeout)

    def request(
        self,
        operation: str,
        body: dict | None = None,
        *,
        remote_id: str = "",
        metadata: bool = False,
    ):
        if operation not in PATHS or (body is not None) != (operation in {"responses", "chat/completions"}):
            raise ValueError("Unapproved HTTP operation.")
        if body is not None and body.get("model") not in self.manifest["models"].values():
            raise ValueError("Model outside the approved manifest.")
        stages = self.manifest.get("stages")
        if stages in (["cost", "codex"], ["codex"]):
            allowed = {"cost": {"key", "responses", "chat/completions", "generation"}, "codex": {"key", "responses"}}
            if self.stage not in stages or operation not in allowed[self.stage]:
                raise ValueError("HTTP operation outside the approved cost or Codex stage.")
            if operation == "generation" and remote_id not in self.observed_generation_ids:
                raise ValueError("Generation lookup requires an ID observed in this stage.")
            if body is not None:
                provider = body.get("provider")
                if "models" in body or body.get("store", False) is not False or body.get("previous_response_id"):
                    raise ValueError("Only stateless requests for one approved model may be forwarded.")
                if provider is not None and (not isinstance(provider, dict) or provider.get("zdr") is not True):
                    raise ValueError("Explicit provider routing must require ZDR.")
                if self.stage == "cost" and (body["model"] != ASTRA or provider is None):
                    raise ValueError("The cost controls require Astra and provider.zdr=true.")
        if self.manifest.get("stages") == ["zdr"]:
            operation_name = f"{'GET' if body is None else 'POST'} /api/v1/{operation}"
            if self.stage != "zdr" or operation_name not in self.manifest["operations"]:
                raise ValueError("HTTP operation outside the approved account ZDR stage.")
            if body is not None:
                provider = body.get("provider")
                if not isinstance(provider, dict) or provider.get("zdr") is not True:
                    raise ValueError("Account ZDR requires provider.zdr=true on every generation.")
                if self.manifest["zdr_control"]["criterion"] == ACCEPTED_REFUSAL and (
                    body != dict(tiny(ASTRA), provider={"zdr": True}) or metadata
                ):
                    raise ValueError(
                        "Only the exact Astra positive control may be sent under the accepted Qwen refusal."
                    )
        path = "/api/v1/" + operation
        if operation == "generation":
            if not re.fullmatch(r"[\w.:-]{1,200}", remote_id):
                raise ValueError("Malformed lookup ID.")
            path += "?" + urlencode({"id": remote_id})
        kind = "generation" if body is not None else "metadata"
        self.remaining()
        self.ledger.reserve(self.stage, kind, operation)
        conn = self._connect(min(60, self.remaining()))
        headers = {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if metadata:
            headers["X-OpenRouter-Metadata"] = "enabled"
        timer = None
        try:
            conn.connect()
            if conn.sock is None:
                raise ValueError("Cannot enforce the absolute deadline on this connection.")
            sock = conn.sock

            def expire_socket() -> None:
                # A peer can trickle even HTTP headers before read1() gets control.
                with contextlib.suppress(OSError):
                    sock.shutdown(socket.SHUT_RDWR)

            timer = threading.Timer(self.remaining(), expire_socket)
            timer.daemon = True
            timer.start()
            self.remaining()
            conn.request(
                "POST" if body is not None else "GET",
                path,
                json.dumps(body) if body is not None else None,
                headers,
            )
            response = conn.getresponse()
            # http.client never follows redirects. An absolute monotonic deadline also bounds a trickling stream.
            pieces = bytearray()
            while True:
                # http.client detaches conn.sock for close-delimited responses;
                # the HTTPResponse still owns that socket until EOF.
                remaining = min(60, self.remaining())
                if response.isclosed():
                    break
                sock.settimeout(remaining)
                chunk = response.read1(65536)
                if not chunk:
                    break
                pieces += chunk
                if len(pieces) > 12 * 1024 * 1024:
                    raise ValueError("Probe response exceeded 12 MiB.")
            self.remaining()
            raw = bytes(pieces)
            headers_in = {k.lower(): v for k, v in response.getheaders()}
            observation: dict = {"operation": operation, "status": response.status, "model": (body or {}).get("model")}
            self.observations.append(observation)
            if diagnostic := provider_diagnostic(response.status, headers_in, raw, body, self.key):
                observation["error"] = diagnostic
            return response.status, headers_in, raw
        finally:
            if timer is not None:
                timer.cancel()
            conn.close()

    def validate_credit_limit(self) -> dict:
        status, _, raw = self.request("key")
        data = json.loads(raw).get("data", {}) if status == 200 else {}
        ceiling = self.manifest["limits"]["usd"]
        limit, remaining = data.get("limit"), data.get("limit_remaining")
        if not isinstance(limit, (float, int)) or not isinstance(remaining, (float, int)):
            raise ValueError("Dedicated key has no verified numeric credit limit.")
        if any(isinstance(n, bool) or not math.isfinite(n) for n in (limit, remaining)):
            raise ValueError("Dedicated key has no verified finite credit limit.")
        if not (0 < remaining <= limit <= ceiling) or "limit_reset" not in data or data["limit_reset"] is not None:
            raise ValueError("Dedicated key must have positive credit and a non-resetting limit within manifest USD.")
        if data.get("include_byok_in_limit") is not True:
            raise ValueError("The dedicated key must verifiably include BYOK usage in its spending limit.")
        if self.manifest.get("stages") == ["codex"] and remaining < self.manifest["key_setup"]["minimum_remaining_usd"]:
            raise ValueError("Standalone Codex requires at least $3 available before sending the native request.")
        return {
            "usd_limit": limit,
            "usd_remaining": remaining,
            "resets": False,
            "includes_byok": True,
        }
