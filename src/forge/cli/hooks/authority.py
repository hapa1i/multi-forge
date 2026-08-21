"""Raw artifact-authority guard shared by Claude and Codex hook commands."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge.core.run_id import is_valid_run_id
from forge.session.authority import (
    AUTHORITY_MARKER_ENV,
    AuthorityMarker,
    append_authority_event,
    authority_hook_contract_sha256,
    classify_authority_tool,
    new_authority_event,
    parse_authority_marker,
    sanitize_covered_tool_name,
)
from forge.session.hooks import resolve_session_store
from forge.session.models import SessionState
from forge.session.store import SessionStore


@dataclass(frozen=True)
class AuthorityGuardResult:
    """Authority guard decision and the safe facts needed for denial logging."""

    marker_present: bool
    deny: bool
    reason_code: str | None = None
    covered_tool: str | None = None
    state: SessionState | None = None
    store: SessionStore | None = None
    marker: AuthorityMarker | None = None


def evaluate_authority_guard(data: dict[str, Any] | None, *, runtime: str) -> AuthorityGuardResult:
    """Evaluate a launch marker and raw tool name before payload/policy parsing."""
    raw_marker = os.environ.get(AUTHORITY_MARKER_ENV)
    if raw_marker is None:
        return AuthorityGuardResult(marker_present=False, deny=False)
    if data is None:
        return AuthorityGuardResult(marker_present=True, deny=True, reason_code="authority_guard_invalid_input")

    state: SessionState | None = None
    store: SessionStore | None = None
    covered_tool = sanitize_covered_tool_name(data.get("tool_name") if isinstance(data.get("tool_name"), str) else None)
    try:
        payload_cwd = data.get("cwd")
        cwd = Path(payload_cwd).resolve() if isinstance(payload_cwd, str) and payload_cwd else Path.cwd().resolve()
        store = resolve_session_store(cwd, session_id=data.get("session_id") if runtime == "claude_code" else None)
        if store is None:
            raise ValueError("managed session could not be resolved")
        state = store.read()
        marker = parse_authority_marker(raw_marker, state)
        authority = state.intent.authority
        if authority is None:
            raise ValueError("resolved session is not authority-marked")
        if marker.runtime != runtime:
            raise ValueError("runtime mismatch")
        if data.get("hook_event_name") != "PreToolUse":
            raise ValueError("unexpected hook event")
        decision = classify_authority_tool(authority, runtime, data.get("tool_name"))
        return AuthorityGuardResult(
            marker_present=True,
            deny=decision.deny,
            reason_code=decision.reason_code,
            covered_tool=decision.covered_tool,
            state=state,
            store=store,
            marker=marker,
        )
    except Exception:
        return AuthorityGuardResult(
            marker_present=True,
            deny=True,
            reason_code="authority_guard_error",
            covered_tool=covered_tool or "unknown",
            state=state,
            store=store,
            marker=None,
        )


def journal_authority_denial(result: AuthorityGuardResult, *, runtime: str) -> bool:
    """Best-effort denial journal; return False without weakening the deny."""
    if not result.deny or result.state is None or result.store is None:
        return True
    try:
        run_id = result.marker.run_id if result.marker is not None else _recover_valid_marker_run_id()
        hook_digest = (
            result.marker.hook_registration_sha256
            if result.marker is not None
            else authority_hook_contract_sha256(runtime)
        )
        event = new_authority_event(
            result.state,
            event_type="request_denied",
            run_id=run_id,
            origin_surface=("claude_authority_hook" if runtime == "claude_code" else "codex_policy_hook"),
            operation="tool_request",
            outcome="denied",
            reason_code=result.reason_code or "authority_guard_error",
            hook_registration_sha256=hook_digest,
            covered_tool=result.covered_tool or "unknown",
        )
        append_authority_event(str(result.store.forge_root), event)
    except Exception:
        return False
    return True


def _recover_valid_marker_run_id() -> str | None:
    raw_marker = os.environ.get(AUTHORITY_MARKER_ENV)
    if raw_marker is None:
        return None
    try:
        raw = json.loads(raw_marker)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    run_id = raw.get("run_id")
    return run_id if isinstance(run_id, str) and is_valid_run_id(run_id) else None
