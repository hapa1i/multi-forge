"""Durable review starts and outcomes, independent of hook terminal output.

Global telemetry owns these records (as it owns usage/upstream events). A held
flock proves that a pending writer is alive without relying on a reusable PID.
Readers derive incomplete state without rewriting records. Session deletion
preserves this telemetry; telemetry reset removes records and their lock files.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO
from uuid import uuid4

import dacite

from forge.core.paths import get_forge_home
from forge.core.state import atomic_write_json, parse_iso
from forge.policy.action_identity import action_fingerprint
from forge.policy.semantic.plan_source import PlanSnapshot
from forge.policy.types import ActionContext, PolicyDecision
from forge.session.models import LaneRecord, SupervisorConfig

_log = logging.getLogger(__name__)


@dataclass
class AttemptRecord:
    schema_version: int
    attempt_id: str
    session: str
    forge_root: str | None
    root_run_id: str | None
    action_id: str
    origin: str
    tool_name: str
    target_path: str | None
    plan_path: str | None
    plan_digest: str | None
    conversation: str | None
    lane: LaneRecord | None
    model: str | None
    effort: str | None
    auth_mode: str
    stage: str
    started_at: str
    deadline_at: str
    owner_pid: int
    state: str = "pending"
    reason: str | None = None
    finished_at: str | None = None
    verdict: str | None = None
    cached: bool = False
    model_run_id: str | None = None
    observed_models: list[str] = field(default_factory=list)


def attempts_directory() -> Path:
    return get_forge_home() / "telemetry" / "supervisor_attempts"


class ReviewAttempt:
    """Required start evidence; a failed finalization must not claim successful review."""

    def __init__(
        self,
        config: SupervisorConfig,
        context: ActionContext,
        snapshot: PlanSnapshot,
        lane: LaneRecord | None,
        *,
        budget: float,
        stage: str = "frontier",
    ) -> None:
        now = datetime.now(timezone.utc)
        self.record = AttemptRecord(
            schema_version=1,
            attempt_id=uuid4().hex,
            session=context.session_name,
            forge_root=os.environ.get("FORGE_FORGE_ROOT") or config.forge_root,
            root_run_id=os.environ.get("FORGE_ROOT_RUN_ID"),
            action_id=action_fingerprint(context),
            origin=context.origin,
            tool_name=context.tool_name,
            target_path=context.target_path,
            plan_path=snapshot.path,
            plan_digest=snapshot.digest,
            conversation=config.resume_id,
            lane=lane,
            model=config.supervisor_model,
            effort=config.supervisor_effort,
            auth_mode=config.auth_mode,
            stage=stage,
            started_at=now.isoformat(),
            deadline_at=(now + timedelta(seconds=max(0, budget) + 2)).isoformat(),
            owner_pid=os.getpid(),
        )
        if stage == "checker":
            from forge.policy.semantic.plan_check import resolve_plan_check_route

            route = resolve_plan_check_route(config)
            self.record.model = route.model
            self.record.effort = config.checker_effort
            self.record.lane = None  # API checker is not a subprocess consumer lane.
        directory = attempts_directory()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / f"{self.record.attempt_id}.json"
        self.lock_path = self.path.with_suffix(".lock")
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        self._lock: BinaryIO = os.fdopen(descriptor, "rb+")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            atomic_write_json(self.path, asdict(self.record))
        except BaseException:
            self._lock.close()
            raise

    def finish(self, decision: PolicyDecision) -> None:
        self.record.state = "unavailable" if decision.fail_open or decision.failure_type else "completed"
        self.record.reason = decision.failure_type
        self.record.verdict = None if self.record.state == "unavailable" else decision.decision
        self.record.cached = decision.cached
        self.record.model_run_id = decision.telemetry_run_id
        self.record.finished_at = datetime.now(timezone.utc).isoformat()
        try:
            atomic_write_json(self.path, asdict(self.record))
        finally:
            self._lock.close()

    def close(self) -> None:
        """Leave a start without a terminal claim when evaluation/finalization raises."""
        self._lock.close()


def _project_state(record: AttemptRecord, path: Path) -> None:
    if record.state != "pending":
        return
    expired = datetime.now(timezone.utc) > parse_iso(record.deadline_at)
    alive = False
    try:
        with path.with_suffix(".lock").open("rb") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                alive = True
    except FileNotFoundError:
        pass
    if expired or not alive:
        record.state = "incomplete"
        record.reason = "deadline_elapsed" if expired else "reviewer_owner_exited"


def record_cached_review(
    config: SupervisorConfig,
    context: ActionContext,
    snapshot: PlanSnapshot,
    lane: LaneRecord | None,
    decision: PolicyDecision,
) -> PolicyDecision:
    """A cache hit is review evidence, with no invented model invocation."""
    attempt = ReviewAttempt(config, context, snapshot, lane, budget=1)
    try:
        attempt.finish(decision)
    finally:
        attempt.close()
    return decision


def read_attempts(
    session: str, forge_root: str | None = None, *, since: datetime | None = None
) -> list[dict[str, Any]]:
    """Read matching evidence without mutating or fabricating model usage/cost."""
    records: list[dict[str, Any]] = []
    for path in attempts_directory().glob("*.json"):
        try:
            record = dacite.from_dict(AttemptRecord, json.loads(path.read_text()), config=dacite.Config(strict=True))
            if record.schema_version != 1:
                raise ValueError("Unsupported supervisor-attempt schema; upgrade Forge")
            if record.session != session or (forge_root and record.forge_root != forge_root):
                continue
            if since is not None and parse_iso(record.started_at) < since:
                continue
            _project_state(record, path)
            records.append(asdict(record))
        except (OSError, ValueError, TypeError, dacite.DaciteError) as exc:
            _log.warning("Supervisor attempt %s is unreadable: %s", path.name, exc)
    return sorted(records, key=lambda row: row["started_at"], reverse=True)
