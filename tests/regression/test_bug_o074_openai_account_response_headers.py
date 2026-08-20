"""Regression for O074: upstream OpenAI account metadata crossed the response boundary.

Root cause: the shared response-header denylist omitted OpenAI's organization and
project selectors. Both ``passthrough.py`` and ``responses_passthrough.py`` relay
through ``response_headers.py``, so either transport could expose the upstream account.
"""

from __future__ import annotations

import pytest

from forge.proxy import passthrough, responses_passthrough
from tests.fixtures.proxy_transport import FakeResponse, ProxyTransportFake

pytestmark = pytest.mark.regression


@pytest.mark.asyncio
async def test_bug_o074_messages_drops_mixed_case_openai_account_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = ProxyTransportFake(
        response=FakeResponse(
            content=b'{"type":"message"}',
            headers={
                "content-type": "application/json",
                "oPeNaI-OrGaNiZaTiOn": "org-upstream",
                "OPENAI-project": "project-upstream",
                "Anthropic-RateLimit-Requests-Remaining": "4",
            },
        )
    )
    monkeypatch.setattr(passthrough.httpx, "AsyncClient", transport.client)

    response = await passthrough.forward(
        raw_body={"model": "claude", "messages": []},
        inbound_headers={},
        base_url="https://api.anthropic.test",
        api_key="test-key",
        request_id="forge-messages-id",
    )

    assert "openai-organization" not in response.headers
    assert "openai-project" not in response.headers
    assert response.headers["anthropic-ratelimit-requests-remaining"] == "4"
    assert response.headers["x-request-id"] == "forge-messages-id"


@pytest.mark.asyncio
async def test_bug_o074_responses_drops_mixed_case_openai_account_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = ProxyTransportFake(
        response=FakeResponse(
            content=b'{"id":"resp_1"}',
            headers={
                "content-type": "application/json",
                "OpenAI-ORGANIZATION": "org-upstream",
                "OpEnAi-PrOjEcT": "project-upstream",
                "openai-processing-ms": "42",
            },
        )
    )
    monkeypatch.setattr(responses_passthrough.httpx, "AsyncClient", transport.client)

    response = await responses_passthrough.forward(
        method="GET",
        url_path="/v1/responses/resp_1",
        body=None,
        query_string="",
        inbound_headers={},
        base_url="https://api.openai.test",
        api_key="test-key",
        request_id="forge-responses-id",
    )

    assert "openai-organization" not in response.headers
    assert "openai-project" not in response.headers
    assert response.headers["openai-processing-ms"] == "42"
    assert response.headers["x-request-id"] == "forge-responses-id"
