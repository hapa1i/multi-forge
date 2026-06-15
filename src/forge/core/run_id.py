"""Forge run-tree id format — single source of truth for minting and validating.

A run id is ``run_`` + 12 lowercase hex chars. This is a dependency-free leaf module
so both the env builder (`forge.core.reactive.env`, which mints ids and stamps the
``X-Forge-Run-ID`` header onto proxy-routed subprocess requests) and the proxy
(`forge.proxy.server`, which validates the inbound header before logging it) share
one format without dragging the heavier ``core.reactive`` package (which eagerly
imports the tagger and session runner).
"""

from __future__ import annotations

import hashlib
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

# Provider session/command correlation headers (openrouter_observability Phase 1).
# Forge stamps these alongside the run-id headers onto a proven-proxy-routed headless
# child's outbound requests. ``X-Forge-Session`` carries an OPAQUE grouping id derived
# from a hash of the (never-sent-raw) human session name + role; ``X-Forge-Command``
# carries the sanitized command role. Both are internal Forge<->proxy correlation
# headers — consumed by the proxy for trace joins, never forwarded upstream (the
# passthrough allowlist drops them). Distinct from Phase 5, which injects the
# OpenAI-standard ``user`` field upstream.
FORGE_SESSION_HEADER = "X-Forge-Session"
FORGE_COMMAND_HEADER = "X-Forge-Command"

# A sanitized role/command label: lowercase alphanumerics + underscore, length-capped.
# One charset shared by the id-suffix derivation, the X-Forge-Command header, and the
# proxy validators, so a role can never normalize two different ways.
_LABEL_MAX_LEN = 64
_LABEL_SEP_RE = re.compile(r"[^a-z0-9]+")
LABEL_RE = re.compile(rf"^[a-z0-9_]{{1,{_LABEL_MAX_LEN}}}$")

# An opaque provider grouping id: ``forge_sess_<12hex>`` (hashed session label) or
# ``forge_run_<12hex>`` (root-run-id fallback), with an optional ``_<role>`` suffix.
# Validated at the proxy like a run id — a spoofed/over-long/injection value is rejected.
PROVIDER_SESSION_ID_RE = re.compile(rf"^forge_(?:sess|run)_[0-9a-f]{{12}}(?:_[a-z0-9_]{{1,{_LABEL_MAX_LEN}}})?$")


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


def sanitize_label(value: str | None) -> str | None:
    """Normalize a role/command label to ``[a-z0-9_]`` (<=64 chars), or None if empty.

    Lowercases, collapses every run of non-alphanumerics to a single underscore, and
    trims edge underscores, so ``memory_writer`` / ``memory-writer`` / ``memory writer``
    all canonicalize to ``memory_writer``. Header-injection bytes (newlines, colons)
    become separators and are stripped — the result is always one safe header-value token.
    """
    if not value:
        return None
    collapsed = _LABEL_SEP_RE.sub("_", value.lower()).strip("_")
    if not collapsed:
        return None
    return collapsed[:_LABEL_MAX_LEN].strip("_") or None


def is_valid_label(value: str | None) -> bool:
    """True if ``value`` is already a clean role/command label (:data:`LABEL_RE`).

    Validates the untrusted inbound ``X-Forge-Command`` header at the proxy: a
    legitimately stamped (already-sanitized) role passes; a spoofed value with
    whitespace, injection bytes, or over-length is rejected (stored as ``None``).
    """
    if not value:
        return False
    return LABEL_RE.match(value) is not None


def is_valid_provider_session_id(value: str | None) -> bool:
    """True if ``value`` is a well-formed provider grouping id (:data:`PROVIDER_SESSION_ID_RE`).

    Validates the untrusted inbound ``X-Forge-Session`` header at the proxy, mirroring
    :func:`is_valid_run_id`: a spoofed/over-long/injection value is dropped, never joined
    into a trace record.
    """
    if not value:
        return False
    return PROVIDER_SESSION_ID_RE.match(value) is not None


def derive_provider_session_id(label: str | None, root_run_id: str, role: str | None = None) -> str:
    """Derive an opaque provider grouping id from a session label (or run-id fallback).

    With a session ``label`` (e.g. the manifest session name) the id is
    ``forge_sess_<hash>`` over the label — the human name is hashed, never sent raw. With
    no label (review fan-out, any headless child lacking ``FORGE_SESSION``) it falls back
    to ``forge_run_<hash>`` over ``root_run_id``, the only id all direct callers share. An
    optional sanitized ``role`` is appended as ``_<role>`` for per-role grouping.
    """
    clean_role = sanitize_label(role)
    if label and label.strip():
        base = f"forge_sess_{_short_hash(label.strip())}"
    else:
        base = f"forge_run_{_short_hash(root_run_id)}"
    return f"{base}_{clean_role}" if clean_role else base


def _short_hash(value: str) -> str:
    """A 12-hex-char SHA-256 prefix — opaque, stable, and non-reversible."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
