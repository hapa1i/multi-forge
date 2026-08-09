"""Shared safe response-header relay for raw proxy transports."""

from __future__ import annotations

from collections.abc import Mapping

# Headers that must never cross from an upstream response to the downstream
# client. Besides standard hop-by-hop framing, this excludes authentication and
# cookie material plus Forge-owned correlation identity. Header names nominated
# by ``Connection`` are added dynamically in ``relay_response_headers``.
_RESPONSE_HEADER_DENYLIST = frozenset(
    {
        "authentication-info",
        "authorization",
        "connection",
        "content-encoding",
        "content-length",
        "cookie",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authentication-info",
        "proxy-authorization",
        "proxy-connection",
        "set-cookie",
        "set-cookie2",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "www-authenticate",
        "x-api-key",
        "x-cumulative-cost",
        "x-request-id",
        "x-request-cost",
        "x-resolved-model",
        "x-resolved-tier",
        "x-spend-warning",
    }
)

_PROXY_OWNED_HEADER_PREFIXES = ("x-forge-",)


def relay_response_headers(upstream: Mapping[str, str], request_id: str) -> dict[str, str]:
    """Relay safe upstream metadata and stamp Forge's correlation id.

    Matching is case-insensitive. In addition to the fixed denylist, RFC-style
    extension headers named by an upstream ``Connection`` value are treated as
    hop-by-hop and removed.
    """
    connection_tokens: set[str] = set()
    for name, value in upstream.items():
        if name.lower() == "connection":
            connection_tokens.update(token.strip().lower() for token in value.split(",") if token.strip())

    denied = _RESPONSE_HEADER_DENYLIST | connection_tokens
    relayed: dict[str, str] = {"X-Request-ID": request_id}
    for name, value in upstream.items():
        lowered = name.lower()
        if lowered not in denied and not lowered.startswith(_PROXY_OWNED_HEADER_PREFIXES):
            relayed[name] = value
    return relayed


def merge_response_headers(
    headers: Mapping[str, str],
    overlay: Mapping[str, str] | None,
) -> dict[str, str]:
    """Overlay Forge-owned headers with case-insensitive replacement semantics."""
    if not overlay:
        return dict(headers)

    replaced = {name.lower() for name in overlay}
    merged = {name: value for name, value in headers.items() if name.lower() not in replaced}
    merged.update(overlay)
    return merged
