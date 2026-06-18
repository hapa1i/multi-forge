"""Regression: full-body audit must never persist plaintext secrets.

Bug class: security / silent loss. ``audit_full_body`` captures request/response
structure; redaction must run BEFORE persistence so no plaintext credential,
message text, system prompt, or tool description reaches disk. Covers headers,
request body, response body, and tool payloads.

Affected files: src/forge/proxy/audit_logger.py, src/forge/proxy/utils.py
"""

from __future__ import annotations

import json

import pytest

from forge.proxy import audit_logger

pytestmark = pytest.mark.regression

BEARER = "sk-ant-secret-DO-NOT-LOG-1234567890abcdef"
APIKEY = "sk-or-v1-PLAINTEXT-LEAK-CANARY-0987654321"
COOKIE = "session=PLAINTEXT-COOKIE-CANARY"
MSG = "my password is hunter2-PLAINTEXT"
SYS = "internal PLAINTEXT-SYSTEM-PROMPT"
TOOLDESC = "runs PLAINTEXT-TOOL-DESC"
RESP = "answer PLAINTEXT-RESPONSE " + APIKEY


@pytest.fixture(autouse=True)
def _isolated_audit_home(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    yield


def test_full_body_audit_persists_no_plaintext_secret():
    audit_logger.write_full_body_record(
        request_id="req_x",
        proxy_id="p",
        mode="inspect",
        route={"template": "anthropic-passthrough"},
        request_headers={
            "Authorization": f"Bearer {BEARER}",
            "x-api-key": APIKEY,
            "cookie": COOKIE,
            "anthropic-version": "2023-06-01",
        },
        request_body={
            "model": "claude-opus-4-6",
            "system": SYS,
            "messages": [{"role": "user", "content": MSG}],
            "tools": [{"name": "Bash", "description": TOOLDESC, "input_schema": {"type": "object"}}],
        },
        response_headers={"set-cookie": COOKIE},
        response_body={"id": "msg_1", "role": "assistant", "content": [{"type": "text", "text": RESP}]},
    )

    records = audit_logger.read_audit_logs(record_type="request")
    assert records
    blob = json.dumps(records, sort_keys=True)

    for secret in (BEARER, APIKEY, COOKIE, MSG, SYS, TOOLDESC, RESP):
        assert secret not in blob, f"plaintext secret leaked into audit log: {secret!r}"

    # Structure IS retained (proves the record is still useful).
    rec = records[0]
    assert rec["full_body"] is True
    assert rec["request_headers"]["Authorization"] == {"redacted": True, "length": len(f"Bearer {BEARER}")}
    assert rec["request_headers"]["anthropic-version"] == "2023-06-01"  # non-secret header preserved
    assert rec["request_body"]["model"] == "claude-opus-4-6"  # safe field preserved
    assert rec["request_body"]["tools"][0]["name"] == "Bash"  # tool name kept, description redacted


def test_full_body_audit_through_server_path_no_plaintext(monkeypatch):
    """Drive the REAL server (middleware -> passthrough -> on_complete -> writer) with
    secret request headers/body and a secret response, then assert the audit shard holds
    no plaintext. Guards the WIRING — a leak in the server hook (e.g. forwarding raw
    headers unredacted) would slip past a test that only calls write_full_body_record()."""
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    import forge.proxy.server as server
    from forge.proxy import passthrough

    monkeypatch.setattr(server, "_ensure_runtime_state", lambda: None)
    monkeypatch.setattr(server, "PROXY_ID", "p")
    monkeypatch.setattr(server, "cost_tracker", None)
    audit_logger._drift_state.clear()

    provider = SimpleNamespace(base_url="https://api.anthropic.com")
    monkeypatch.setattr(
        server.config,
        "proxy",
        SimpleNamespace(
            wire_shape="anthropic_passthrough",
            default_tier="sonnet",
            active_template="anthropic-passthrough",
            preferred_provider="litellm",
            intercept=SimpleNamespace(mode="inspect"),
            audit=SimpleNamespace(
                audit_full_body=True, effective_redact_headers=lambda: set(), retention_days=30, max_total_mb=100
            ),
            get_provider=lambda name=None: provider,
        ),
    )
    monkeypatch.setattr("forge.core.auth.template_secrets.resolve_env_or_credential", lambda var: "UPSTREAM-KEY")

    resp_bytes = json.dumps(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": RESP}],
            "usage": {"input_tokens": 5, "output_tokens": 7},
        }
    ).encode()

    class _Resp:
        status_code = 200
        content = resp_bytes
        headers = {"content-type": "application/json"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        async def post(self, url, headers=None, json=None):
            return _Resp()

    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _Client)

    client = TestClient(server.app)
    r = client.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {BEARER}", "x-api-key": APIKEY},
        json={
            "model": "claude-opus-4-6",
            "max_tokens": 16,
            "system": SYS,
            "messages": [{"role": "user", "content": MSG}],
        },
    )
    assert r.status_code == 200

    records = audit_logger.read_audit_logs(record_type="request")
    assert records
    blob = json.dumps(records, sort_keys=True)
    for secret in (BEARER, APIKEY, MSG, SYS, RESP):
        assert secret not in blob, f"plaintext secret leaked through the server path: {secret!r}"

    full = [record for record in records if record.get("full_body")]
    assert full and full[0]["response_body"] is not None  # response captured + redacted
