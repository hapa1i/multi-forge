"""OpenRouter remote-reconciliation adapter -- the first backend remote adapter.

A narrow ``httpx`` REST client for OpenRouter's account-side metadata endpoint. This is NOT the
OpenAI-SDK chat client in ``core/llm/clients/openrouter.py``: ``/api/v1/generation`` is an
OpenRouter-proprietary REST endpoint, not an OpenAI-compatible chat call.

MVP: generation lookup only. Metadata-only -- it reads a fixed allowlist of correlation/usage
fields off the response and NEVER calls ``/generation/content`` (the prompt/completion endpoint),
so no payload can reach a ``RemoteRecord``.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from forge.backend.remote.base import RemoteAdapterError, RemoteCapability, RemoteRecord
from forge.backend.sources import get_model_source
from forge.core.auth.template_secrets import resolve_env_or_credential_with_source

_SOURCE_ID = "openrouter"
_API_KEY_VAR = "OPENROUTER_API_KEY"
_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_GENERATION_PATH = "generation"


class OpenRouterRemoteAdapter:
    """Account-side metadata lookups for the ``openrouter`` source (generation API)."""

    source_id = _SOURCE_ID

    def capabilities(self) -> RemoteCapability:
        # MVP: single-id generation lookup with the normal key. Windowed activity/analytics
        # (management key) is the declared-but-unimplemented follow-on.
        return RemoteCapability(
            single_lookup=True,
            single_lookup_key="normal",
            single_lookup_credential_id="openrouter",
        )

    def lookup_remote_record(self, remote_id: str, *, timeout_s: float = 5.0) -> RemoteRecord:
        import httpx

        endpoint = f"GET /{_GENERATION_PATH}"
        # Pre-check the key so a missing credential is renderable data (not_authorized), never an
        # HTTP round-trip or a raised error. Provenance only -- the value is never echoed.
        api_key, _ = resolve_env_or_credential_with_source(_API_KEY_VAR)
        if not api_key:
            return RemoteRecord(
                remote_id=remote_id,
                outcome="not_authorized",
                endpoint=endpoint,
                detail=f"{_API_KEY_VAR} is not configured",
            )

        url = f"{self._base_url().rstrip('/')}/{_GENERATION_PATH}"
        try:
            with httpx.Client(timeout=httpx.Timeout(timeout_s)) as client:
                resp = client.get(url, params={"id": remote_id}, headers={"Authorization": f"Bearer {api_key}"})
        except (httpx.TimeoutException, httpx.RequestError) as e:
            # Network/timeout -> renderable data, not an exception (sanitized: class name only).
            return RemoteRecord(
                remote_id=remote_id,
                outcome="unavailable",
                endpoint=endpoint,
                detail=f"request failed: {type(e).__name__}",
            )
        return self._map_response(remote_id, endpoint, resp)

    def fetch_activity(
        self, *, period_start: datetime | None, period_end: datetime | None, timeout_s: float = 5.0
    ) -> list[RemoteRecord]:
        # Windowed activity (management key) is the deferred follow-on; the single-id op never
        # calls this. Declared on the protocol so adding it later needs no MVP rework.
        raise RemoteAdapterError("windowed activity is a follow-on; not supported in this build")

    # --- internals ---------------------------------------------------------

    def _base_url(self) -> str:
        # Resolve the endpoint from the model-source catalog (single source of truth), honoring an
        # OPENROUTER_BASE_URL override and falling back to the catalog default.
        source = get_model_source(_SOURCE_ID)
        endpoint = source.endpoint
        if endpoint.value:
            override, _ = resolve_env_or_credential_with_source(endpoint.value)
            if override:
                return override
        return endpoint.default_url or _DEFAULT_BASE_URL

    def _map_response(self, remote_id: str, endpoint: str, resp: Any) -> RemoteRecord:
        status = resp.status_code
        if status == 200:
            return self._record_from_body(remote_id, endpoint, resp)
        if status == 404:
            return RemoteRecord(remote_id=remote_id, outcome="not_found", endpoint=endpoint, http_status=404)
        if status in (401, 403):
            return RemoteRecord(remote_id=remote_id, outcome="not_authorized", endpoint=endpoint, http_status=status)
        # All other 4xx (incl. 429 rate limit) + 5xx -> unavailable, carrying the status.
        return RemoteRecord(
            remote_id=remote_id,
            outcome="unavailable",
            endpoint=endpoint,
            http_status=status,
            detail=f"unexpected status {status}",
        )

    def _record_from_body(self, remote_id: str, endpoint: str, resp: Any) -> RemoteRecord:
        def _unavailable(detail: str) -> RemoteRecord:
            return RemoteRecord(
                remote_id=remote_id, outcome="unavailable", endpoint=endpoint, http_status=200, detail=detail
            )

        try:
            payload = resp.json()
        except ValueError:
            return _unavailable("malformed response body")

        # A 200 that wraps an error envelope ({"error": {...}} with no generation "data") is not a
        # real record -- classify it as unavailable so it never renders as a misleading join.
        if isinstance(payload, dict) and "error" in payload and not isinstance(payload.get("data"), dict):
            return _unavailable("backend returned a 200 error envelope")

        # Accept only a generation object: a top-level dict, optionally under a "data" wrapper. A
        # non-dict body or a non-dict "data" wrapper is malformed -- never a (misleading) empty "found".
        if not isinstance(payload, dict):
            return _unavailable("malformed response body")
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            return _unavailable("malformed response body")

        # Allowlisted metadata reads only -- content-like fields are never touched, so prompt /
        # completion text cannot enter the record even if the body carries it. The coercers are
        # total (NaN/Infinity/overflow/bool/wrong-type -> None, never raise); the try is a net so a
        # surprising 200 body always becomes data, never an exception (the error-vs-data invariant).
        try:
            cost_micros = _as_cost_micros(data.get("total_cost"))
            input_tokens = _as_int(data.get("native_tokens_prompt"), data.get("tokens_prompt"))
            output_tokens = _as_int(data.get("native_tokens_completion"), data.get("tokens_completion"))
        except (ValueError, TypeError, OverflowError):
            return _unavailable("unparseable usage fields")
        cancelled = data.get("cancelled")
        return RemoteRecord(
            remote_id=str(data.get("id") or remote_id),
            outcome="found",
            endpoint=endpoint,
            http_status=200,
            remote_input_tokens=input_tokens,
            remote_output_tokens=output_tokens,
            remote_cost_micros=cost_micros,
            remote_provider=_as_str(data.get("provider_name")),
            cancelled=bool(cancelled) if cancelled is not None else None,
            remote_request_id=_as_str(data.get("upstream_id")),
        )


def _as_int(*candidates: Any) -> int | None:
    for value in candidates:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                continue  # NaN/Infinity is not a token count -- fall through, never int(inf)/int(nan)
            return int(value)
    return None


def _as_cost_micros(value: Any) -> int | None:
    # bool is an int subclass but never a real cost; NaN/Infinity/overflow -> no cost, not a crash.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        usd = float(value)
    except (OverflowError, ValueError):
        return None  # int too large to convert to float
    if not math.isfinite(usd):
        return None
    return round(usd * 1_000_000)


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
