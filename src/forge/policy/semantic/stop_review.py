"""Once-per-explicit-turn supervision over immutable, already-applied evidence.

The session review journal owns the allowance, independently of telemetry. A
reservation is terminal for spending even if the owner dies before dispatch.
Only a new measured UserPromptSubmit may advance the durable turn watermark.
"""

from __future__ import annotations

import copy
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from forge.core.state import utc_timestamp_z
from forge.policy.semantic import turn_evidence
from forge.policy.semantic.identity import reviewer_cache_identity
from forge.policy.semantic.plan_source import read_plan
from forge.policy.semantic.supervisor import run_supervisor_check
from forge.policy.types import ActionContext, PolicyDecision
from forge.session.events import (
    SessionEvent,
    SessionEventError,
    get_session_event_journal_path,
    new_session_event,
    read_review_checkpoint,
    update_review_checkpoint,
)
from forge.session.models import LaneRecord, SupervisorConfig

MAX_ACTIONS = 48
MAX_PROVENANCE_TURNS = 32


@dataclass(frozen=True)
class TurnContext:
    forge_root: Path
    session: str
    checkout: Path
    thread_id: str
    turn_id: str
    config: SupervisorConfig
    lane: LaneRecord | None

    def __post_init__(self) -> None:
        # Admission pins the native version that produced UUIDv7 identifiers.
        for value in (self.thread_id, self.turn_id):
            parsed = UUID(value)
            if str(parsed) != value or parsed.version != 7:
                raise ValueError("Unverified native turn identity")

    @property
    def config_digest(self) -> str:
        return turn_evidence.digest({"config": asdict(self.config), "lane": asdict(self.lane) if self.lane else None})

    @property
    def storage(self) -> Path:
        return get_session_event_journal_path(self.forge_root, self.session, "review").parent / "evidence"


@dataclass
class StopOutcome:
    status: str
    reason: str | None = None
    decision: PolicyDecision | None = None
    correction: bool = False
    complete: bool = False


def begin_turn(context: TurnContext, *, deadline: float) -> None:
    """Freeze the start state before tools; a duplicate cannot reset spending."""

    def update(previous: SessionEvent | None) -> SessionEvent | None:
        old = _state(previous, context)
        if old and UUID(context.turn_id).int <= int(old["watermark"]):
            return None
        outstanding = bool(old and old.get("outstanding"))
        provenance = list(old["provenance"]) if old and outstanding else []
        provenance.append(context.turn_id)
        state: dict[str, Any] = {
            "schema": 1,
            "forge_root": str(context.forge_root.resolve()),
            "checkout": str(context.checkout.resolve()),
            "thread_id": context.thread_id,
            "turn_id": context.turn_id,
            "watermark": str(UUID(context.turn_id).int),
            "config_digest": context.config_digest,
            "spent": False,
            "status": "collecting",
            "reason": None,
            "outstanding": outstanding,
            "provenance": provenance[-MAX_PROVENANCE_TURNS:],
            "actions": copy.deepcopy(old["actions"]) if old and outstanding else [],
            "correction_consumed": False,
            "baseline": old.get("baseline") if old and outstanding else None,
            "reviewed": None,
            "attempt_id": None,
            "evidence_digest": None,
            "evidence": None,
            "decision": None,
            "updated_at": utc_timestamp_z(),
            "coverage": None,
        }
        try:
            if outstanding and (not old or not old.get("baseline") or old.get("baseline_error")):
                raise ValueError("Outstanding evidence lost its baseline; restore artifacts or use a new session")
            if len(provenance) > MAX_PROVENANCE_TURNS:
                raise ValueError("Outstanding evidence provenance exceeds its bounded history")
            # Held only during local capture/recording, never during reviewer inference.
            references = [old[k] for k in ("baseline", "reviewed") if old and old.get(k)]
            turn_evidence.prune(context.storage, references)
            current = turn_evidence.capture(context.checkout, context.storage, deadline=deadline)
            state["baseline"] = state["baseline"] or current
            state["start_snapshot"] = current
        except (OSError, ValueError, TimeoutError, RuntimeError, subprocess.SubprocessError) as exc:
            state.update(
                status="unavailable", reason="baseline_unavailable", outstanding=True, baseline_error=type(exc).__name__
            )
        return _event(context, state)

    _update(context, update)


def record_action(context: TurnContext, action: dict[str, Any]) -> None:
    """Keep bounded request/outcome evidence, including actions with no final diff."""

    def update(previous: SessionEvent | None) -> SessionEvent | None:
        state = _state(previous, context)
        if state is None or not _current(state, context):
            return None
        if state["config_digest"] != context.config_digest:
            state.update(status="unavailable", reason="configuration_changed", outstanding=True)
            return _event(context, state)
        if any(
            row.get("id") == action.get("id")
            and row.get("phase") == action.get("phase")
            and row.get("turn_id") == action.get("turn_id")
            for row in state["actions"]
        ):
            return None
        if len(state["actions"]) >= MAX_ACTIONS:
            state.update(status="unavailable", reason="action_limit", outstanding=True)
        else:
            state["actions"].append(action)
        return _event(context, state)

    _update(context, update)


def review_stop(context: TurnContext, *, deadline: float, current_config: Callable[[], str]) -> StopOutcome:
    """Reserve before dispatch and consume any correction before returning its wire payload."""
    outcome = StopOutcome("unavailable", "missing_baseline")
    reservation: dict[str, Any] | None = None
    plan = read_plan(context.config)

    def reserve(previous: SessionEvent | None) -> SessionEvent | None:
        nonlocal outcome, reservation
        state = _state(previous, context)
        if state is None or not _current(state, context):
            outcome = StopOutcome("unavailable", "missing_or_stale_turn")
            return None
        if state["config_digest"] != context.config_digest:
            state.update(status="unavailable", reason="configuration_changed", outstanding=True)
            outcome = StopOutcome("unavailable", "configuration_changed")
            return _event(context, state)
        if state.get("spent"):
            # Never replay a stored block. Delivery may have happened before the owner died.
            if state["status"] == "reviewing":
                state.update(status="incomplete", reason="reserved_without_completed_review", outstanding=True)
            if state.get("reviewed"):
                now = turn_evidence.capture(context.checkout, context.storage, deadline=deadline)
                if now["digest"] != state["reviewed"]["digest"]:
                    state.update(status="unreviewed", reason="changes_after_review", outstanding=True)
            else:
                state.update(status="incomplete", reason="reserved_without_completed_review", outstanding=True)
            outcome = StopOutcome(state["status"], state.get("reason"))
            return _event(context, state)
        if not state.get("baseline") or state["status"] == "unavailable":
            outcome = StopOutcome("unavailable", state.get("reason") or "missing_baseline")
            return None
        now = turn_evidence.capture(context.checkout, context.storage, deadline=deadline)
        evidence = turn_evidence.compare(context.storage, state["baseline"], now, state["actions"])
        evidence["provenance_turns"] = state["provenance"]
        if len(json.dumps(evidence, sort_keys=True).encode()) > turn_evidence.MAX_EVIDENCE_BYTES:
            evidence.update(complete=False, omissions=["review_prompt_byte_limit"])
        state["coverage"] = {"complete": evidence["complete"], "omissions": evidence["omissions"]}
        if not evidence["complete"]:
            state.update(status="unavailable", reason="incomplete_evidence", outstanding=True)
            outcome = StopOutcome("unavailable", "incomplete_evidence")
            return _event(context, state)
        meaningful_actions = any(row.get("phase") == "outcome" for row in state["actions"])
        if not evidence.get("changes") and not meaningful_actions and not state["outstanding"]:
            state.update(status="no_changes", reason="complete_unchanged_turn", reviewed=now)
            outcome = StopOutcome("no_changes", complete=True)
            return _event(context, state)
        if not plan.text:
            state.update(status="unavailable", reason="plan_unavailable", outstanding=True)
            outcome = StopOutcome("unavailable", "plan_unavailable")
            return _event(context, state)
        state.update(
            spent=True,
            status="reviewing",
            reason=None,
            outstanding=True,
            reviewed=now,
            attempt_id=uuid4().hex,
            evidence=evidence,
            evidence_digest=turn_evidence.digest(evidence),
            plan_digest=plan.digest,
            reviewer_identity=reviewer_cache_identity(context.config, context.lane),
        )
        reservation = copy.deepcopy(state)
        outcome = StopOutcome("incomplete", "reserved_without_completed_review")
        return _event(context, state)

    _update(context, reserve)
    if reservation is None:
        return outcome
    frozen = reservation
    action = ActionContext(
        origin="codex",
        event="Stop",
        tool_name="TurnReview",
        tool_args={"scope": "already-applied turn"},
        repo_root=str(context.checkout),
        session_name=context.session,
        raw_diff=json.dumps(frozen["evidence"], sort_keys=True),
        action_fingerprint=frozen["evidence_digest"],
    )
    # Only this owner reaches dispatch. Format retry is disabled for Stop by the transport.
    result = run_supervisor_check(
        context.config, action, snapshot=plan, lane_record=context.lane, attempt_id=frozen["attempt_id"]
    )
    after = turn_evidence.capture(context.checkout, context.storage, deadline=deadline)
    latest_plan = read_plan(context.config)
    config_matches = current_config() == context.config_digest

    def finish(previous: SessionEvent | None) -> SessionEvent | None:
        nonlocal outcome
        state = _state(previous, context)
        if state is None or not _current(state, context) or state.get("attempt_id") != frozen["attempt_id"]:
            outcome = StopOutcome("unavailable", "turn_changed_during_review")
            return None
        state["decision"] = asdict(result.decision)
        state["dispatched"] = result.dispatched
        if (
            after["digest"] != frozen["reviewed"]["digest"]
            or latest_plan.fingerprint != plan.fingerprint
            or not config_matches
        ):
            state.update(status="unreviewed", reason="stale_review", outstanding=True)
            outcome = StopOutcome("unreviewed", "stale_review")
        elif not result.run_ok or not result.parsed or result.decision.fail_open or result.decision.failure_type:
            state.update(
                status="unavailable", reason=result.decision.failure_type or "review_unavailable", outstanding=True
            )
            outcome = StopOutcome("unavailable", state["reason"])
        else:
            deny = result.decision.decision == "deny"
            state.update(status="reviewed", reason=None, outstanding=deny, correction_consumed=deny)
            outcome = StopOutcome("reviewed", decision=result.decision, correction=deny, complete=True)
        return _event(context, state)

    _update(context, finish)
    return outcome


def status(
    forge_root: Path, session: str, *, config: SupervisorConfig | None = None, lane: LaneRecord | None = None
) -> dict[str, Any]:
    """Project private operational records to a bounded public status without rewriting them."""
    try:
        event = read_review_checkpoint(forge_root, session, payload_validator=validate_payload)
    except (OSError, ValueError, RuntimeError, SessionEventError) as exc:
        return {"state": "unavailable", "reason": "review_history_unavailable", "error_type": type(exc).__name__}
    if event is None:
        return {"state": "unavailable", "reason": "new_explicit_turn_required", "spent": False}
    data = event.payload
    changed_config = (
        config is not None
        and turn_evidence.digest({"config": asdict(config), "lane": asdict(lane) if lane else None})
        != data["config_digest"]
    )
    return {
        "state": "unavailable" if changed_config else "incomplete" if data["status"] == "reviewing" else data["status"],
        "reason": (
            "configuration_changed"
            if changed_config
            else "reserved_without_completed_review" if data["status"] == "reviewing" else data.get("reason")
        ),
        "thread_id": data["thread_id"],
        "turn_id": data["turn_id"],
        "spent": data["spent"],
        "dispatch_cap": 1,
        "dispatched": data.get("dispatched"),
        "assessed_snapshot": data.get("reviewed"),
        "attempt_id": data.get("attempt_id"),
        "evidence_digest": data.get("evidence_digest"),
        "coverage": data.get("coverage"),
        "outstanding": data["outstanding"],
        "correction_consumed": data["correction_consumed"],
        "provenance_turns": data["provenance"],
        "updated_at": data["updated_at"],
    }


def validate_payload(event_type: str, payload: dict[str, Any]) -> None:
    """Reject unknown/newer or malformed spending state rather than inventing an unused turn."""
    if event_type != "review_checkpoint" or payload.get("schema") != 1:
        raise ValueError("Unsupported review checkpoint schema")
    required = {
        "forge_root",
        "checkout",
        "thread_id",
        "turn_id",
        "watermark",
        "config_digest",
        "spent",
        "status",
        "outstanding",
        "provenance",
        "actions",
        "correction_consumed",
        "baseline",
        "reviewed",
        "updated_at",
    }
    allowed = required | {
        "reason",
        "attempt_id",
        "evidence_digest",
        "evidence",
        "decision",
        "coverage",
        "start_snapshot",
        "baseline_error",
        "plan_digest",
        "reviewer_identity",
        "dispatched",
        "schema",
    }
    if not required <= payload.keys() or payload.keys() - allowed:
        raise ValueError("Malformed review checkpoint fields")
    for key in ("spent", "outstanding", "correction_consumed"):
        if type(payload[key]) is not bool:
            raise ValueError("Invalid review spending state")
    for key in ("turn_id", "thread_id"):
        _native_id(payload[key])
    if str(UUID(payload["turn_id"]).int) != payload["watermark"]:
        raise ValueError("Invalid review watermark")
    if not isinstance(payload["actions"], list) or len(payload["actions"]) > MAX_ACTIONS:
        raise ValueError("Invalid bounded action evidence")
    if not isinstance(payload["provenance"], list) or len(payload["provenance"]) > MAX_PROVENANCE_TURNS:
        raise ValueError("Invalid bounded review provenance")
    for key in ("forge_root", "checkout"):
        if not isinstance(payload[key], str) or not Path(payload[key]).is_absolute():
            raise ValueError("Invalid review checkout identity")
    if payload["status"] not in {
        "collecting",
        "reviewing",
        "reviewed",
        "unavailable",
        "unreviewed",
        "incomplete",
        "no_changes",
    }:
        raise ValueError("Invalid review status")
    _hex(payload["config_digest"], 64)
    for key in ("baseline", "reviewed", "start_snapshot"):
        reference = payload.get(key)
        if reference is not None:
            if not isinstance(reference, dict) or set(reference) != {"digest", "root", "files", "omissions"}:
                raise ValueError("Invalid review snapshot reference")
            _hex(reference["digest"], 64)
            if reference["root"] != payload["checkout"] or type(reference["files"]) is not int:
                raise ValueError("Invalid review snapshot scope")
            if not isinstance(reference["omissions"], list) or not all(
                isinstance(v, str) for v in reference["omissions"]
            ):
                raise ValueError("Invalid review omissions")
    if not payload["provenance"] or payload["provenance"][-1] != payload["turn_id"]:
        raise ValueError("Invalid review provenance")
    for value in payload["provenance"]:
        _native_id(value)
    for action in payload["actions"]:
        if not isinstance(action, dict) or not isinstance(action.get("id"), str) or not action["id"]:
            raise ValueError("Invalid action identity")
        if action.get("phase") not in {"request", "outcome", "denied"}:
            raise ValueError("Invalid action phase")
        if action.get("turn_id") not in payload["provenance"]:
            raise ValueError("Invalid action provenance")
        if len(json.dumps(action).encode()) > 8_000:
            raise ValueError("Unbounded action evidence")
    if payload["spent"]:
        _hex(payload.get("attempt_id"), 32)
        _hex(payload.get("evidence_digest"), 64)
        _hex(payload.get("plan_digest"), 64)
        if not isinstance(payload.get("evidence"), dict) or not payload["reviewed"]:
            raise ValueError("Spent review lacks frozen evidence")
        if turn_evidence.digest(payload["evidence"]) != payload["evidence_digest"]:
            raise ValueError("Changed frozen review evidence")
    elif (
        payload["status"] in {"reviewing", "reviewed", "incomplete", "unreviewed"}
        or payload.get("attempt_id") is not None
        or payload.get("evidence") is not None
        or payload.get("decision") is not None
    ):
        raise ValueError("Completed or reserved review cannot regain its allowance")
    if payload.get("dispatched") is not None and type(payload["dispatched"]) is not bool:
        raise ValueError("Invalid review dispatch observation")
    if payload["correction_consumed"] and not payload["spent"]:
        raise ValueError("Correction without a spent review")


def _native_id(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("Invalid review turn identity")
    parsed = UUID(value)
    if str(parsed) != value or parsed.version != 7:
        raise ValueError("Invalid review turn identity")


def _hex(value: Any, size: int) -> None:
    if not isinstance(value, str) or len(value) != size or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Invalid review identity digest")


def _state(event: SessionEvent | None, context: TurnContext) -> dict[str, Any] | None:
    if event is None:
        return None
    state = copy.deepcopy(event.payload)
    if state["forge_root"] != str(context.forge_root.resolve()) or state["checkout"] != str(context.checkout.resolve()):
        raise ValueError("Review checkpoint belongs to another checkout")
    return state


def _current(state: dict[str, Any] | None, context: TurnContext) -> bool:
    return bool(state and state["thread_id"] == context.thread_id and state["turn_id"] == context.turn_id)


def _event(context: TurnContext, state: dict[str, Any]) -> SessionEvent:
    state["updated_at"] = utc_timestamp_z()
    return new_session_event(
        session=context.session,
        runtime="codex",
        event_type="review_checkpoint",
        run_id=None,
        origin_surface="codex_review_hook",
        operation="runtime_event",
        outcome="success",
        reason_code=state.get("reason"),
        payload=state,
        payload_validator=validate_payload,
    )


def _update(
    context: TurnContext, callback: Callable[[SessionEvent | None], SessionEvent | None]
) -> SessionEvent | None:
    return update_review_checkpoint(context.forge_root, context.session, callback, payload_validator=validate_payload)
