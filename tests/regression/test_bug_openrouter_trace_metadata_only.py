"""Regression: the provider-trace plane is metadata-only — never prompt/completion/body.

Bug class: silent privacy leak. The provider-trace plane (openrouter_observability Phase 3)
exists to answer "what happened to this provider request?" from correlation metadata. If a
body, prompt, completion, tool I/O, or a raw auth header ever reached a persisted record, the
plane would become a second copy of sensitive payload on disk.

Root cause guarded here:
1. ``ProviderTraceRecord`` (src/forge/proxy/provider_trace_logger.py) has NO body/prompt field.
2. ``write_provider_trace`` re-applies the Phase 2 header allowlist at the persistence edge, so
   even a caller that bypasses the upstream allowlist cannot persist auth/cookie headers.

Affected files: src/forge/proxy/provider_trace_logger.py.
"""

from __future__ import annotations

import json
from dataclasses import fields

import pytest

from forge.core.telemetry import downstream as downstream_telemetry
from forge.proxy import provider_trace_logger as ptl

pytestmark = pytest.mark.regression

# Anything that would indicate request/response PAYLOAD (not correlation metadata) leaked in.
_FORBIDDEN_FIELD_NAMES = {
    "messages",
    "prompt",
    "completion",
    "content",
    "text",
    "system",
    "request_body",
    "response_body",
    "body",
    "tool_calls",
    "tool_input",
    "tool_result",
    "arguments",
    "input",
    "output",
}

_FORBIDDEN_HEADER_NAMES = {"authorization", "x-api-key", "api-key", "cookie", "set-cookie"}


def test_dataclass_has_no_payload_fields():
    names = {f.name for f in fields(ptl.ProviderTraceRecord)}
    assert names.isdisjoint(
        _FORBIDDEN_FIELD_NAMES
    ), f"payload field leaked into the schema: {names & _FORBIDDEN_FIELD_NAMES}"


def test_persisted_record_carries_no_payload_or_secret_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    ptl._warned_newer_schema = False

    # A caller hands provider_meta whose headers carry secrets (simulating a future bypass of
    # the Phase 2 allowlist). The persisted record must drop them.
    ptl.record_provider_trace(
        provider_name="openrouter",
        request_mode="streaming",
        proxy_id="crimson-apricot",
        mapped_model="openai/gpt-5.5",
        request_id="req-leak",
        forge_run_id="run_a",
        forge_root_run_id="run_root",
        provider_session_id="forge_sess_x",
        provider_command="supervisor",
        provider_meta={
            "provider": "openrouter",
            "provider_generation_id": "gen-1",
            "headers": {
                "x-request-id": "req-allow",
                "authorization": "Bearer sk-or-SECRET",
                "x-api-key": "SECRET-KEY",
                "set-cookie": "session=SECRET",
            },
        },
        stream_started=True,
        first_chunk_seen=True,
        final_usage_seen=False,
        client_disconnected=True,
        reported_cost_micros=None,
        latency_ms=12.0,
    )

    raw = downstream_telemetry._current_log_path().read_text()
    line = raw.splitlines()[0]
    record = json.loads(line)

    # No payload-bearing key in the persisted object.
    assert set(record).isdisjoint(_FORBIDDEN_FIELD_NAMES)
    # No secret header name and no secret value survives anywhere in the raw line.
    lowered = raw.lower()
    for forbidden in _FORBIDDEN_HEADER_NAMES:
        assert forbidden not in lowered, f"secret header {forbidden!r} reached disk"
    assert "secret" not in lowered  # no secret VALUE survived either
    # Only the allowlisted correlation header is retained.
    assert record["provider_headers"] == {"x-request-id": "req-allow"}
    # And the diagnostic metadata IS present (the plane still does its job).
    assert record["provider_generation_id"] == "gen-1"
    assert record["local_usage_status"] == "unavailable"  # cancelled before final usage
