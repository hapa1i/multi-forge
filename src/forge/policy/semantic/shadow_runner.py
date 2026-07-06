"""Supervisor shadow sampling -- drain side (Slice 2).

Replays the frontier supervisor on captured shadow candidates (Slice 1) post-hoc,
records the verdict, and **never enforces**. Runs in a detached
``forge policy shadow run`` worker (the memory-writer pattern), so it is heavy and
isolated from the PreToolUse hook path.

Idempotency is per-candidate, not via the work queue: the queue deletes the
shadow marker the instant the handler ``Popen``s the worker, so the marker's
poison cap never sees the detached worker's outcome. Instead each candidate is
**atomically claimed** (``rename`` to ``.processing``) before any frontier call --
a re-spawned or concurrent worker that loses the rename race skips it, bounding
frontier billing to at-most-once per candidate.

A *deterministic* post-claim failure (unreadable JSON, a reconstruction error) is
**finalized** as ``.done`` with ``status="error"`` rather than left as ``.processing``:
re-running it would only fail again, a stranded ``.processing`` would count as phantom
``pending`` forever (the drain re-sweeps only ``*.json``) and permanently consume a cap
slot. Only a hard crash mid-write leaves a ``.processing`` behind.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from forge.core.state import now_iso
from forge.core.telemetry.upstream import UpstreamStatus, record_upstream_operation
from forge.policy.semantic.supervisor import (
    SUPERVISOR_INTENT,
    SupervisorRun,
    run_supervisor_check,
)
from forge.policy.types import ActionContext
from forge.session.artifacts import get_artifact_paths
from forge.session.models import LaneRecord, SupervisorConfig

_log = logging.getLogger(__name__)

SHADOW_USAGE_COMMAND = "supervisor-shadow"

# Classification statuses (also the candidate's terminal ``status`` value).
STATUS_AGREE = "agree"  # frontier also found the action aligned
STATUS_DISAGREE = "disagree"  # frontier would have BLOCKED (high-confidence + cited divergence)
STATUS_INCONCLUSIVE = "inconclusive"  # frontier divergent but below the block bar
STATUS_ERROR = "error"  # the frontier run failed or its output did not parse


def _shadow_status_to_upstream(status: str) -> UpstreamStatus:
    if status == STATUS_AGREE:
        return "success"
    if status == STATUS_DISAGREE:
        return "deny"
    if status == STATUS_INCONCLUSIVE:
        return "warning"
    return "error"


def classify_shadow(run: SupervisorRun) -> str:
    """Map a frontier run to a shadow status using the supervisor's OWN block bar.

    A ``disagree`` is exactly a verdict that ``verdict_to_decision`` would have
    turned into a ``deny`` (divergent + confidence >= 0.8 + citations), so the
    audit never re-implements the threshold. A failed/unparseable run is
    ``error`` -- distinct from a real low-confidence ``inconclusive`` (Finding 3).
    """
    if not (run.run_ok and run.parsed) or run.verdict is None:
        return STATUS_ERROR
    if run.verdict.verdict == "aligned":
        return STATUS_AGREE
    return STATUS_DISAGREE if run.decision.decision == "deny" else STATUS_INCONCLUSIVE


def reconstruct_context(candidate: dict[str, Any]) -> ActionContext:
    """Rebuild the FULL ActionContext the frontier needs from frozen raw fields."""
    return ActionContext(
        origin=candidate.get("origin", "claude_code"),
        event=candidate.get("event", "PreToolUse.Write"),
        tool_name=candidate["tool_name"],
        tool_args=candidate.get("tool_args") or {},
        repo_root=candidate.get("repo_root", ""),
        session_name=candidate["session_name"],
        target_path=candidate.get("target_path"),
        new_content=candidate.get("new_content"),
        raw_diff=candidate.get("raw_diff"),
    )


def reconstruct_config(candidate: dict[str, Any], directory: Path) -> SupervisorConfig:
    """Rebuild a SupervisorConfig from the frozen routing snapshot.

    ``plan_override_path`` points at the frozen ``<hash>.plan.md`` sidecar (not the
    live plan), so the frontier judges exactly the plan tier-1 saw.
    """
    plan_file = candidate.get("plan_snapshot_file")
    plan_override_path = str(directory / plan_file) if plan_file else None
    return SupervisorConfig(
        resume_id=candidate.get("resume_id"),
        direct=bool(candidate.get("direct", False)),
        base_url=candidate.get("base_url"),
        proxy=candidate.get("proxy"),
        forge_root=candidate.get("forge_root"),
        timeout_seconds=int(candidate.get("timeout_seconds", 45)),
        fork_session=bool(candidate.get("fork_session", True)),
        plan_override_path=plan_override_path,
    )


def reconstruct_lane(candidate: dict[str, Any]) -> LaneRecord | None:
    """Rebuild the replay lane from the frozen candidate (epic consumer_lanes, T1b).

    The candidate stores the resolved consumer-lane binding as a ``lane`` dict (v3). None =>
    the claude default. An older record (no ``lane``) or a malformed one degrades to None ->
    default replay -- shadow candidates are runtime-only state, discard-and-default per
    coding_standards section 5.
    """
    lane = candidate.get("lane")
    if not isinstance(lane, dict):
        return None
    try:
        return LaneRecord(lane["runtime_id"], lane["backend_id"], lane["model"])
    except (KeyError, TypeError, ValueError):
        return None


def run_shadow_candidate(path: Path) -> str | None:
    """Claim, run the frontier, classify, and finalize one pending candidate.

    Returns the terminal status, or None only when the claim race was lost (another
    worker got it). Every claimed candidate is finalized to ``.done`` -- a real
    verdict, or ``status="error"`` for a deterministic post-claim failure -- so it is
    never stranded as phantom ``pending``. Never enforces; ``run_supervisor_check``
    is the sole usage emitter (``command="supervisor-shadow"``).
    """
    processing = path.with_suffix(".processing")
    done = path.with_suffix(".done")
    try:
        os.rename(path, processing)  # atomic claim -- loser of the race raises and skips
    except OSError:
        return None

    try:
        candidate = json.loads(processing.read_text())
    except Exception:
        # Corrupt content can't merge into a record; write a minimal error marker so the
        # read surface counts it as `error` (not phantom pending) and finalize it.
        _log.warning("Unreadable shadow candidate %s; finalizing as error", processing.name)
        _finalize_error(processing, done, {"error": "unreadable candidate JSON"})
        _record_shadow_drain_outcome(STATUS_ERROR)
        return STATUS_ERROR

    run: SupervisorRun | None = None
    try:
        context = reconstruct_context(candidate)
        config = reconstruct_config(candidate, processing.parent)
        lane = reconstruct_lane(candidate)
        run = run_supervisor_check(
            config, context, intent=SUPERVISOR_INTENT, usage_command=SHADOW_USAGE_COMMAND, lane_record=lane
        )
        status = classify_shadow(run)
        candidate["status"] = status
        candidate["run_ok"] = run.run_ok
        candidate["parsed"] = run.parsed
        if run.verdict is not None:
            candidate["frontier_verdict"] = run.verdict.verdict
            candidate["frontier_confidence"] = run.verdict.confidence
            candidate["frontier_violations"] = run.verdict.violations
    except Exception:
        # run_supervisor_check is fail-open, but reconstruction can raise on a malformed
        # candidate. Finalize as error rather than orphan the claimed .processing file.
        _log.warning("Shadow check failed post-claim for %s", processing.name, exc_info=True)
        status = STATUS_ERROR
        candidate["status"] = STATUS_ERROR
        candidate["error"] = "post-claim failure"

    candidate["checked_at"] = now_iso()
    processing.write_text(json.dumps(candidate, indent=2))
    os.rename(processing, done)
    _record_shadow_drain_outcome(status, candidate=candidate, run=run)
    return status


def _finalize_error(processing: Path, done: Path, extra: dict[str, Any]) -> None:
    """Write a minimal ``status="error"`` record and finalize ``.processing`` -> ``.done``."""
    record = {"status": STATUS_ERROR, "checked_at": now_iso(), **extra}
    processing.write_text(json.dumps(record, indent=2))
    os.rename(processing, done)


def _record_shadow_drain_outcome(
    status: str,
    *,
    candidate: dict[str, Any] | None = None,
    run: SupervisorRun | None = None,
) -> None:
    candidate = candidate or {}
    record_upstream_operation(
        command=SHADOW_USAGE_COMMAND,
        operation="policy.shadow_drain",
        status=_shadow_status_to_upstream(status),
        session=candidate.get("session_name") if isinstance(candidate.get("session_name"), str) else None,
        run_id=run.decision.telemetry_run_id if run is not None else None,
        parent_run_id=run.decision.telemetry_parent_run_id if run is not None else None,
        root_run_id=run.decision.telemetry_root_run_id if run is not None else None,
        origin=candidate.get("origin") if isinstance(candidate.get("origin"), str) else None,
        tool_name=candidate.get("tool_name") if isinstance(candidate.get("tool_name"), str) else None,
        target_path=candidate.get("target_path") if isinstance(candidate.get("target_path"), str) else None,
        reason_code=status,
    )


def run_shadow_for_session(session_name: str, forge_root: str) -> dict[str, int]:
    """Drain all pending shadow candidates for a session; return per-status counts."""
    directory = get_artifact_paths(Path(forge_root), session_name).shadow_abs
    counts: dict[str, int] = {}
    if not directory.is_dir():
        return counts
    for path in sorted(directory.glob("*.json")):
        try:
            status = run_shadow_candidate(path)
        except Exception:
            _log.warning("Shadow check failed for %s", path.name, exc_info=True)
            continue
        if status:
            counts[status] = counts.get(status, 0) + 1
    return counts
