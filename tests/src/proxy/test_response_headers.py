"""Tests for the shared passthrough response-header boundary."""

from forge.proxy.response_headers import merge_response_headers, relay_response_headers


def test_relay_response_headers_strips_fixed_and_connection_nominated_fields() -> None:
    upstream = {
        "Content-Type": "application/json",
        "Retry-After": "7",
        "Anthropic-RateLimit-Requests-Remaining": "0",
        "CONNECTION": "X-Hop-Token, keep-alive",
        "X-Hop-Token": "remove-me",
        "Transfer-Encoding": "chunked",
        "Content-Length": "9999",
        "Content-Encoding": "gzip",
        "Authentication-Info": "nextnonce=secret",
        "Authorization": "Bearer secret",
        "X-API-Key": "secret",
        "Cookie": "session=secret",
        "Set-Cookie": "session=secret",
        "Set-Cookie2": "legacy=secret",
        "WWW-Authenticate": "Bearer realm=secret",
        "X-Request-ID": "upstream-id",
        "X-Spend-Warning": "upstream-warning",
        "X-Resolved-Model": "upstream-model",
        "X-Cumulative-Cost": "999.99",
        "X-Forge-Session": "upstream-session",
    }

    assert relay_response_headers(upstream, "forge-id") == {
        "X-Request-ID": "forge-id",
        "Content-Type": "application/json",
        "Retry-After": "7",
        "Anthropic-RateLimit-Requests-Remaining": "0",
    }


def test_merge_response_headers_replaces_collisions_case_insensitively() -> None:
    merged = merge_response_headers(
        {
            "retry-after": "7",
            "x-spend-warning": "upstream-value",
            "cache-control": "public, max-age=60",
        },
        {
            "X-Spend-Warning": "forge-value",
            "Cache-Control": "no-cache",
        },
    )

    assert merged == {
        "retry-after": "7",
        "X-Spend-Warning": "forge-value",
        "Cache-Control": "no-cache",
    }


def test_merge_response_headers_does_not_mutate_input() -> None:
    original = {"Retry-After": "7"}

    assert merge_response_headers(original, {"X-Spend-Warning": "warn"}) == {
        "Retry-After": "7",
        "X-Spend-Warning": "warn",
    }
    assert original == {"Retry-After": "7"}
