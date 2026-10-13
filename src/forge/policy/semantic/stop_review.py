"""Once-per-explicit-turn supervision over immutable, already-applied evidence.

The session review journal owns the allowance, independently of telemetry. A
reservation is terminal for spending even if the owner dies before dispatch.
Only a new measured UserPromptSubmit may open an allowance. An unknown newer
Stop advances the watermark as an excluded, untracked scope without dispatch.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import UUID, uuid4

from forge.core.native_review_types import NativeReviewBoundary
from forge.core.state import utc_timestamp_z
from forge.policy.semantic import turn_evidence
from forge.policy.semantic.deadline import review_scope
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
from forge.session.store import SessionStore

MAX_ACTIONS = 48
MAX_ACTION_BYTES = 8_000
MAX_PROVENANCE_TURNS = 32
# Seven seconds for a final snapshot, then lock, config verification and output.
COMPLETION_SECONDS = 10.0


@dataclass(frozen=True)
class TurnContext:
    forge_root: Path
    session: str
    checkout: Path
    thread_id: str
    turn_id: str
    config: SupervisorConfig
    lane: LaneRecord | None
    session_identity: str
    native_boundary: NativeReviewBoundary | None = None

    def __post_init__(self) -> None:
        _hex(self.session_identity, 32)
        # Admission pins the native version that produced UUIDv7 identifiers.
        for value in (self.thread_id, self.turn_id):
            parsed = UUID(value)
            if str(parsed) != value or parsed.version != 7:
                raise ValueError("Unverified native turn identity")

    @property
    def config_digest(self) -> str:
        return turn_evidence.digest(
            {
                "config": asdict(self.config),
                "lane": asdict(self.lane) if self.lane else None,
            }
        )

    @property
    def storage(self) -> Path:
        return (
            get_session_event_journal_path(
                self.forge_root, self.session, "review", review_id=self.session_identity
            ).parent
            / "evidence"
        )


@dataclass
class StopOutcome:
    status: str
    reason: str | None = None
    decision: PolicyDecision | None = None
    correction: bool = False
    complete: bool = False


def begin_turn(context: TurnContext, *, deadline: float) -> None:
    """Freeze this prompt's baseline, carrying only work bounded by observed events."""

    def update(previous: SessionEvent | None) -> SessionEvent | None:
        old = _state(previous, context)
        watermark = (
            max(
                int(old["watermark"]),
                UUID(old.get("blocked_until_turn", old["turn_id"])).int,
            )
            if old
            else 0
        )
        if UUID(context.turn_id).int <= watermark:
            return None
        reset = bool(old and old.get("reset_requested"))
        pending = bool(
            old
            and not reset
            and (
                old["outstanding"]
                or (
                    old["status"] == "collecting"
                    and (
                        old["actions"]
                        or old.get("carry_omissions")
                        or old.get("baseline") != old.get("observed_snapshot")
                    )
                )
            )
        )
        if pending and old and len(old["provenance"]) >= MAX_PROVENANCE_TURNS:
            old.update(
                status="unavailable",
                reason="carry_limit",
                outstanding=True,
                blocked_until_turn=context.turn_id,
            )
            return _event(context, old)
        current = None
        capture_error = None
        try:
            references = [old[k] for k in ("baseline", "reviewed", "observed_snapshot") if old and old.get(k)]
            turn_evidence.prune(context.storage, [] if reset else references)
            current = turn_evidence.capture(context.checkout, context.storage, deadline=deadline)
        except (
            OSError,
            ValueError,
            TimeoutError,
            RuntimeError,
            subprocess.SubprocessError,
        ) as exc:
            capture_error = type(exc).__name__
        state = _new_state(context, current)
        state["excluded_work"] = copy.deepcopy(old.get("excluded_work")) if old else None
        if reset and old:
            _exclude(state, old, "operator_reset")
        elif pending and old:
            if current and old.get("baseline") and old.get("observed_snapshot"):
                baseline, unattributed, conflicts = turn_evidence.rebase_pending(
                    context.storage, old["baseline"], old["observed_snapshot"], current
                )
                state.update(
                    baseline=baseline,
                    outstanding=True,
                    provenance=old["provenance"] + [context.turn_id],
                    actions=copy.deepcopy(old["actions"]),
                    carry_omissions=list(old.get("carry_omissions", [])),
                    unattributed_changes={
                        "count": len(unattributed),
                        "paths": unattributed[:32],
                    },
                )
                if conflicts:
                    # Old action descriptions cannot authorize corrections to a
                    # path changed outside the observed turn. Keep the gap explicit.
                    state["actions"] = []
                    state["carry_omissions"].append("unattributed_pending_work")
                    _exclude(state, old, "unattributed_pending_work")
            else:
                _exclude(state, old, "missing_observation")
        elif old and current and old.get("observed_snapshot"):
            _, unattributed, _ = turn_evidence.rebase_pending(
                context.storage,
                old["observed_snapshot"],
                old["observed_snapshot"],
                current,
            )
            state["unattributed_changes"] = {
                "count": len(unattributed),
                "paths": unattributed[:32],
            }
        if capture_error:
            state.update(
                status="unavailable",
                reason="baseline_unavailable",
                baseline_error=capture_error,
                outstanding=True,
            )
        return _event(context, state)

    _update(context, update)


def _new_state(context: TurnContext, snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schema": 2,
        "session_identity": context.session_identity,
        "forge_root": str(context.forge_root.resolve()),
        "checkout": str(context.checkout.resolve()),
        "thread_id": context.thread_id,
        "turn_id": context.turn_id,
        "watermark": str(UUID(context.turn_id).int),
        "config_digest": context.config_digest,
        "spent": False,
        "dispatched": False,
        "status": "collecting",
        "reason": None,
        "outstanding": False,
        "provenance": [context.turn_id],
        "actions": [],
        "correction_consumed": False,
        "baseline": snapshot,
        "start_snapshot": snapshot,
        "observed_snapshot": snapshot,
        "excluded_work": None,
        "unattributed_changes": {"count": 0, "paths": []},
        "reset_requested": False,
        "reviewed": None,
        "attempt_id": None,
        "evidence_digest": None,
        "evidence": None,
        "decision": None,
        "updated_at": utc_timestamp_z(),
        "coverage": None,
        "carry_omissions": [],
    }


def _exclude(state: dict[str, Any], source: dict[str, Any], reason: str) -> None:
    previous = state.get("excluded_work") or {}
    watermark = UUID(previous["last_turn"]).int if previous else 0
    added = sum(UUID(turn).int > watermark for turn in source["provenance"])
    if previous and not added:
        return
    state["excluded_work"] = {
        "turns": previous.get("turns", 0) + added,
        "last_turn": source["turn_id"],
        "last_thread": source["thread_id"],
        "reason": reason,
        "reviewed": False,
    }


def record_action(context: TurnContext, action: dict[str, Any]) -> None:
    """Keep bounded request/outcome evidence, including actions with no final diff."""

    def update(previous: SessionEvent | None) -> SessionEvent | None:
        state = _state(previous, context)
        if state is None or not _current(state, context):
            return None
        if state["config_digest"] != context.config_digest:
            state.update(status="unavailable", reason="configuration_changed", outstanding=True)
            return _event(context, state)
        if state is not None and (state.get("reset_requested") or state.get("blocked_until_turn")):
            return None
        if action.get("phase") == "denied":
            state["actions"] = [
                row
                for row in state["actions"]
                if not (row.get("id") == action.get("id") and row.get("turn_id") == action.get("turn_id"))
            ]
            return _event(context, state)
        if any(
            row.get("id") == action.get("id")
            and row.get("phase") == action.get("phase")
            and row.get("turn_id") == action.get("turn_id")
            for row in state["actions"]
        ):
            return None
        if state["spent"] and not state["outstanding"]:
            # A later tool can start after an operator edit. Its request is the
            # first observed boundary for this continuation, not the old verdict.
            snapshot = turn_evidence.capture(context.checkout, context.storage, deadline=time.monotonic() + 7)
            state.update(
                baseline=snapshot,
                actions=[],
                observed_snapshot=snapshot,
                carry_omissions=[],
            )
        if state["spent"]:
            state.update(status="unreviewed", reason="actions_after_review", outstanding=True)
        if len(state["actions"]) >= MAX_ACTIONS:
            state.update(status="unavailable", reason="action_limit", outstanding=True)
            state["carry_omissions"] = sorted(set(state.get("carry_omissions", []) + ["action_limit"]))
        else:
            state["actions"].append(action)
        if action.get("phase") == "outcome":
            try:
                state["observed_snapshot"] = turn_evidence.capture(
                    context.checkout, context.storage, deadline=time.monotonic() + 7
                )
            except (
                OSError,
                ValueError,
                TimeoutError,
                RuntimeError,
                subprocess.SubprocessError,
            ):
                state["carry_omissions"] = sorted(set(state["carry_omissions"] + ["observation_unavailable"]))
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
        if state is not None and (state.get("reset_requested") or state.get("blocked_until_turn")):
            outcome = StopOutcome(
                "unavailable",
                ("new_explicit_turn_required" if state.get("reset_requested") else "carry_limit"),
            )
            return None
        if state is None or not _current(state, context):
            if state is None or UUID(context.turn_id).int > int(state["watermark"]):
                missing = _new_state(context, None)
                missing["excluded_work"] = copy.deepcopy(state.get("excluded_work")) if state else None
                if state and (state["outstanding"] or state["status"] == "collecting"):
                    _exclude(missing, state, "missing_turn_start")
                _exclude(missing, missing, "missing_turn_start")
                missing.update(status="unavailable", reason="missing_turn_start")
                outcome = StopOutcome("unavailable", "missing_turn_start")
                return _event(context, missing)
            outcome = StopOutcome("unavailable", "missing_or_stale_turn")
            return None
        if state["config_digest"] != context.config_digest:
            state.update(status="unavailable", reason="configuration_changed", outstanding=True)
            outcome = StopOutcome("unavailable", "configuration_changed")
            return _event(context, state)
        if state.get("spent"):
            # Never replay a stored block. Delivery may have happened before the owner died.
            if state["status"] == "reviewing":
                state.update(
                    status="incomplete",
                    reason="reserved_without_completed_review",
                    outstanding=True,
                )
            if state.get("reviewed"):
                now = turn_evidence.capture(context.checkout, context.storage, deadline=deadline)
                state["observed_snapshot"] = now
                if now["digest"] != state["reviewed"]["digest"]:
                    state.update(
                        status="unreviewed",
                        reason="changes_after_review",
                        outstanding=True,
                    )
                elif state["correction_consumed"]:
                    state.update(
                        status="unreviewed",
                        reason="correction_not_reassessed",
                        outstanding=True,
                    )
            else:
                state.update(
                    status="incomplete",
                    reason="reserved_without_completed_review",
                    outstanding=True,
                )
            outcome = StopOutcome(state["status"], state.get("reason"))
            return _event(context, state)
        if not state.get("baseline") or state.get("reason") == "configuration_changed":
            outcome = StopOutcome("unavailable", state.get("reason") or "missing_baseline")
            return None
        now = turn_evidence.capture(context.checkout, context.storage, deadline=deadline)
        state["observed_snapshot"] = now
        evidence = turn_evidence.compare(context.storage, state["baseline"], now, state["actions"])
        if state.get("carry_omissions"):
            evidence["omissions"] = sorted(set(evidence["omissions"] + state["carry_omissions"]))
            evidence["complete"] = False
        evidence["provenance_turns"] = state["provenance"]
        if len(json.dumps(evidence, sort_keys=True).encode()) > turn_evidence.MAX_EVIDENCE_BYTES:
            evidence = {
                "complete": False,
                "omissions": ["review_prompt_byte_limit"],
                "changes_count": len(evidence.get("changes", [])),
                "actions_count": len(evidence.get("actions", [])),
                "provenance_turns": state["provenance"],
            }
        state["coverage"] = {
            "complete": evidence["complete"],
            "omissions": evidence["omissions"],
        }
        meaningful_actions = any(row.get("phase") == "outcome" for row in state["actions"])
        if not evidence["complete"] and not (
            evidence.get("changes") or any(row.get("phase") == "outcome" for row in evidence.get("actions", []))
        ):
            _exclude(state, state, "partial_evidence")
            state.update(status="unavailable", reason="incomplete_evidence", outstanding=False)
            outcome = StopOutcome("unavailable", "incomplete_evidence")
            return _event(context, state)
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
            dispatched=None,
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
        native_boundary=context.native_boundary,
    )
    # Only this owner reaches dispatch. Format retry is disabled for Stop by the transport.
    with review_scope(deadline - COMPLETION_SECONDS):
        result = run_supervisor_check(
            context.config,
            action,
            snapshot=plan,
            lane_record=context.lane,
            attempt_id=frozen["attempt_id"],
        )

    def save_result(previous: SessionEvent | None) -> SessionEvent | None:
        state = _state(previous, context)
        if state is None or not _current(state, context) or state.get("attempt_id") != frozen["attempt_id"]:
            return None
        state.update(decision=asdict(result.decision), dispatched=result.dispatched)
        return _event(context, state)

    # A completed deny is audit evidence even if the subsequent freshness check
    # fails. Keep the reservation spent and save before another expensive capture.
    _update(context, save_result)
    completion_failed = False
    try:
        after = turn_evidence.capture(context.checkout, context.storage, deadline=deadline - 2)
        latest_plan = read_plan(context.config)
        config_matches = current_config() == context.config_digest
        stale = (
            after["digest"] != frozen["reviewed"]["digest"]
            or latest_plan.fingerprint != plan.fingerprint
            or not config_matches
        )
        if time.monotonic() >= deadline - 1:
            raise TimeoutError("Stop completion budget exhausted")
    except (
        OSError,
        ValueError,
        TimeoutError,
        RuntimeError,
        subprocess.SubprocessError,
    ):
        completion_failed, stale = True, True

    def finish(previous: SessionEvent | None) -> SessionEvent | None:
        nonlocal outcome
        state = _state(previous, context)
        if state is None or not _current(state, context) or state.get("attempt_id") != frozen["attempt_id"]:
            outcome = StopOutcome("unavailable", "turn_changed_during_review")
            return None
        state["decision"] = asdict(result.decision)
        state["dispatched"] = result.dispatched
        if state.get("reset_requested") or state.get("blocked_until_turn"):
            outcome = StopOutcome(
                "unavailable",
                ("new_explicit_turn_required" if state.get("reset_requested") else "carry_limit"),
            )
        elif completion_failed:
            state.update(status="unavailable", reason="completion_unavailable", outstanding=True)
            outcome = StopOutcome("unavailable", "completion_unavailable")
        elif stale:
            state.update(status="unreviewed", reason="stale_review", outstanding=True)
            outcome = StopOutcome("unreviewed", "stale_review")
        elif not result.run_ok or not result.parsed or result.decision.fail_open or result.decision.failure_type:
            state.update(
                status="unavailable",
                reason=result.decision.failure_type or "review_unavailable",
                outstanding=True,
            )
            outcome = StopOutcome("unavailable", state["reason"])
        elif not frozen["evidence"]["complete"]:
            # A partial verdict cannot authorize a correction or approve omitted
            # work. Retain the gap as history without poisoning every later turn.
            _exclude(state, state, "partial_evidence")
            state.update(status="partial", reason="incomplete_evidence", outstanding=False)
            outcome = StopOutcome("partial", "incomplete_evidence", decision=result.decision)
        else:
            deny = result.decision.decision == "deny"
            state.update(
                status="reviewed",
                reason=None,
                outstanding=deny,
                correction_consumed=deny,
            )
            outcome = StopOutcome("reviewed", decision=result.decision, correction=deny, complete=True)
        return _event(context, state)

    _update(context, finish)
    return outcome


def status(
    forge_root: Path,
    session: str,
    *,
    config: SupervisorConfig | None = None,
    lane: LaneRecord | None = None,
) -> dict[str, Any]:
    """Project private operational records to a bounded public status without rewriting them."""
    try:
        event = read_review_checkpoint(forge_root, session, payload_validator=validate_payload)
    except (OSError, ValueError, RuntimeError, SessionEventError) as exc:
        return {
            "state": "unavailable",
            "reason": "review_history_unavailable",
            "error_type": type(exc).__name__,
        }
    if event is None:
        return {
            "state": "unavailable",
            "reason": "new_explicit_turn_required",
            "spent": False,
            "dispatched": False,
        }
    data = event.payload
    changed_config = (
        config is not None
        and turn_evidence.digest({"config": asdict(config), "lane": asdict(lane) if lane else None})
        != data["config_digest"]
    )
    return {
        "state": (
            "unavailable" if changed_config else "incomplete" if data["status"] == "reviewing" else data["status"]
        ),
        "reason": (
            "configuration_changed"
            if changed_config
            else ("reserved_without_completed_review" if data["status"] == "reviewing" else data.get("reason"))
        ),
        "thread_id": data["thread_id"],
        "turn_id": data["turn_id"],
        "latest_seen_turn": data.get("blocked_until_turn", data["turn_id"]),
        "spent": data["spent"],
        "dispatch_cap": 1,
        "dispatched": data.get("dispatched") if data["spent"] else False,
        "assessed_snapshot": data.get("reviewed"),
        "attempt_id": data.get("attempt_id"),
        "evidence_digest": data.get("evidence_digest"),
        "coverage": data.get("coverage"),
        "outstanding": data["outstanding"],
        "correction_consumed": data["correction_consumed"],
        "provenance_turns": data["provenance"],
        "carry_limit": MAX_PROVENANCE_TURNS,
        "reset_required": data.get("reason") == "carry_limit" or bool(data.get("baseline_error")),
        "reset_requested": data.get("reset_requested", False),
        "excluded_work": data.get("excluded_work"),
        "unattributed_changes": data.get("unattributed_changes"),
        "updated_at": data["updated_at"],
    }


def reset_review(forge_root: Path, session: str, *, apply: bool = False) -> dict[str, Any]:
    """Exclude pending work on the next explicit prompt, never refund this turn.

    The preview is read-only. Applying records the operator's choice in the same
    bounded journal; the next baseline retains an unreviewed exclusion summary.
    Corrupt/missing established history still requires restoration or a new session.
    """
    result: dict[str, Any] = {
        "applied": False,
        "session": session,
        "requires_new_turn": True,
    }

    def update(previous: SessionEvent | None) -> SessionEvent | None:
        if previous is None:
            result["reason"] = "no_review_history"
            return None
        state = copy.deepcopy(previous.payload)
        result.update(
            turn_id=state["turn_id"],
            spent=state["spent"],
            excluded_turns=len(state["provenance"]),
        )
        if not apply:
            return None
        state.update(
            reset_requested=True,
            status="unavailable",
            reason="operator_reset",
            outstanding=True,
            updated_at=utc_timestamp_z(),
        )
        result["applied"] = True
        return new_session_event(
            session=session,
            runtime="codex",
            event_type="review_checkpoint",
            run_id=None,
            origin_surface="external_cli",
            operation="set",
            outcome="success",
            reason_code="operator_reset",
            payload=state,
            payload_validator=validate_payload,
        )

    if apply:
        update_review_checkpoint(forge_root, session, update, payload_validator=validate_payload)
    else:
        update(read_review_checkpoint(forge_root, session, payload_validator=validate_payload))
    return result


def validate_payload(event_type: str, payload: dict[str, Any]) -> None:
    """Reject unknown/newer or malformed spending state rather than inventing an unused turn."""
    if event_type != "review_checkpoint" or payload.get("schema") != 2:
        raise ValueError("Unsupported Stop review checkpoint; create a new session to preserve historical artifacts")
    required = {
        "forge_root",
        "session_identity",
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
        "reset_requested",
        "excluded_work",
        "carry_omissions",
        "blocked_until_turn",
        "observed_snapshot",
        "unattributed_changes",
    }
    if not required <= payload.keys() or payload.keys() - allowed:
        raise ValueError("Malformed review checkpoint fields")
    for key in ("spent", "outstanding", "correction_consumed"):
        if type(payload[key]) is not bool:
            raise ValueError("Invalid review spending state")
    if type(payload.get("reset_requested", False)) is not bool:
        raise ValueError("Invalid review reset state")
    excluded = payload.get("excluded_work")
    if excluded is not None and (
        not isinstance(excluded, dict)
        or set(excluded) != {"turns", "last_turn", "last_thread", "reason", "reviewed"}
        or type(excluded["turns"]) is not int
        or excluded["turns"] < 1
        or excluded["reviewed"] is not False
        or excluded["reason"]
        not in {
            "operator_reset",
            "partial_evidence",
            "unattributed_pending_work",
            "missing_turn_start",
            "missing_observation",
        }
    ):
        raise ValueError("Invalid excluded review scope")
    if excluded:
        _native_id(excluded["last_turn"])
        _native_id(excluded["last_thread"])
    for key in ("turn_id", "thread_id"):
        _native_id(payload[key])
    _hex(payload["session_identity"], 32)
    unattributed = payload.get("unattributed_changes")
    if unattributed is not None and (
        not isinstance(unattributed, dict)
        or set(unattributed) != {"count", "paths"}
        or type(unattributed["count"]) is not int
        or unattributed["count"] < 0
        or not isinstance(unattributed["paths"], list)
        or len(unattributed["paths"]) > 32
        or not all(isinstance(path, str) for path in unattributed["paths"])
    ):
        raise ValueError("Invalid unattributed change summary")
    if str(UUID(payload["turn_id"]).int) != payload["watermark"]:
        raise ValueError("Invalid review watermark")
    if payload.get("blocked_until_turn") is not None:
        _native_id(payload["blocked_until_turn"])
        if UUID(payload["blocked_until_turn"]).int <= int(payload["watermark"]):
            raise ValueError("Invalid blocked review watermark")
    if not isinstance(payload.get("carry_omissions", []), list) or not all(
        isinstance(item, str) for item in payload.get("carry_omissions", [])
    ):
        raise ValueError("Invalid carried coverage gaps")
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
        "partial",
    }:
        raise ValueError("Invalid review status")
    _hex(payload["config_digest"], 64)
    for key in ("baseline", "reviewed", "start_snapshot", "observed_snapshot"):
        reference = payload.get(key)
        if reference is not None:
            if not isinstance(reference, dict) or set(reference) != {
                "digest",
                "root",
                "files",
                "omissions",
            }:
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
        if len(json.dumps(action).encode()) > MAX_ACTION_BYTES:
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
        payload["status"] in {"reviewing", "reviewed", "partial", "incomplete", "unreviewed"}
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
    if state["session_identity"] != context.session_identity:
        raise ValueError("Review checkpoint belongs to another session lifetime")
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
        # Runtime failure labels include signed return codes (exit_-9). The
        # envelope uses a stable token; the exact failure stays in the payload.
        reason_code=(re.sub(r"[^a-z0-9_]", "_", state["reason"]) if state.get("reason") else None),
        payload=state,
        payload_validator=validate_payload,
    )


def _update(
    context: TurnContext, callback: Callable[[SessionEvent | None], SessionEvent | None]
) -> SessionEvent | None:
    def owned(previous: SessionEvent | None) -> SessionEvent | None:
        if SessionStore(str(context.forge_root), context.session).review_identity() != context.session_identity:
            raise ValueError("Stop event belongs to a deleted or replaced session")
        return callback(previous)

    return update_review_checkpoint(
        context.forge_root,
        context.session,
        owned,
        payload_validator=validate_payload,
        review_id=context.session_identity,
    )
