"""Regression: anthropic_passthrough forwards the RAW body, preserving unknown
fields and signed thinking blocks.

Bug class: silent loss. ``MessagesRequest`` uses Pydantic ``extra='ignore'``, so
parsing + ``model_dump()`` drops unknown/future Anthropic fields. The passthrough
path must read ``raw_request.json()`` and forward it unchanged so signed thinking
blocks and forward-compatible fields survive (signature-safe).

Affected files: src/forge/proxy/passthrough.py, src/forge/proxy/server.py
"""

from __future__ import annotations

import pytest

from forge.proxy import passthrough
from forge.proxy.data_models import MessagesRequest

pytestmark = pytest.mark.regression


class _FakeResponse:
    status_code = 200
    content = b'{"ok":true}'
    headers = {"content-type": "application/json"}


class _CapturingClient:
    captured: dict = {}

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        _CapturingClient.captured = {"url": url, "json": json}
        return _FakeResponse()


# Historical assistant turn with a signed thinking block + an unknown future field.
RAW_BODY = {
    "model": "claude-opus-4-6",
    "max_tokens": 1024,
    "messages": [
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "step by step", "signature": "SIG-DO-NOT-DROP"},
                {"type": "text", "text": "answer"},
            ],
        },
        {"role": "user", "content": "continue"},
    ],
    "future_unknown_field": {"experimental": True},
}


def test_messages_request_drops_unknown_field_motivation():
    """Proves WHY raw-body forwarding is needed: MessagesRequest drops the unknown field."""
    parsed = MessagesRequest(**RAW_BODY).model_dump()
    assert "future_unknown_field" not in parsed  # silently dropped by extra='ignore'


@pytest.mark.asyncio
async def test_passthrough_forwards_raw_body_byte_for_byte(monkeypatch):
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", _CapturingClient)
    _CapturingClient.captured = {}

    await passthrough.forward(
        raw_body=RAW_BODY,
        inbound_headers={"anthropic-version": "2023-06-01"},
        base_url="https://api.anthropic.com",
        api_key="K",
        request_id="req_regress",
    )

    sent = _CapturingClient.captured["json"]
    assert sent["future_unknown_field"] == {"experimental": True}  # unknown field survives

    thinking = sent["messages"][0]["content"][0]
    assert thinking["type"] == "thinking"
    assert thinking["signature"] == "SIG-DO-NOT-DROP"  # signature preserved byte-for-byte

    assert sent == RAW_BODY  # forwarded body IS the raw body, unchanged
