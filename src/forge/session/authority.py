"""Artifact-authority contracts shared by control, launch, and hook surfaces."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

from forge.core.run_id import is_valid_run_id
from forge.core.state import file_lock

from .events import (
    SessionEvent,
    SessionEventValidationError,
    append_session_event,
    new_session_event,
    read_session_events,
)
from .models import (
    AUTHORITY_ROLES,
    AUTHORITY_TIERS,
    AuthorityIntent,
    SessionState,
    session_runtime,
)
from .validation import validate_name

AUTHORITY_JOURNAL_DOMAIN = "authority"
AUTHORITY_MARKER_ENV = "FORGE_AUTHORITY_MARKER"
AUTHORITY_MARKER_SCHEMA_VERSION = 1
AUTHORITY_COVERAGE_VERSION = 1
AUTHORITY_HOOK_TIMEOUT_SECONDS = 60
AUTHORITY_CONTROL_LOCK_TIMEOUT_S = 5.0

AUTHORITY_EVENT_TYPES = frozenset(
    {
        "authority_configured",
        "authority_cleared",
        "authority_inherited",
        "launch_preflight",
        "launch_aborted",
        "run_started",
        "run_ended",
        "request_denied",
        "mutation_refused",
    }
)

NAMED_MUTATION_TOOLS = frozenset({"Write", "Edit", "NotebookEdit", "apply_patch"})
CLAUDE_READ_ONLY_TOOLS = (
    "Read",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
)
CLAUDE_CONTROL_TOOLS = (
    "AskUserQuestion",
    "EnterPlanMode",
    "ExitPlanMode",
    "ReportFindings",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "TodoWrite",
)
_CLAUDE_SHELL_CLOSED_ALLOWLIST = frozenset(CLAUDE_READ_ONLY_TOOLS + CLAUDE_CONTROL_TOOLS)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_TOOL_RE = re.compile(r"^[A-Za-z0-9_.:*\-/]{1,128}$")
_AUTHORITY_PAYLOAD_FIELDS = frozenset(
    {
        "role",
        "tier",
        "effective_config_sha256",
        "hook_registration_sha256",
        "covered_tool",
    }
)
_MARKER_FIELDS = frozenset(
    {
        "schema_version",
        "session",
        "runtime",
        "run_id",
        "effective_config_sha256",
        "hook_registration_sha256",
    }
)
_USE_STATE_AUTHORITY = object()


class AuthorityError(Exception):
    """Base error for authority evaluation and marker validation."""


class AuthorityMarkerError(AuthorityError):
    """A launch-owned authority marker is malformed or inconsistent."""


@dataclass(frozen=True)
class AuthorityMarker:
    """Secret-free marker for one preflighted managed advisory run."""

    schema_version: int
    session: str
    runtime: str
    run_id: str
    effective_config_sha256: str
    hook_registration_sha256: str


@dataclass(frozen=True)
class AuthorityToolDecision:
    """Authority-only tool classification; decline never grants permission."""

    deny: bool
    covered_tool: str | None = None
    reason_code: str | None = None


@contextmanager
def authority_session_lock(session_dir: Path) -> Iterator[None]:
    """Serialize authority creation/configuration and launch preflight.

    The sibling lock exists before the session directory can be published, so a
    creator can hold it across manifest/index publication and the required first
    journal record without making an empty session directory visible.
    """
    validate_name(session_dir.name)
    with file_lock(
        lock_path=session_dir.parent / f".{session_dir.name}.authority.lock",
        timeout_s=AUTHORITY_CONTROL_LOCK_TIMEOUT_S,
    ):
        yield


def authority_config_sha256(authority: AuthorityIntent, runtime: str) -> str:
    """Hash the effective, source-free authority configuration."""
    data = {
        "coverage_version": AUTHORITY_COVERAGE_VERSION,
        "role": authority.role,
        "runtime": runtime,
        "tier": authority.tier,
    }
    return hashlib.sha256(_canonical_json(data).encode("utf-8")).hexdigest()


def authority_hook_contract_sha256(runtime: str) -> str:
    """Hash the exact code-owned hook registration contract for a runtime."""
    if runtime == "claude_code":
        from forge.install.hook_dispatcher import (
            dispatcher_source_sha256,
            render_dispatcher_command,
        )

        contract: dict[str, Any] = {
            "command": render_dispatcher_command("authority-check"),
            "dispatcher_source_sha256": dispatcher_source_sha256(),
            "event": "PreToolUse",
            "matcher": None,
            "timeout": AUTHORITY_HOOK_TIMEOUT_SECONDS,
        }
    elif runtime == "codex":
        from forge.install.codex_hooks import get_builtin_codex_entries

        entries = [asdict(entry) for entry in get_builtin_codex_entries() if entry.event == "PreToolUse"]
        contract = {"entries": entries}
    else:
        raise AuthorityError(f"unsupported authority runtime: {runtime!r}")
    return hashlib.sha256(_canonical_json(contract).encode("utf-8")).hexdigest()


def build_authority_marker(state: SessionState, run_id: str, hook_registration_sha256: str) -> str:
    """Serialize the immutable advisory marker as compact JSON."""
    authority = state.intent.authority
    if authority is None or authority.role != "advisory":
        raise AuthorityMarkerError("only an advisory session can receive an authority marker")
    if not is_valid_run_id(run_id):
        raise AuthorityMarkerError("marker run id is invalid")
    _require_sha256(hook_registration_sha256, "hook_registration_sha256")
    marker = AuthorityMarker(
        schema_version=AUTHORITY_MARKER_SCHEMA_VERSION,
        session=state.name,
        runtime=session_runtime(state),
        run_id=run_id,
        effective_config_sha256=authority_config_sha256(authority, session_runtime(state)),
        hook_registration_sha256=hook_registration_sha256,
    )
    return _canonical_json(asdict(marker))


def parse_authority_marker(raw_marker: str, state: SessionState) -> AuthorityMarker:
    """Validate marker shape and bind it to the current advisory manifest."""
    try:
        raw = json.loads(raw_marker)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AuthorityMarkerError("authority marker is not valid JSON") from exc
    if not isinstance(raw, dict) or set(raw) != _MARKER_FIELDS:
        raise AuthorityMarkerError("authority marker has an invalid field set")
    schema_version = raw.get("schema_version")
    if type(schema_version) is not int or schema_version != AUTHORITY_MARKER_SCHEMA_VERSION:
        raise AuthorityMarkerError("authority marker schema version is unsupported")
    if not isinstance(raw.get("session"), str) or raw["session"] != state.name:
        raise AuthorityMarkerError("authority marker session does not match the manifest")
    runtime = session_runtime(state)
    if raw.get("runtime") != runtime:
        raise AuthorityMarkerError("authority marker runtime does not match the manifest")
    run_id = raw.get("run_id")
    if not isinstance(run_id, str) or not is_valid_run_id(run_id):
        raise AuthorityMarkerError("authority marker run id is invalid")

    authority = state.intent.authority
    if authority is None or authority.role != "advisory":
        raise AuthorityMarkerError("authority marker does not match a current advisory role")
    expected_config = authority_config_sha256(authority, runtime)
    if raw.get("effective_config_sha256") != expected_config:
        raise AuthorityMarkerError("authority marker configuration digest does not match the manifest")
    expected_hook = authority_hook_contract_sha256(runtime)
    if raw.get("hook_registration_sha256") != expected_hook:
        raise AuthorityMarkerError("authority marker hook digest does not match the installed contract")
    return AuthorityMarker(
        schema_version=AUTHORITY_MARKER_SCHEMA_VERSION,
        session=state.name,
        runtime=runtime,
        run_id=run_id,
        effective_config_sha256=expected_config,
        hook_registration_sha256=expected_hook,
    )


def classify_authority_tool(authority: AuthorityIntent, runtime: str, tool_name: object) -> AuthorityToolDecision:
    """Return deny/decline for the raw delivered tool name before payload parsing."""
    if authority.role != "advisory":
        return AuthorityToolDecision(deny=False)
    normalized = tool_name if isinstance(tool_name, str) and tool_name else "unknown"
    covered_tool = sanitize_covered_tool_name(normalized)
    if authority.tier == "named_tools":
        if normalized in NAMED_MUTATION_TOOLS:
            return AuthorityToolDecision(True, covered_tool, "advisory_named_tool_denied")
        return AuthorityToolDecision(False)
    if authority.tier != "shell_closed":
        raise AuthorityError(f"unsupported advisory authority tier: {authority.tier!r}")
    if runtime == "claude_code" and normalized in _CLAUDE_SHELL_CLOSED_ALLOWLIST:
        return AuthorityToolDecision(False)
    if runtime not in {"claude_code", "codex"}:
        raise AuthorityError(f"unsupported authority runtime: {runtime!r}")
    return AuthorityToolDecision(True, covered_tool, "advisory_shell_closed_denied")


def authority_coverage(authority: AuthorityIntent | None, runtime: str) -> tuple[list[str], list[str], list[str]]:
    """Return covered, inspection, and control inventories for report output."""
    if authority is None or authority.role != "advisory":
        return [], [], []
    if authority.tier == "named_tools":
        return ["Write", "Edit", "NotebookEdit", "apply_patch"], [], []
    if runtime == "claude_code":
        return (
            [
                "Write",
                "Edit",
                "NotebookEdit",
                "apply_patch",
                "Bash",
                "unknown_tools",
            ],
            list(CLAUDE_READ_ONLY_TOOLS),
            list(CLAUDE_CONTROL_TOOLS),
        )
    if runtime == "codex":
        return ["all_delivered_tools"], [], []
    raise AuthorityError(f"unsupported authority runtime: {runtime!r}")


def authority_payload(
    authority: AuthorityIntent | None,
    runtime: str,
    *,
    config_sha256: str | None = None,
    hook_registration_sha256: str | None = None,
    covered_tool: str | None = None,
) -> dict[str, Any]:
    """Build the exact, source-free payload shared by every authority event."""
    effective_digest = config_sha256
    if effective_digest is None and authority is not None:
        effective_digest = authority_config_sha256(authority, runtime)
    return {
        "role": authority.role if authority is not None else None,
        "tier": authority.tier if authority is not None else None,
        "effective_config_sha256": effective_digest,
        "hook_registration_sha256": hook_registration_sha256,
        "covered_tool": (sanitize_covered_tool_name(covered_tool) if covered_tool is not None else None),
    }


def new_authority_event(
    state: SessionState,
    *,
    event_type: str,
    run_id: str | None,
    origin_surface: str,
    operation: str | None,
    outcome: str,
    reason_code: str | None = None,
    authority: AuthorityIntent | None | object = _USE_STATE_AUTHORITY,
    config_sha256: str | None = None,
    hook_registration_sha256: str | None = None,
    covered_tool: str | None = None,
) -> SessionEvent:
    """Construct one validated authority-domain event."""
    selected_authority = state.intent.authority if authority is _USE_STATE_AUTHORITY else authority
    if selected_authority is not None and not isinstance(selected_authority, AuthorityIntent):
        raise TypeError("authority event authority must be AuthorityIntent or None")
    return new_session_event(
        session=state.name,
        runtime=session_runtime(state),
        event_type=event_type,
        run_id=run_id,
        origin_surface=origin_surface,
        operation=operation,
        outcome=outcome,
        reason_code=reason_code,
        payload=authority_payload(
            selected_authority,
            session_runtime(state),
            config_sha256=config_sha256,
            hook_registration_sha256=hook_registration_sha256,
            covered_tool=covered_tool,
        ),
        payload_validator=validate_authority_payload,
    )


def append_authority_event(forge_root: str, event: SessionEvent) -> None:
    """Durably append one authority event."""
    append_session_event(
        forge_root,
        AUTHORITY_JOURNAL_DOMAIN,
        event,
        payload_validator=validate_authority_payload,
    )


def read_authority_events(forge_root: str, session: str) -> list[SessionEvent]:
    """Strictly read one session's authority journal."""
    return read_session_events(
        forge_root,
        session,
        AUTHORITY_JOURNAL_DOMAIN,
        payload_validator=validate_authority_payload,
    )


def validate_authority_payload(event_type: str, payload: dict[str, Any]) -> None:
    """Validate the authority-owned event type and exact payload shape."""
    if event_type not in AUTHORITY_EVENT_TYPES:
        raise SessionEventValidationError(f"unknown authority event type {event_type!r}", field="event_type")
    if set(payload) != _AUTHORITY_PAYLOAD_FIELDS:
        unknown = set(payload) - _AUTHORITY_PAYLOAD_FIELDS
        missing = _AUTHORITY_PAYLOAD_FIELDS - set(payload)
        detail = []
        if unknown:
            detail.append(f"unknown: {', '.join(sorted(unknown))}")
        if missing:
            detail.append(f"missing: {', '.join(sorted(missing))}")
        raise ValueError("invalid authority payload fields (" + "; ".join(detail) + ")")

    role = payload["role"]
    tier = payload["tier"]
    if role is not None and role not in AUTHORITY_ROLES:
        raise ValueError("role must be null, advisory, or producer")
    if tier is not None and tier not in AUTHORITY_TIERS:
        raise ValueError("tier must be null, named_tools, or shell_closed")
    if role == "advisory" and tier is None:
        raise ValueError("advisory authority payload requires a tier")
    if role == "producer" and tier is not None:
        raise ValueError("producer authority payload cannot carry a tier")
    if role is None and tier is not None:
        raise ValueError("an authority payload without a role cannot carry a tier")

    for field_name in ("effective_config_sha256", "hook_registration_sha256"):
        value = payload[field_name]
        if value is not None:
            _require_sha256(value, field_name)
    covered_tool = payload["covered_tool"]
    if covered_tool is not None and (
        not isinstance(covered_tool, str) or _SAFE_TOOL_RE.fullmatch(covered_tool) is None
    ):
        raise ValueError("covered_tool must be null or a safe tool identifier")

    if event_type in {"authority_configured", "authority_inherited"}:
        _require_authority_payload(payload, require_hook=False, require_tool=False)
    elif event_type == "authority_cleared":
        if any(payload.values()):
            raise ValueError("authority_cleared payload must contain only null values")
    elif event_type in {"run_started", "run_ended"}:
        _require_authority_payload(
            payload,
            require_hook=role == "advisory",
            require_tool=False,
        )
    elif event_type in {"launch_preflight", "launch_aborted"}:
        _require_authority_payload(payload, require_hook=False, require_tool=False)
    elif event_type == "request_denied":
        if role != "advisory":
            raise ValueError("request_denied payload requires advisory authority")
        _require_authority_payload(payload, require_hook=True, require_tool=True)
    elif event_type == "mutation_refused" and covered_tool is not None:
        raise ValueError("mutation_refused payload cannot carry a covered tool")


def _require_authority_payload(
    payload: dict[str, Any],
    *,
    require_hook: bool,
    require_tool: bool,
) -> None:
    if payload["role"] is None or payload["effective_config_sha256"] is None:
        raise ValueError("event payload requires role and effective_config_sha256")
    if require_hook and payload["hook_registration_sha256"] is None:
        raise ValueError("event payload requires hook_registration_sha256")
    if not require_tool and payload["covered_tool"] is not None:
        raise ValueError("event payload cannot carry a covered tool")
    if require_tool and payload["covered_tool"] is None:
        raise ValueError("event payload requires covered_tool")


def sanitize_covered_tool_name(tool_name: str | None) -> str | None:
    """Keep a tool identifier only when it is safe to persist verbatim."""
    if tool_name is None:
        return None
    return tool_name if _SAFE_TOOL_RE.fullmatch(tool_name) is not None else "unknown"


def _require_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise AuthorityError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False)
