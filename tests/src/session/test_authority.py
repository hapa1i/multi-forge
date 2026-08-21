"""Unit contracts for authority intent, markers, coverage, and payload hygiene."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from forge.session.authority import (
    AUTHORITY_MARKER_ENV,
    AuthorityMarkerError,
    authority_config_sha256,
    authority_coverage,
    build_authority_marker,
    classify_authority_tool,
    new_authority_event,
    parse_authority_marker,
    validate_authority_event,
    validate_authority_payload,
)
from forge.session.events import SessionEventValidationError, validate_session_event
from forge.session.models import (
    AuthorityIntent,
    create_session_state,
    session_state_to_dict,
)
from forge.session.store import SessionStore


def test_authority_role_and_tier_validation() -> None:
    assert AuthorityIntent("advisory").tier == "shell_closed"
    assert AuthorityIntent("advisory", "named_tools").tier == "named_tools"
    assert AuthorityIntent("producer").tier is None

    with pytest.raises(ValueError, match="role"):
        AuthorityIntent("unknown")
    with pytest.raises(ValueError, match="tier"):
        AuthorityIntent("advisory", "unknown")
    with pytest.raises(ValueError, match="producer"):
        AuthorityIntent("producer", "shell_closed")


@pytest.mark.parametrize(
    "authority",
    [None, AuthorityIntent("advisory", "named_tools"), AuthorityIntent("producer")],
)
def test_authority_intent_round_trips_through_strict_session_store(
    tmp_path: Path, authority: AuthorityIntent | None
) -> None:
    state = create_session_state("round-trip", authority=authority)
    store = SessionStore(str(tmp_path), "round-trip")

    store.write(state)
    restored = store.read()

    assert restored.intent.authority == authority
    assert session_state_to_dict(restored)["intent"]["authority"] == (
        asdict(authority) if authority is not None else None
    )


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit", "apply_patch"])
def test_named_tools_denies_raw_mutation_names(tool: str) -> None:
    authority = AuthorityIntent("advisory", "named_tools")

    assert classify_authority_tool(authority, "claude_code", tool).deny is True
    assert classify_authority_tool(authority, "codex", tool).deny is True


def test_named_tools_declines_bash_and_unknown() -> None:
    authority = AuthorityIntent("advisory", "named_tools")
    assert classify_authority_tool(authority, "claude_code", "Bash").deny is False
    assert classify_authority_tool(authority, "claude_code", "NewTool").deny is False


@pytest.mark.parametrize(
    "tool",
    [
        "Read",
        "Glob",
        "Grep",
        "WebFetch",
        "WebSearch",
        "AskUserQuestion",
        "ExitPlanMode",
        "TaskCreate",
    ],
)
def test_claude_shell_closed_declines_only_allowlisted_tools(tool: str) -> None:
    authority = AuthorityIntent("advisory")
    assert classify_authority_tool(authority, "claude_code", tool).deny is False


@pytest.mark.parametrize("tool", ["Write", "Bash", "Task", "Skill", "mcp__server__tool", "FutureTool", None])
def test_claude_shell_closed_denies_every_other_delivered_tool(tool: object) -> None:
    authority = AuthorityIntent("advisory")
    assert classify_authority_tool(authority, "claude_code", tool).deny is True


@pytest.mark.parametrize("tool", ["apply_patch", "Bash", "FutureTool", None])
def test_codex_shell_closed_denies_every_delivered_tool(tool: object) -> None:
    authority = AuthorityIntent("advisory")
    assert classify_authority_tool(authority, "codex", tool).deny is True


def test_producer_never_receives_an_authority_deny() -> None:
    authority = AuthorityIntent("producer")
    assert classify_authority_tool(authority, "claude_code", "Write").deny is False
    assert classify_authority_tool(authority, "codex", "apply_patch").deny is False


def test_marker_is_compact_secret_free_and_bound_to_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = create_session_state("planner", authority=AuthorityIntent("advisory"))
    monkeypatch.setattr(
        "forge.session.authority.authority_hook_contract_sha256",
        lambda runtime: "b" * 64,
    )

    marker_raw = build_authority_marker(state, "run_0123456789ab", "b" * 64)
    marker = parse_authority_marker(marker_raw, state)
    authority = state.intent.authority
    assert authority is not None

    assert " " not in marker_raw
    assert marker.session == "planner"
    assert marker.effective_config_sha256 == authority_config_sha256(authority, "claude_code")
    assert set(json.loads(marker_raw)) == {
        "schema_version",
        "session",
        "runtime",
        "run_id",
        "effective_config_sha256",
        "hook_registration_sha256",
    }
    assert AUTHORITY_MARKER_ENV not in marker_raw


def test_marker_mismatch_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    state = create_session_state("planner", authority=AuthorityIntent("advisory"))
    monkeypatch.setattr(
        "forge.session.authority.authority_hook_contract_sha256",
        lambda runtime: "b" * 64,
    )
    marker_raw = build_authority_marker(state, "run_0123456789ab", "b" * 64)
    state.intent.authority = AuthorityIntent("advisory", "named_tools")

    with pytest.raises(AuthorityMarkerError, match="configuration digest"):
        parse_authority_marker(marker_raw, state)


def test_marker_rejects_boolean_schema_version(monkeypatch: pytest.MonkeyPatch) -> None:
    state = create_session_state("planner", authority=AuthorityIntent("advisory"))
    monkeypatch.setattr(
        "forge.session.authority.authority_hook_contract_sha256",
        lambda runtime: "b" * 64,
    )
    marker = json.loads(build_authority_marker(state, "run_0123456789ab", "b" * 64))
    marker["schema_version"] = True

    with pytest.raises(AuthorityMarkerError, match="schema version"):
        parse_authority_marker(json.dumps(marker), state)


def test_authority_event_payload_is_exact_and_source_free() -> None:
    state = create_session_state("planner", authority=AuthorityIntent("advisory"))
    event = new_authority_event(
        state,
        event_type="request_denied",
        run_id="run_0123456789ab",
        origin_surface="claude_authority_hook",
        operation="tool_request",
        outcome="denied",
        reason_code="advisory_shell_closed_denied",
        hook_registration_sha256="b" * 64,
        covered_tool="Write",
    )

    assert set(event.payload) == {
        "role",
        "tier",
        "effective_config_sha256",
        "hook_registration_sha256",
        "covered_tool",
    }
    serialized = json.dumps(asdict(event))
    assert "tool_input" not in serialized
    assert "file_path" not in serialized


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", "run_0123456789ab"),
        ("origin_surface", "codex_policy_hook"),
        ("operation", "tool_request"),
        ("outcome", "error"),
    ],
)
def test_authority_event_rejects_semantically_invalid_configuration_envelope(field: str, value: object) -> None:
    state = create_session_state("planner", authority=AuthorityIntent("advisory"))
    valid = new_authority_event(
        state,
        event_type="authority_configured",
        run_id=None,
        origin_surface="external_cli",
        operation="set",
        outcome="success",
    )
    raw = asdict(valid)
    raw[field] = value
    if field == "outcome":
        raw["reason_code"] = "invalid_configuration"

    with pytest.raises(SessionEventValidationError):
        validate_session_event(
            raw,
            payload_validator=validate_authority_payload,
            event_validator=validate_authority_event,
        )


def test_authority_event_rejects_denial_with_wrong_runtime_origin() -> None:
    state = create_session_state("planner", runtime="codex", authority=AuthorityIntent("advisory"))

    with pytest.raises(SessionEventValidationError, match="origin_surface"):
        new_authority_event(
            state,
            event_type="request_denied",
            run_id="run_0123456789ab",
            origin_surface="claude_authority_hook",
            operation="tool_request",
            outcome="denied",
            reason_code="advisory_shell_closed_denied",
            hook_registration_sha256="b" * 64,
            covered_tool="apply_patch",
        )


def test_authority_event_wraps_invalid_digest_as_typed_record_error() -> None:
    state = create_session_state("planner", authority=AuthorityIntent("advisory"))
    valid = new_authority_event(
        state,
        event_type="authority_configured",
        run_id=None,
        origin_surface="external_cli",
        operation="set",
        outcome="success",
    )
    raw = asdict(valid)
    raw["payload"]["effective_config_sha256"] = "not-a-digest"

    with pytest.raises(SessionEventValidationError, match="record 7 field 'payload'.*SHA-256"):
        validate_session_event(
            raw,
            payload_validator=validate_authority_payload,
            event_validator=validate_authority_event,
            record_number=7,
        )


def test_report_coverage_is_explicit() -> None:
    named = authority_coverage(AuthorityIntent("advisory", "named_tools"), "claude_code")
    closed = authority_coverage(AuthorityIntent("advisory"), "claude_code")
    codex = authority_coverage(AuthorityIntent("advisory"), "codex")

    assert named[0] == ["Write", "Edit", "NotebookEdit", "apply_patch"]
    assert closed[0] == [
        "Write",
        "Edit",
        "NotebookEdit",
        "apply_patch",
        "Bash",
        "unknown_tools",
    ]
    assert "Read" in closed[1]
    assert "AskUserQuestion" in closed[2]
    assert codex == (["all_delivered_tools"], [], [])
