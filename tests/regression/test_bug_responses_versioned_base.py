"""A saved Responses base may already include the upstream API version."""

import pytest

from forge.proxy import responses_passthrough
from tests.fixtures.proxy_transport import ProxyTransportFake

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    ("base", "endpoint"),
    [
        ("https://router.test/api/v1", "https://router.test/api/v1/responses"),
        ("https://router.test/api", "https://router.test/api/v1/responses"),
        ("http://host.docker.internal:4000/team/v1/", "http://host.docker.internal:4000/team/v1/responses"),
        ("http://v1", "http://v1/v1/responses"),
    ],
)
@pytest.mark.asyncio
async def test_relay_joins_create_and_subresource_paths_once(base, endpoint, monkeypatch):
    upstream = ProxyTransportFake()
    monkeypatch.setattr(responses_passthrough.httpx, "AsyncClient", upstream.client)
    for method, suffix, query, body in [
        ("POST", "", "", {"model": "fixture", "input": "hi"}),
        ("GET", "/resp_1/input_items", "after=a%2Fb&limit=2", None),
    ]:
        await responses_passthrough.forward(
            method=method,
            url_path="/v1/responses" + suffix,
            body=body,
            query_string=query,
            inbound_headers={"authorization": "Bearer child-token"},
            base_url=base,
            api_key="fixture-key",
            request_id="req_fixture",
        )
        request = upstream.captured
        assert request.url == endpoint + suffix + ("?" + query if query else "")
        assert request.method == method
        assert request.json == body
        assert request.headers["authorization"] == "Bearer fixture-key"
    assert len(upstream.requests) == 2
