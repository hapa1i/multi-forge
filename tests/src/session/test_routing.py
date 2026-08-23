from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from forge.session.events import SessionEventValidationError, append_session_event
from forge.session.models import (
    LaunchIntent,
    RouteCommitConfirmed,
    SessionIntent,
    SessionState,
)
from forge.session.routing import (
    ROUTING_ABORT_EVENT,
    ROUTING_COMMIT_EVENT,
    append_routing_event,
    custom_route_fingerprint,
    derive_routing_history,
    new_routing_event,
    read_routing_events,
)


def _state(*, runtime: str = "claude_code") -> SessionState:
    return SessionState(
        schema_version=1,
        name="planner",
        created_at="2026-08-22T00:00:00Z",
        last_accessed_at="2026-08-22T00:00:00Z",
        intent=SessionIntent(launch=LaunchIntent(runtime=runtime)),
    )


def _payload(*, kind: str = "direct") -> dict[str, Any]:
    direct_model = "claude-opus-5" if kind == "direct" else None
    base: dict[str, Any] = {
        "route": {
            "kind": kind,
            "backend_id": None,
            "proxy_id": None,
            "template": None,
            "custom_route_fingerprint": None,
        },
        "requested_model": None,
        "selected_tier": None,
        "selected_model": None,
        "default_tier": None,
        "direct_model": direct_model,
        "tier_mappings": {},
        "model_alternatives": {},
        "billing_mode": "unknown",
        "route_scope_tags": ["route:direct", "runtime:claude_code"],
        "marking_snapshots": (
            [
                {
                    "slot": "direct",
                    "tier": None,
                    "request_model": None,
                    "route_model": direct_model,
                    "canonical_model": direct_model,
                    "declaration": {
                        "status": "unknown",
                        "basis": None,
                        "source_url": None,
                        "checked_at": None,
                        "effective_from": None,
                        "route_scope": [],
                    },
                }
            ]
            if direct_model is not None
            else []
        ),
    }
    return base


def _proxy_payload() -> dict[str, Any]:
    payload = _payload(kind="proxy")
    payload["route"] = {
        "kind": "proxy",
        "backend_id": "openrouter",
        "proxy_id": "or-1",
        "template": "openrouter-anthropic",
        "custom_route_fingerprint": None,
    }
    payload["default_tier"] = "sonnet"
    payload["tier_mappings"] = {"sonnet": "anthropic/claude-sonnet-5"}
    payload["route_scope_tags"] = [
        "backend:openrouter",
        "route:proxy",
        "runtime:claude_code",
    ]
    payload["marking_snapshots"] = [
        {
            "slot": "tier_default",
            "tier": "sonnet",
            "request_model": None,
            "route_model": "anthropic/claude-sonnet-5",
            "canonical_model": "claude-sonnet-5",
            "declaration": {
                "status": "unknown",
                "basis": None,
                "source_url": None,
                "checked_at": None,
                "effective_from": None,
                "route_scope": [],
            },
        }
    ]
    return payload


def _commit(state: SessionState, run: str, payload: dict[str, Any] | None = None):
    return new_routing_event(
        state,
        event_type=ROUTING_COMMIT_EVENT,
        run_id=run,
        operation="resume",
        payload=payload or _payload(),
    )


def _abort(state: SessionState, run: str, payload: dict[str, Any] | None = None):
    return new_routing_event(
        state,
        event_type=ROUTING_ABORT_EVENT,
        run_id=run,
        operation="resume",
        payload=payload or _payload(),
    )


def _append_attempt(root: Path, state: SessionState, run: str, *, aborted: bool = False):
    commit = _commit(state, run)
    append_routing_event(root, commit)
    if aborted:
        append_routing_event(root, _abort(state, run))
    return commit


def test_route_payload_kinds_validate_exactly(tmp_path: Path) -> None:
    direct = _commit(_state(), "run_000000000001")
    assert direct.payload["route"]["kind"] == "direct"

    proxy = _proxy_payload()
    append_routing_event(tmp_path, _commit(_state(), "run_000000000002", proxy))

    native = _payload(kind="runtime_native")
    native["direct_model"] = None
    native["route_scope_tags"] = ["route:runtime_native", "runtime:codex"]
    append_routing_event(tmp_path, _commit(_state(runtime="codex"), "run_000000000003", native))


def test_requested_model_can_remain_when_proxy_or_custom_route_ignores_it(tmp_path: Path) -> None:
    proxy = _proxy_payload()
    proxy["requested_model"] = "claude-opus-5"
    append_routing_event(tmp_path, _commit(_state(), "run_000000000001", proxy))

    custom = _payload(kind="custom")
    custom["direct_model"] = None
    custom["route"]["custom_route_fingerprint"] = custom_route_fingerprint("https://example.com")
    custom["requested_model"] = "claude-opus-5"
    custom["route_scope_tags"] = ["route:custom", "runtime:claude_code"]
    append_routing_event(tmp_path, _commit(_state(), "run_000000000002", custom))


def test_ignored_proxy_request_cannot_claim_an_effective_model(tmp_path: Path) -> None:
    payload = _proxy_payload()
    payload["requested_model"] = "claude-opus-5"
    payload["selected_model"] = "anthropic/claude-sonnet-5"

    with pytest.raises(SessionEventValidationError, match="ignored proxy request"):
        append_routing_event(tmp_path, _commit(_state(), "run_000000000001", payload))


def test_exact_abort_payload_is_enforced(tmp_path: Path) -> None:
    state = _state()
    commit = _commit(state, "run_000000000001")
    append_routing_event(tmp_path, commit)
    different = _payload()
    different["direct_model"] = "claude-sonnet-5"
    different["marking_snapshots"][0]["route_model"] = "claude-sonnet-5"
    different["marking_snapshots"][0]["canonical_model"] = "claude-sonnet-5"
    append_routing_event(tmp_path, _abort(state, "run_000000000001", different))

    with pytest.raises(SessionEventValidationError, match="payload does not match"):
        read_routing_events(tmp_path, state)


@pytest.mark.parametrize(
    ("url", "same_as"),
    [
        ("HTTPS://Example.COM:443/path?secret=x#frag", "https://example.com"),
        ("https://user:pass@example.com/private", "https://example.com"),
        ("http://[2001:db8::1]:80/a", "http://[2001:db8::1]"),
    ],
)
def test_custom_fingerprint_uses_only_canonical_origin(url: str, same_as: str) -> None:
    assert custom_route_fingerprint(url) == custom_route_fingerprint(same_as)


@pytest.mark.parametrize("url", ["ftp://example.com", "https:///missing", "https://example.com:notaport"])
def test_custom_fingerprint_rejects_unusable_origins(url: str) -> None:
    with pytest.raises(ValueError):
        custom_route_fingerprint(url)


def test_absent_empty_and_aborted_only_history_states(tmp_path: Path) -> None:
    state = _state()
    assert derive_routing_history(tmp_path, state).status is None

    journal = tmp_path / ".forge" / "artifacts" / "planner" / "routing" / "events.jsonl"
    journal.parent.mkdir(parents=True)
    journal.touch()
    assert derive_routing_history(tmp_path, state).status == "unproven"

    journal.unlink()
    _append_attempt(tmp_path, state, "run_000000000001", aborted=True)
    assert derive_routing_history(tmp_path, state).status == "supported"
    assert derive_routing_history(tmp_path, state).effective_commit is None


def test_projection_state_table(tmp_path: Path) -> None:
    state = _state()
    first = _append_attempt(tmp_path, state, "run_000000000001")
    assert derive_routing_history(tmp_path, state).status == "unproven"

    state.confirmed.route_commit = RouteCommitConfirmed(first.event_id, first.run_id or "")
    assert derive_routing_history(tmp_path, state).status == "supported"

    _append_attempt(tmp_path, state, "run_000000000002", aborted=True)
    assert derive_routing_history(tmp_path, state).status == "supported"

    latest = _append_attempt(tmp_path, state, "run_000000000003")
    assert derive_routing_history(tmp_path, state).status == "unproven"
    state.confirmed.route_commit = RouteCommitConfirmed(latest.event_id, latest.run_id or "")
    assert derive_routing_history(tmp_path, state).status == "supported"

    state.confirmed.route_commit = RouteCommitConfirmed("sevt_00000000000000000000000000000000", "run_000000000003")
    assert derive_routing_history(tmp_path, state).status == "unproven"


def test_projection_to_aborted_commit_is_unproven_even_with_older_effective(
    tmp_path: Path,
) -> None:
    state = _state()
    _append_attempt(tmp_path, state, "run_000000000001")
    aborted = _append_attempt(tmp_path, state, "run_000000000002", aborted=True)
    state.confirmed.route_commit = RouteCommitConfirmed(aborted.event_id, aborted.run_id or "")

    assert derive_routing_history(tmp_path, state).status == "unproven"


def test_projection_run_id_mismatch_is_unproven(tmp_path: Path) -> None:
    state = _state()
    commit = _append_attempt(tmp_path, state, "run_000000000001")
    state.confirmed.route_commit = RouteCommitConfirmed(commit.event_id, "run_000000000002")

    assert derive_routing_history(tmp_path, state).status == "unproven"


def test_projection_with_only_aborted_attempts_is_unproven(tmp_path: Path) -> None:
    state = _state()
    aborted = _append_attempt(tmp_path, state, "run_000000000001", aborted=True)
    state.confirmed.route_commit = RouteCommitConfirmed(aborted.event_id, aborted.run_id or "")

    history = derive_routing_history(tmp_path, state)

    assert history.status == "unproven"
    assert history.effective_commit is None


def test_marking_snapshots_must_match_every_effective_proxy_slot(
    tmp_path: Path,
) -> None:
    payload = _payload(kind="proxy")
    payload["route"] = {
        "kind": "proxy",
        "backend_id": None,
        "proxy_id": "proxy-1",
        "template": "litellm-openai",
        "custom_route_fingerprint": None,
    }
    payload["default_tier"] = "sonnet"
    payload["tier_mappings"] = {"sonnet": "openai/gpt-5"}
    payload["route_scope_tags"] = ["route:proxy", "runtime:claude_code"]
    payload["marking_snapshots"] = []

    with pytest.raises(SessionEventValidationError, match="effective model slots"):
        append_routing_event(tmp_path, _commit(_state(), "run_000000000001", payload))


def test_marking_snapshot_declaration_has_an_exact_normalized_shape(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["marking_snapshots"][0]["declaration"]["extra"] = True

    with pytest.raises(SessionEventValidationError, match="invalid field set"):
        append_routing_event(tmp_path, _commit(_state(), "run_000000000001", payload))


def test_marking_snapshot_canonical_model_must_match_the_route_model(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["marking_snapshots"][0]["canonical_model"] = "claude-sonnet-5"

    with pytest.raises(SessionEventValidationError, match="does not match route_model"):
        append_routing_event(tmp_path, _commit(_state(), "run_000000000001", payload))


def test_catalog_removal_does_not_reinterpret_valid_historical_model_facts(
    tmp_path: Path,
) -> None:
    state = _state()
    commit = _append_attempt(tmp_path, state, "run_000000000001")
    state.confirmed.route_commit = RouteCommitConfirmed(commit.event_id, commit.run_id or "")

    with patch("forge.session.routing.normalize_model_reference", return_value=None):
        history = derive_routing_history(tmp_path, state)

    assert history.status == "supported"
    assert history.effective_commit is not None
    assert history.effective_commit.payload["direct_model"] == "claude-opus-5"
    assert history.effective_commit.payload["marking_snapshots"][0]["canonical_model"] == "claude-opus-5"


def test_historical_read_still_rejects_a_current_catalog_canonical_mismatch(
    tmp_path: Path,
) -> None:
    state = _state()
    commit = _commit(state, "run_000000000001")
    commit.payload["marking_snapshots"][0]["canonical_model"] = "claude-sonnet-5"
    append_session_event(tmp_path, "routing", asdict(commit))

    with pytest.raises(SessionEventValidationError, match="does not match route_model"):
        read_routing_events(tmp_path, state)


def test_direct_route_rejects_proxy_default_or_inconsistent_selection(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["default_tier"] = "sonnet"
    with pytest.raises(SessionEventValidationError, match="default_tier"):
        append_routing_event(tmp_path, _commit(_state(), "run_000000000001", payload))

    payload = _payload()
    payload["requested_model"] = "claude-sonnet-5"
    payload["selected_tier"] = "sonnet"
    payload["selected_model"] = "claude-opus-5"
    with pytest.raises(SessionEventValidationError, match="selected model"):
        append_routing_event(tmp_path, _commit(_state(), "run_000000000002", payload))


def test_abort_operation_must_match_its_commit(tmp_path: Path) -> None:
    state = _state()
    commit = _commit(state, "run_000000000001")
    abort = replace(_abort(state, "run_000000000001"), operation="start")
    append_session_event(tmp_path, "routing", asdict(commit))
    append_session_event(tmp_path, "routing", asdict(abort))

    with pytest.raises(SessionEventValidationError, match="operation does not match"):
        read_routing_events(tmp_path, state)


@pytest.mark.parametrize("mutation", ["orphan", "duplicate_commit", "duplicate_abort", "runtime"])
def test_malformed_history_is_a_command_error(tmp_path: Path, mutation: str) -> None:
    state = _state()
    run = "run_000000000001"
    commit = _commit(state, run)
    abort = _abort(state, run)
    if mutation == "orphan":
        events = [abort]
    elif mutation == "duplicate_commit":
        events = [
            commit,
            replace(commit, event_id="sevt_11111111111111111111111111111111"),
        ]
    elif mutation == "duplicate_abort":
        events = [
            commit,
            abort,
            replace(abort, event_id="sevt_22222222222222222222222222222222"),
        ]
    else:
        events = [replace(commit, runtime="codex")]
    for event in events:
        append_session_event(
            tmp_path,
            "routing",
            asdict(event),
        )

    with pytest.raises(SessionEventValidationError):
        read_routing_events(tmp_path, state)
