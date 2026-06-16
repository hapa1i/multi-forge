#!/usr/bin/env python3
"""OpenRouter provider-trace Phase 0 probe helper.

Operator-gated: needs a live ``OPENROUTER_API_KEY`` resolvable by Forge. Run via
``uv run python helpers/or_probe.py <subcommand> --capture-dir <dir> --label <l>``
so ``forge.*`` imports resolve against the project venv.

Design constraints (see the harness README + the Phase 0 plan):

* **Read-only against Forge state.** Reuses ``CredentialManager`` for credential
  resolution; never writes ``~/.forge``.
* **Never prints or persists an API key.** ``creds`` emits only ``base_url`` +
  provenance. Other subcommands emit deliberately shaped records.
* **No raw body dumps by default.** ``--debug-raw`` opt-in writes raw payloads to
  the cache only (scrubbed by ``sanitize.sh``, never committed).
* **Transport != recognition.** Probe 3 records that a field *left in the request
  body* (``transported``) separately from OpenRouter *doing something with it*
  (``recognized``); when no surface confirms recognition the cell is
  ``UNVERIFIABLE`` -- a real finding, not a bug.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

HELPER_VERSION = "1"

# Recorded by NAME only (never value) in meta/run.json.
_ENV_CANDIDATES = (
    "OPENROUTER_API_KEY",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_PROVISIONING_KEY",
    "OPENROUTER_MANAGEMENT_KEY",
    "OPENROUTER_PROBE_GATEWAY_BASE_URL",
    "OPENROUTER_PROBE_GATEWAY_KEY",
    "OPENROUTER_PROBE_MODEL",
)

DEFAULT_MODEL = os.environ.get("OPENROUTER_PROBE_MODEL", "openai/gpt-4o-mini")

# GET /generation is eventually-consistent: an immediate lookup 404s even for a
# fully completed call, so probes poll with capped backoff (~23s worst case)
# before concluding a record is absent. Tune here if OpenRouter indexing is slower.
GENERATION_POLL_DELAYS = (1.0, 2.0, 4.0, 8.0, 8.0)


# --------------------------------------------------------------------------- #
# Small IO + provenance helpers (no secrets ever written)
# --------------------------------------------------------------------------- #
def _utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _git_short_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def _prefix(value: str | None) -> str | None:
    """Record only the id *prefix* (e.g. ``gen-``), not the unique id."""
    if not value:
        return None
    return value.split("-")[0] + "-" if "-" in value else value[:6]


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")


def _results_dir(capture_dir: Path) -> Path:
    d = capture_dir / "results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_record(capture_dir: Path, label: str, record: dict[str, Any]) -> None:
    _write_json(_results_dir(capture_dir) / f"{label}.record.json", record)


def write_verdict(capture_dir: Path, text: str) -> None:
    (_results_dir(capture_dir) / "verdict.txt").write_text(text + "\n")
    print(f"[or_probe] verdict: {text}")


def append_oracle(capture_dir: Path, label: str, line: str) -> None:
    with (_results_dir(capture_dir) / f"{label}.oracle.txt").open("a") as fh:
        fh.write(line + "\n")


def write_run_manifest(capture_dir: Path, stage_label: str, model: str, base_url: str) -> None:
    meta = capture_dir / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    manifest = {
        "stage": stage_label,
        "started_at": _utcnow(),
        "model": model,
        "base_url": base_url,
        "helper_version": HELPER_VERSION,
        "git_short_sha": _git_short_sha(),
        # NAMES only -- never values.
        "env_vars_present": [name for name in _ENV_CANDIDATES if os.environ.get(name)],
    }
    _write_json(meta / "run.json", manifest)


def _maybe_debug_raw(args: argparse.Namespace, capture_dir: Path, name: str, obj: Any) -> None:
    """Write a raw payload to the cache only when --debug-raw is set."""
    if not getattr(args, "debug_raw", False):
        return
    try:
        _write_json(capture_dir / "streams" / f"{name}.raw.json", obj)
    except Exception:
        pass


def credential_provenance(env_var: str) -> str:
    """Return 'env' | 'credentials.yaml' | 'absent' -- never the value."""
    if os.environ.get(env_var):
        return "env"
    try:
        from forge.core.auth.template_secrets import resolve_env_or_credential

        if resolve_env_or_credential(env_var):
            return "credentials.yaml"
    except Exception:
        pass
    return "absent"


def management_key() -> tuple[str | None, str]:
    """Resolve the OpenRouter provisioning/management key (for /activity).

    Returns (key_or_None, provenance). Provenance uses the card vocabulary:
    'env' or 'management key unavailable'.
    """
    for name in ("OPENROUTER_PROVISIONING_KEY", "OPENROUTER_MANAGEMENT_KEY"):
        val = os.environ.get(name)
        if val:
            return val, "env"
    return None, "management key unavailable"


async def resolve_openrouter_creds() -> dict[str, Any]:
    from forge.core.llm.credentials import CredentialManager

    return await CredentialManager.default().get_credentials("openrouter")


# --------------------------------------------------------------------------- #
# HTTP + client helpers
# --------------------------------------------------------------------------- #
def _openai_client(creds: dict[str, Any]) -> Any:
    from openai import AsyncOpenAI

    return AsyncOpenAI(
        api_key=creds["api_key"],
        base_url=creds["base_url"],
        default_headers=creds.get("extra_headers", {}),
    )


async def _http_get(url: str, key: str, params: dict[str, str] | None = None) -> tuple[int, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {key}"}, params=params)
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, None


def _generation_present(status: int | None, data: Any) -> bool:
    """True only for an HTTP 200 lookup that returned a real record body.

    OpenRouter returns a *truthy* JSON error envelope (``{"error": {...}}``) on a
    404, so ``bool(body)`` alone reports an error body as 'present' -- the false
    positive that flipped probe 2's verdict. Require status 200 + a non-error dict.
    """
    return status == 200 and isinstance(data, dict) and bool(data) and "error" not in data


async def _poll_generations(base_url: str, key: str, ids: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Poll ``GET /generation?id=`` for several ids together until each is present.

    The lookup is eventually-consistent: an immediate query 404s even for a fully
    completed call (probe 1), so a single immediate lookup cannot distinguish
    'record absent' from 'not yet indexed'. Poll with capped backoff and check the
    ids interleaved so each gets comparable indexing time (a fair baseline compare).
    Returns ``{label: {status, present, attempts}}``.
    """
    pending = dict(ids)
    out: dict[str, dict[str, Any]] = {label: {"status": None, "present": False, "attempts": 0} for label in ids}
    for delay in (0.0, *GENERATION_POLL_DELAYS):
        if not pending:
            break
        if delay:
            await asyncio.sleep(delay)
        for label, gen_id in list(pending.items()):
            status, data = await _http_get(f"{base_url}/generation", key, params={"id": gen_id})
            out[label]["attempts"] += 1
            out[label]["status"] = status
            if _generation_present(status, data):
                out[label]["present"] = True
                del pending[label]
    return out


async def _poll_generation(base_url: str, key: str, gen_id: str) -> dict[str, Any]:
    """Poll a single gen-id to present-or-exhausted (see ``_poll_generations``)."""
    return (await _poll_generations(base_url, key, {"id": gen_id}))["id"]


async def _poll_generation_body(base_url: str, key: str, gen_id: str) -> tuple[int | None, Any]:
    """Poll until the record is present (HTTP 200) or attempts exhausted; return the
    final ``(status, body)``.

    Probe 3 must inspect the *indexed* generation record for an echoed field. An
    immediate lookup 404s (indexing lag), so a single un-polled check would read a
    recognized field as 'not recognized' -- an artifact, not a finding.
    """
    status: int | None = None
    data: Any = None
    for delay in (0.0, *GENERATION_POLL_DELAYS):
        if delay:
            await asyncio.sleep(delay)
        status, data = await _http_get(f"{base_url}/generation", key, params={"id": gen_id})
        if _generation_present(status, data):
            break
    return status, data


async def _http_post_chat(
    base_url: str,
    key: str,
    body: dict[str, Any],
    extra_headers: dict[str, str],
) -> tuple[int, Any, dict[str, str]]:
    import httpx

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    headers.update(extra_headers or {})
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{base_url}/chat/completions", headers=headers, json=body)
        try:
            data = resp.json()
        except Exception:
            data = None
        return resp.status_code, data, dict(resp.headers)


async def _stream_chunk_ids(client: Any, model: str, prompt: str, max_tokens: int = 64) -> dict[str, Any]:
    stream = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        stream=True,
        stream_options={"include_usage": True},
    )
    ids: list[str] = []
    saw_usage = False
    try:
        async for chunk in stream:
            cid = getattr(chunk, "id", None)
            if cid:
                ids.append(cid)
            if getattr(chunk, "usage", None):
                saw_usage = True
    finally:
        try:
            await stream.close()
        except Exception:
            pass
    return {
        "first_id": ids[0] if ids else None,
        "count": len(ids),
        "stable": (len(set(ids)) <= 1) if ids else None,
        "saw_usage": saw_usage,
    }


async def _canonical_preserves_provider_id(model: str) -> bool:
    """True iff Forge's canonical CompletionResponse exposes a provider id via a
    stable typed field. Expected False: the gen id only survives in ``.raw``
    ('debugging only'), so the typed surface drops it -- the synthetic
    ``chatcmpl-<ts>`` id (minted later by the proxy adapter) stays separate.
    """
    from forge.core.llm import Message, ModelHyperparameters
    from forge.core.llm.clients.openrouter import OpenRouterClient
    from forge.core.llm.credentials import CredentialManager

    client = OpenRouterClient(model=model, provider="openrouter", credentials=CredentialManager.default())
    resp = await client.complete(
        [Message(role="user", content="Reply with exactly: OK")],
        hyperparams=ModelHyperparameters(max_tokens=16),
    )
    return any(getattr(resp, field, None) for field in ("id", "response_id", "provider_generation_id"))


async def _timed_stream(
    base_url: str,
    key: str,
    body: dict[str, Any],
    extra_headers: dict[str, str],
) -> dict[str, Any]:
    """One streaming POST; measure first-token + total latency, cache, provider."""
    import httpx

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    headers.update(extra_headers or {})
    start = time.monotonic()
    first_token_ms: float | None = None
    cached: int | None = None
    provider: str | None = None
    status: int | None = None
    ok = False
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", f"{base_url}/chat/completions", headers=headers, json=body) as resp:
                status = resp.status_code
                if resp.status_code >= 400:
                    await resp.aread()
                    return {
                        "ok": False,
                        "status": status,
                        "first_token_ms": None,
                        "total_ms": None,
                        "cached_tokens": None,
                        "provider": None,
                    }
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:") :].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        obj = json.loads(payload)
                    except Exception:
                        continue
                    if first_token_ms is None:
                        choices = obj.get("choices") or []
                        if choices and (choices[0].get("delta") or {}).get("content"):
                            first_token_ms = (time.monotonic() - start) * 1000.0
                    usage = obj.get("usage")
                    if usage:
                        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", cached)
                    if obj.get("provider"):
                        provider = obj.get("provider")
                ok = True
    except Exception:
        ok = False
    total_ms = (time.monotonic() - start) * 1000.0
    return {
        "ok": ok,
        "status": status,
        "first_token_ms": (round(first_token_ms, 1) if first_token_ms is not None else None),
        "total_ms": round(total_ms, 1) if ok else None,
        "cached_tokens": cached,
        "provider": provider,
    }


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #
async def cmd_creds(args: argparse.Namespace) -> int:
    capture_dir = Path(args.capture_dir)
    meta = capture_dir / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    try:
        creds = await resolve_openrouter_creds()
    except Exception as e:  # NoApiKeyError etc. -- message may name the env var, not the value
        (meta / "key-provenance.txt").write_text("absent\n")
        print(f"ERROR: could not resolve OPENROUTER_API_KEY: {e}", file=sys.stderr)
        return 1
    base_url = creds["base_url"]
    prov = credential_provenance("OPENROUTER_API_KEY")
    write_run_manifest(capture_dir, args.label, args.model, base_url)
    (meta / "base-url.txt").write_text(base_url + "\n")
    (meta / "key-provenance.txt").write_text(prov + "\n")
    # stdout: base_url + provenance ONLY (never the key).
    print(f"base_url={base_url}")
    print(f"provenance={prov}")
    return 0


async def cmd_genid(args: argparse.Namespace) -> int:
    capture_dir = Path(args.capture_dir)
    label = args.label
    model = args.model
    creds = await resolve_openrouter_creds()
    base_url, key = creds["base_url"], creds["api_key"]
    extra_headers = creds.get("extra_headers", {})
    write_run_manifest(capture_dir, label, model, base_url)

    record: dict[str, Any] = {
        "ts": _utcnow(),
        "probe": "genid",
        "mapped_model": model,
        "body_id_present": None,
        "body_id_prefix": None,
        "header_id_name": None,
        "stream_first_chunk_id_present": None,
        "stream_id_stable": None,
        "stream_chunk_count": None,
        "generation_lookup_status": None,
        "generation_lookup_has_data": None,
        "generation_lookup_attempts": None,
        "forge_canonical_type_preserved_provider_id": None,
        "errors": [],
    }
    body_id: str | None = None
    stream_id: str | None = None

    # Non-streaming via httpx: full header + body control.
    try:
        status, data, headers = await _http_post_chat(
            base_url,
            key,
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                "max_tokens": 16,
            },
            extra_headers,
        )
        _maybe_debug_raw(args, capture_dir, f"{label}-nonstream", {"status": status, "data": data})
        body_id = data.get("id") if isinstance(data, dict) else None
        record["body_id_present"] = bool(body_id)
        record["body_id_prefix"] = _prefix(body_id)
        if body_id:
            for hname, hval in headers.items():  # record header NAME only
                if hval == body_id:
                    record["header_id_name"] = hname
                    break
        append_oracle(
            capture_dir,
            label,
            f"non-streaming body.id present={bool(body_id)} prefix={_prefix(body_id)} "
            f"header_carrier={record['header_id_name']}",
        )
    except Exception as e:
        record["errors"].append(f"nonstream: {e}")

    # Streaming via the OpenAI SDK: chunk.id.
    try:
        sres = await _stream_chunk_ids(_openai_client(creds), model, "Count slowly: one, two, three, four, five.")
        stream_id = sres["first_id"]
        record["stream_first_chunk_id_present"] = bool(stream_id)
        record["stream_id_stable"] = sres["stable"]
        record["stream_chunk_count"] = sres["count"]
        append_oracle(
            capture_dir,
            label,
            f"streaming chunk.id present={bool(stream_id)} stable={sres['stable']} chunks={sres['count']}",
        )
    except Exception as e:
        record["errors"].append(f"stream: {e}")

    # Generation lookup -- polled, because it is eventually-consistent (an immediate
    # query 404s even for this completed call). The attempt count also reveals the
    # indexing latency a later reconciliation card would face.
    lookup_id = body_id or stream_id
    if lookup_id:
        try:
            poll = await _poll_generation(base_url, key, lookup_id)
            record["generation_lookup_status"] = poll["status"]
            record["generation_lookup_has_data"] = poll["present"]
            record["generation_lookup_attempts"] = poll["attempts"]
            append_oracle(
                capture_dir,
                label,
                f"/generation?id status={poll['status']} present={poll['present']} attempts={poll['attempts']}",
            )
        except Exception as e:
            record["errors"].append(f"generation: {e}")

    # Structural-drop check: Forge's canonical types vs the provider gen id.
    try:
        preserved = await _canonical_preserves_provider_id(model)
        record["forge_canonical_type_preserved_provider_id"] = preserved
        append_oracle(
            capture_dir,
            label,
            f"forge canonical type preserved provider id = {preserved}",
        )
    except Exception as e:
        record["errors"].append(f"drop-check: {e}")

    write_record(capture_dir, label, record)

    if record["stream_first_chunk_id_present"]:
        v = "[GENID-IN-STREAM-CHUNK]"
    elif record["body_id_present"]:
        v = "[GENID-IN-BODY]"
    elif record["header_id_name"]:
        v = "[GENID-HEADER-ONLY]"
    elif record["generation_lookup_has_data"]:
        v = "[GENID-LOOKUP-ONLY]"
    elif record["errors"]:
        v = "[GENID-INCONCLUSIVE]"
    else:
        v = "[GENID-ABSENT]"
    write_verdict(capture_dir, v)
    return 1 if v == "[GENID-INCONCLUSIVE]" else 0


async def cmd_cancel(args: argparse.Namespace) -> int:
    capture_dir = Path(args.capture_dir)
    label = args.label
    model = args.model
    creds = await resolve_openrouter_creds()
    base_url, key = creds["base_url"], creds["api_key"]
    write_run_manifest(capture_dir, label, model, base_url)

    record: dict[str, Any] = {
        "ts": _utcnow(),
        "probe": "cancel",
        "mapped_model": model,
        "stream_started": False,
        "first_chunk_seen": False,
        "final_usage_seen": False,
        "client_disconnected": False,
        "stop_reason": None,
        "provider_generation_id_prefix": None,
        "generation_lookup_status": None,
        "generation_lookup_present": None,
        "generation_lookup_attempts": None,
        "baseline_generation_id_prefix": None,
        "baseline_lookup_status": None,
        "baseline_lookup_present": None,
        "activity_status": None,
        "activity_present": None,
        "management_key_provenance": None,
        "local_usage_status": "unavailable",
        "dashboard_check": "Operator: open the OpenRouter dashboard Activity view and confirm whether this "
        "aborted request appears.",
        "errors": [],
    }
    first_id: str | None = None

    try:
        stream = await _openai_client(creds).chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": "Write a long, detailed, multi-paragraph essay about the ocean.",
                }
            ],
            max_tokens=2048,
            stream=True,
            stream_options={"include_usage": True},
        )
        record["stream_started"] = True
        async for chunk in stream:
            record["first_chunk_seen"] = True
            cid = getattr(chunk, "id", None)
            if cid:
                first_id = cid
                record["provider_generation_id_prefix"] = _prefix(cid)
            # Deliberate in-process client close after the FIRST chunk -- precise
            # client disconnect, not a process kill.
            await stream.close()
            record["client_disconnected"] = True
            record["stop_reason"] = "deliberate client close after first chunk"
            break
        else:
            record["stop_reason"] = "stream ended before first chunk"
    except Exception as e:
        record["errors"].append(f"stream: {e}")

    # Completed-call baseline: the control that makes [REMOTE-ABSENT] assertable.
    # Because an immediate /generation 404s even for a completed call, only a
    # baseline that DOES become retrievable in the poll window lets us read the
    # aborted id's absence as real rather than not-yet-indexed.
    baseline_id: str | None = None
    try:
        completed = await _openai_client(creds).chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=16,
        )
        baseline_id = getattr(completed, "id", None)
        record["baseline_generation_id_prefix"] = _prefix(baseline_id)
    except Exception as e:
        record["errors"].append(f"baseline: {e}")

    poll_ids: dict[str, str] = {}
    if first_id:
        poll_ids["aborted"] = first_id
    if baseline_id:
        poll_ids["baseline"] = baseline_id
    if poll_ids:
        try:
            polled = await _poll_generations(base_url, key, poll_ids)
            if "aborted" in polled:
                record["generation_lookup_status"] = polled["aborted"]["status"]
                record["generation_lookup_present"] = polled["aborted"]["present"]
                record["generation_lookup_attempts"] = polled["aborted"]["attempts"]
            if "baseline" in polled:
                record["baseline_lookup_status"] = polled["baseline"]["status"]
                record["baseline_lookup_present"] = polled["baseline"]["present"]
            append_oracle(
                capture_dir,
                label,
                f"/generation aborted: status={record['generation_lookup_status']} "
                f"present={record['generation_lookup_present']} attempts={record['generation_lookup_attempts']}; "
                f"baseline: status={record['baseline_lookup_status']} present={record['baseline_lookup_present']}",
            )
        except Exception as e:
            record["errors"].append(f"generation: {e}")

    mkey, mprov = management_key()
    record["management_key_provenance"] = mprov
    if mkey:
        try:
            astatus, adata = await _http_get(f"{base_url}/activity", mkey)
            record["activity_status"] = astatus
            present = bool(first_id and adata is not None and first_id in json.dumps(adata))
            record["activity_present"] = present
            append_oracle(
                capture_dir,
                label,
                f"/activity status={astatus} aborted_id_present={present}",
            )
        except Exception as e:
            record["errors"].append(f"activity: {e}")
    else:
        append_oracle(capture_dir, label, "/activity skipped: management key unavailable")

    write_record(capture_dir, label, record)

    # Verdict gates on HTTP 200 (present) AND on the completed baseline indexing:
    # [REMOTE-ABSENT] is only honest when the control DID become retrievable while
    # the aborted id did not. If even the baseline never indexed in-window, the
    # poll was too short to conclude anything -> [REMOTE-INCONCLUSIVE].
    queried = record["generation_lookup_status"] is not None or record["activity_status"] is not None
    baseline_ok = record["baseline_lookup_present"] is True
    if record["generation_lookup_present"]:
        v = "[REMOTE-PRESENT-GENERATION]"
    elif record["activity_present"]:
        v = "[REMOTE-PRESENT-ACTIVITY]"
    elif queried and not record["errors"] and baseline_ok:
        v = "[REMOTE-ABSENT]"  # control indexed, aborted id did not -- a PASS; justifies local-only "unavailable"
    else:
        v = "[REMOTE-INCONCLUSIVE]"  # baseline never indexed (or a query errored): window too short to conclude
    write_verdict(capture_dir, v)
    return 1 if v == "[REMOTE-INCONCLUSIVE]" else 0


def _cell_verdict(cell: dict[str, Any]) -> str:
    if cell["errors"] or cell["http_status"] is None or not cell["transported"]:
        return "[TRANSPORT-FAILED]"
    return "[TRANSPORTED+RECOGNIZED]" if cell["recognized"] else "[TRANSPORTED+UNVERIFIABLE]"


async def cmd_session_transport(args: argparse.Namespace) -> int:
    capture_dir = Path(args.capture_dir)
    label = args.label
    model = args.model
    creds = await resolve_openrouter_creds()
    base_url = creds["base_url"]
    key = creds["api_key"]
    extra_headers = creds.get("extra_headers", {})
    write_run_manifest(capture_dir, label, model, base_url)

    gateway = os.environ.get("OPENROUTER_PROBE_GATEWAY_BASE_URL")
    # Keep the secret keys OUT of `routes` -- that list feeds the written cells/record below.
    # Bundling the api_key alongside the non-secret route name/url taints the whole collection,
    # so CodeQL reports its serialized siblings as clear-text secret storage (py/clear-text-storage
    # false positive). Look the key up by route name instead; it only ever reaches the Bearer header.
    routes: list[tuple[str, str]] = [("direct", base_url)]
    route_keys: dict[str, str] = {"direct": key}
    if gateway:
        routes.append(("gateway", gateway.rstrip("/")))
        route_keys["gateway"] = os.environ.get("OPENROUTER_PROBE_GATEWAY_KEY") or key

    fields = (("session_id", "forge_sess_probe0"), ("user", "forge_user_probe0"))
    cells: list[dict[str, Any]] = []

    for route_name, route_url in routes:
        route_key = route_keys[route_name]
        for field, value in fields:
            cell: dict[str, Any] = {
                "route": route_name,
                "field": field,
                "body_key": field,  # we control the body -> exact outgoing key
                "transported": False,
                "recognized": None,
                "http_status": None,
                "errors": [],
            }
            body = {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
                "max_tokens": 16,
                field: value,
            }
            try:
                status, data, _ = await _http_post_chat(route_url, route_key, body, extra_headers)
                cell["http_status"] = status
                cell["transported"] = status < 400
                _maybe_debug_raw(
                    args,
                    capture_dir,
                    f"{label}-{route_name}-{field}",
                    {"status": status, "data": data},
                )
                recognized = False
                if isinstance(data, dict):
                    if value in json.dumps(data):
                        recognized = True
                    else:
                        gen_id = data.get("id")
                        if gen_id and route_name == "direct":
                            # Poll: /generation is eventually-consistent, so an
                            # immediate lookup would read a stored field as absent.
                            gstatus, gdata = await _poll_generation_body(route_url, route_key, gen_id)
                            recognized = _generation_present(gstatus, gdata) and value in json.dumps(gdata)
                cell["recognized"] = recognized if cell["transported"] else None
            except Exception as e:
                cell["errors"].append(str(e))
            append_oracle(
                capture_dir,
                label,
                f"{route_name}/{field}: {_cell_verdict(cell)} (status={cell['http_status']})",
            )
            cells.append(cell)

    if not gateway:
        append_oracle(capture_dir, label, "[GATEWAY-SKIPPED: no gateway provided]")

    record = {
        "ts": _utcnow(),
        "probe": "session-transport",
        "mapped_model": model,
        "gateway_tested": bool(gateway),
        "cells": cells,
        "errors": [],
    }
    write_record(capture_dir, label, record)

    def cell_for(route: str, field: str) -> dict[str, Any] | None:
        return next((c for c in cells if c["route"] == route and c["field"] == field), None)

    direct_session = cell_for("direct", "session_id")
    direct_user = cell_for("direct", "user")
    if any(c["errors"] or c["http_status"] is None for c in cells if c["route"] == "direct"):
        v = "[CHANNEL-TRANSPORT-FAILED]"
    elif direct_session and direct_session["recognized"]:
        v = "[CHANNEL-SESSION_ID-RECOGNIZED]"
    elif direct_user and direct_user["recognized"]:
        v = "[CHANNEL-USER-RECOGNIZED]"  # Phase 5 channel correction: session_id -> user
    else:
        v = "[CHANNEL-UNVERIFIABLE]"
    write_verdict(capture_dir, v)
    return 1 if v == "[CHANNEL-TRANSPORT-FAILED]" else 0


def _summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    oks = [s for s in samples if s["ok"]]

    def mean(vals: list[float | None]) -> float | None:
        nums = [v for v in vals if v is not None]
        return round(sum(nums) / len(nums), 1) if nums else None

    return {
        "n": len(samples),
        "ok": len(oks),
        "first_token_ms_mean": mean([s["first_token_ms"] for s in oks]),
        "total_ms_mean": mean([s["total_ms"] for s in oks]),
        "cached_tokens_seen": any((s["cached_tokens"] or 0) > 0 for s in oks),
        "providers": sorted({s["provider"] for s in oks if s["provider"]}),
        "failure_rate": round(1 - len(oks) / len(samples), 2) if samples else None,
    }


def _arm_signal(base: dict[str, Any], sticky: dict[str, Any]) -> str | None:
    """Per-arm signal vs baseline: 'improve' | 'degrade' | 'neutral', or None if
    the arm has no comparable total-latency mean."""
    b, s = base.get("total_ms_mean"), sticky.get("total_ms_mean")
    if b is None or s is None:
        return None
    if sticky.get("cached_tokens_seen") and not base.get("cached_tokens_seen"):
        return "improve"
    if s < b * 0.85:
        return "improve"
    if s > b * 1.15:
        return "degrade"
    return "neutral"


def _routing_verdict(arms: dict[str, Any]) -> str:
    """Verdict across BOTH sticky arms (session_id and user), not just session_id --
    otherwise a material `user` improvement/degradation hides behind a neutral
    `session_id`. Degrade dominates (the card's adverse pin-to-worse-provider case)."""
    base = arms.get("baseline", {})
    if not base.get("ok"):
        return "[ROUTING-INCONCLUSIVE]"
    signals = [_arm_signal(base, arms.get(name, {})) for name in ("sticky_session_id", "sticky_user")]
    if any(sig is None for sig in signals):
        return "[ROUTING-INCONCLUSIVE]"
    if "degrade" in signals:
        return "[STICKY-DEGRADES]"
    if "improve" in signals:
        return "[STICKY-IMPROVES]"
    return "[STICKY-NEUTRAL]"


async def cmd_routing(args: argparse.Namespace) -> int:
    capture_dir = Path(args.capture_dir)
    label = args.label
    model = args.model
    creds = await resolve_openrouter_creds()
    base_url, key = creds["base_url"], creds["api_key"]
    extra_headers = creds.get("extra_headers", {})
    write_run_manifest(capture_dir, label, model, base_url)

    big_prompt = "You are reviewing a plan. " + ("Context paragraph. " * 200) + "Reply with exactly: OK"
    arm_extras: dict[str, dict[str, str]] = {
        "baseline": {},
        "sticky_session_id": {"session_id": "forge_sess_routing0"},
        "sticky_user": {"user": "forge_user_routing0"},
    }
    arms: dict[str, Any] = {}
    for arm, extra in arm_extras.items():
        samples: list[dict[str, Any]] = []
        for _ in range(args.repeats):
            body: dict[str, Any] = {
                "model": model,
                "messages": [{"role": "user", "content": big_prompt}],
                "max_tokens": 16,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            body.update(extra)
            samples.append(await _timed_stream(base_url, key, body, extra_headers))
        arms[arm] = _summarize(samples)
        append_oracle(capture_dir, label, f"{arm}: {arms[arm]}")

    write_record(
        capture_dir,
        label,
        {
            "ts": _utcnow(),
            "probe": "routing",
            "mapped_model": model,
            "repeats": args.repeats,
            "arms": arms,
        },
    )
    v = _routing_verdict(arms)
    write_verdict(capture_dir, v)
    return 1 if v == "[ROUTING-INCONCLUSIVE]" else 0


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
DISPATCH: dict[str, Callable[[argparse.Namespace], Coroutine[Any, Any, int]]] = {
    "creds": cmd_creds,
    "genid": cmd_genid,
    "cancel": cmd_cancel,
    "session-transport": cmd_session_transport,
    "routing": cmd_routing,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenRouter provider-trace Phase 0 probe helper")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in DISPATCH:
        sp = sub.add_parser(name)
        sp.add_argument("--capture-dir", required=True)
        sp.add_argument("--label", default=name)
        sp.add_argument("--model", default=DEFAULT_MODEL)
        sp.add_argument(
            "--debug-raw",
            action="store_true",
            help="dump raw payloads to the cache (never committed)",
        )
        if name == "routing":
            sp.add_argument("--repeats", type=int, default=5)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(DISPATCH[args.cmd](args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
