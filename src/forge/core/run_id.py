"""Forge run-tree id format — single source of truth for minting and validating.

A run id is ``run_`` + 12 lowercase hex chars. This is a dependency-free leaf module
so both the env builder (`forge.core.reactive.env`, which mints ids and stamps the
``X-Forge-Run-ID`` header onto proxy-routed subprocess requests) and the proxy
(`forge.proxy.server`, which validates the inbound header before logging it) share
one format without dragging the heavier ``core.reactive`` package (which eagerly
imports the tagger and session runner).
"""

from __future__ import annotations

import re
import uuid

# ``run_`` + 12 lowercase hex chars. Minting and validation share this constant so
# the proxy's X-Forge-Run-ID guard (Slice 4g) can never drift from ``mint_run_id``.
RUN_ID_RE = re.compile(r"^run_[0-9a-f]{12}$")

# Run-tree correlation headers (Slice 4g). Forge stamps these onto a proxy-routed
# headless subprocess's outbound requests via ANTHROPIC_CUSTOM_HEADERS; the Forge
# proxy reads + validates them and records them on each cost record, so proxied
# ``claude -p`` cost joins exactly to the run tree. Opaque, non-secret run ids —
# consumed by the proxy, never forwarded upstream.
ANTHROPIC_CUSTOM_HEADERS_VAR = "ANTHROPIC_CUSTOM_HEADERS"
FORGE_RUN_ID_HEADER = "X-Forge-Run-ID"
FORGE_ROOT_RUN_ID_HEADER = "X-Forge-Root-Run-ID"


def mint_run_id() -> str:
    """Mint a fresh run id (``run_`` + 12 hex; mirrors the proxy's ``req_`` style)."""
    return f"run_{uuid.uuid4().hex[:12]}"


def is_valid_run_id(value: str | None) -> bool:
    """True if ``value`` is a well-formed Forge run id (:data:`RUN_ID_RE`).

    Used to validate untrusted inbound ``X-Forge-Run-ID``/``X-Forge-Root-Run-ID``
    headers at the proxy before persisting them to the cost log — a malformed or
    spoofed value is dropped (stored as ``None``), never trusted into telemetry.
    """
    if not value:
        return False
    return RUN_ID_RE.match(value) is not None
