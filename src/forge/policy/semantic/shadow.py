"""Supervisor shadow sampling -- capture side (Slice 1).

When the cascade's tier-1 plan check returns a *fresh* (uncached) ``allow``, a
random sample of those allows is frozen to disk as a **shadow candidate**. A
post-hoc worker (Slice 2) later replays the frontier supervisor on each
candidate to measure how often tier-1 wrongly short-circuited a divergent action
(the cascade's false-aligned rate).

Capture is best-effort and **inert at rate 0**: it runs no frontier call, never
blocks, and writes nothing -- not even the directory -- unless a candidate is
sampled. The candidate freezes the *raw* action inputs (not tier-1's packed
prompt) plus a copy of the plan, because the frontier supervisor builds its own
prompt from raw content and reloads the plan at run time.

Lifecycle suffixes make cap + dedup state-agnostic:
``<hash>.json`` (pending) -> ``<hash>.processing`` (claimed) -> ``<hash>.done``.
``<hash>.plan.md`` is a sidecar (the frozen plan), not a record file.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from forge.core.state import now_iso
from forge.policy.action_identity import action_fingerprint
from forge.policy.semantic.plan_source import PlanSnapshot, read_plan
from forge.policy.types import ActionContext
from forge.session.artifacts import (
    get_artifact_paths,
    make_content_hash,
)
from forge.session.models import LaneRecord, SupervisorConfig

_log = logging.getLogger(__name__)

# v6 also freezes the resolved model and its origin for legacy conversation configs.
SHADOW_SCHEMA_VERSION = 6

# Record-file suffixes (the candidate's lifecycle states). The `.plan.md` sidecar is deliberately excluded so it is
# never counted toward the cap nor mistaken for a candidate record.
RECORD_SUFFIXES = (".json", ".processing", ".done")


@dataclass
class ShadowCandidate:
    """A frozen tier-1 allow awaiting a post-hoc frontier shadow check.

    Stores everything the frontier needs to *replay* the action faithfully:
    raw action inputs (the frontier builds its own prompt), a routing snapshot
    (so the worker does not drift with the live manifest), and the frozen plan
    hash (the plan text itself is copied to the ``.plan.md`` sidecar).
    """

    schema_version: int
    captured_at: str
    cache_key: str

    # Raw action -- enough to reconstruct a full ActionContext (frontier replay input).
    origin: str
    event: str
    tool_name: str
    target_path: str | None
    new_content: str | None
    raw_diff: str | None
    action_fingerprint: str
    tool_args: dict[str, Any]
    repo_root: str
    session_name: str

    # Frozen plan (text copied to the `<hash>.plan.md` sidecar; hash recorded for provenance).
    plan_snapshot_hash: str
    plan_snapshot_file: str | None

    # Routing/config snapshot -- the worker rebuilds a SupervisorConfig from these, not the live manifest.
    resume_id: str | None
    direct: bool
    base_url: str | None
    proxy: str | None
    forge_root: str | None
    timeout_seconds: int
    fork_session: bool
    # Resolved replay lane (T1b): the shadow must replay on the SAME lane production uses, else it
    # audits the wrong frontier (a codex-configured session measured against the claude judge).
    # The v5 reader requires the complete frozen route; incomplete older records
    # finish unavailable instead of selecting a default backend.
    lane: LaneRecord
    auth_mode: str
    supervisor_model: str | None
    model_source: str
    supervisor_effort: str | None
    source_kind: str
    source_plan_path: str | None
    source_cwd: str

    # Audit + dimensions (so a later prompt/model change does not turn the history into mixed-quality mush).
    tier1_reason: str
    checker_provider: str | None
    checker_model: str | None
    checker_prompt_version: int
    checker_budget_tokens: int | None

    # Lifecycle (Slice 2 advances this and appends frontier_* fields).
    status: str = "pending"


def should_sample(config: SupervisorConfig, context: ActionContext, cache_key: str) -> bool:
    """Decide deterministically whether to shadow this tier-1 allow.

    No RNG: a stable hash of (seed, session, cache_key) buckets into [0, 1], so
    tests are reproducible and the decision never depends on global state. The
    rate bounds also clamp defensively (a hand-edited manifest cannot misbehave).
    """
    rate = config.shadow_sample_rate
    if rate <= 0.0:
        return False
    if rate >= 1.0:
        return True
    # cache_key already encodes action content + plan fingerprint + checker identity + budget, so the sampler can never
    # drift from what the cache considers "the same check"; session_name adds per-session independence.
    key = f"{config.shadow_seed or ''}|{context.session_name}|{cache_key}".encode()
    bucket = int(hashlib.sha256(key).hexdigest()[:8], 16) / 0xFFFFFFFF
    return bucket < rate


def candidate_hash(cache_key: str) -> str:
    """Content-addressed candidate id (stable per distinct tier-1 check)."""
    return make_content_hash(cache_key.encode())


def shadow_dir(config: SupervisorConfig, session_name: str) -> Path | None:
    """Absolute path to the session's shadow dir, or None if forge_root is unknown."""
    if not config.forge_root:
        return None
    return get_artifact_paths(Path(config.forge_root), session_name).shadow_abs


def count_existing_candidates(directory: Path) -> int:
    """Count distinct ``<hash>`` stems across all record states (pending/processing/done).

    Counting only ``*.json`` would undercount while a candidate is mid-``.processing``, letting identical content
    re-capture as a fresh pending file -- over-cap storage and duplicate frontier billing.
    """
    if not directory.is_dir():
        return 0
    stems: set[str] = set()
    for entry in directory.iterdir():
        name = entry.name
        for suffix in RECORD_SUFFIXES:
            if name.endswith(suffix):
                if suffix == ".done":
                    try:
                        record = json.loads(entry.read_text())
                        if record.get("review_state") == "unavailable" and "run_ok" not in record:
                            continue  # reconstruction failed before a model call
                    except (OSError, ValueError, AttributeError):
                        pass
                stems.add(name[: -len(suffix)])
                break
    return len(stems)


def has_pending_candidates(forge_root: str | None, session_name: str) -> bool:
    """True if the session has pending (``*.json``) shadow candidates awaiting a drain.

    The Stop hook's gate: only ``*.json`` (pending) records trigger a drain, since
    ``.processing``/``.done`` are already claimed/finished. Cheap directory glob with
    a fast no-op when the dir was never created (rate 0 stays fully inert).
    """
    if not forge_root:
        return False
    directory = get_artifact_paths(Path(forge_root), session_name).shadow_abs
    if not directory.is_dir():
        return False
    return any(directory.glob("*.json"))


def count_pending_candidates(forge_root: str | None, session_name: str) -> int:
    """Count pending (``*.json``) shadow candidates awaiting a drain.

    Unlike ``count_existing_candidates`` (which counts every lifecycle state for
    cap enforcement), this counts only un-claimed ``*.json`` records -- the
    "waiting to be audited" number a status view reports.
    """
    if not forge_root:
        return 0
    directory = get_artifact_paths(Path(forge_root), session_name).shadow_abs
    if not directory.is_dir():
        return 0
    return sum(1 for _ in directory.glob("*.json"))


def read_done_records(forge_root: str | None, session_name: str) -> list[dict[str, Any]]:
    """Load all finalized (``.done``) shadow records for a session, newest first.

    The read surface for ``forge policy shadow show``: each record carries its
    terminal ``status`` plus the frozen action and ``frontier_*`` verdict fields.
    Best-effort -- unreadable records are skipped, a missing dir yields ``[]``.
    """
    if not forge_root:
        return []
    directory = get_artifact_paths(Path(forge_root), session_name).shadow_abs
    if not directory.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for entry in sorted(directory.glob("*.done")):
        try:
            records.append(json.loads(entry.read_text()))
        except Exception:
            continue
    records.sort(key=lambda r: str(r.get("checked_at") or r.get("captured_at") or ""), reverse=True)
    return records


def _candidate_exists(directory: Path, cand_hash: str) -> bool:
    """True if a record for this hash exists in any lifecycle state."""
    return any((directory / f"{cand_hash}{suffix}").exists() for suffix in RECORD_SUFFIXES)


def capture_candidate(
    config: SupervisorConfig,
    context: ActionContext,
    *,
    cache_key: str,
    tier1_reason: str,
    checker_model: str,
    checker_provider: str | None,
    checker_budget_tokens: int,
    checker_prompt_version: int,
    lane_record: LaneRecord | None = None,
    snapshot: PlanSnapshot | None = None,
) -> Path | None:
    """Freeze a sampled tier-1 allow as a pending shadow candidate.

    Best-effort and cost-bounded: dedups against any existing record state,
    enforces ``shadow_max_per_session`` at capture time, creates the shadow dir
    lazily (only here, never in ``ensure_dirs``), copies the plan, and writes the
    pending ``<hash>.json``. Returns the candidate path, or None if skipped.
    """
    max_n = config.shadow_max_per_session
    if max_n <= 0:  # defensive: validation rejects < 1, but never trust a hand-edited manifest
        return None

    directory = shadow_dir(config, context.session_name)
    if directory is None:
        return None

    from forge.policy.semantic.identity import reviewer_cache_identity

    cand_hash = candidate_hash(cache_key + reviewer_cache_identity(config, lane_record))
    if _candidate_exists(directory, cand_hash):
        return None  # idempotent: already captured (in any state)
    if count_existing_candidates(directory) >= max_n:
        return None  # cap reached

    snapshot = snapshot or read_plan(config)
    if config.plan_override_path and snapshot.text is None:
        return None
    plan_snapshot_hash = snapshot.digest or ""
    plan_snapshot_file = None
    if snapshot.text is not None:
        plan_snapshot_file = f"{cand_hash}.plan.md"

    from forge.policy.semantic.supervisor import (
        _resolve_resume_target,
        resolve_supervisor_lane,
    )

    lane = resolve_supervisor_lane(lane_record)
    from forge.policy.semantic.identity import validate_reviewer

    validate_reviewer(config, LaneRecord(lane.runtime_id, lane.backend_id, lane.model))
    resolved = _resolve_resume_target(config.resume_id, config.forge_root) if config.resume_id else None
    if resolved is not None and resolved.warning:
        return None
    model, model_source = _freeze_model(
        config,
        lane.runtime_id,
        lane.model,
        resolved.resume_id if resolved else None,
        (resolved.source_cwd if resolved else None) or context.repo_root,
    )
    # A legacy lane's nominal opus default may differ from the restored model.
    # Freeze the model actually selected by that conversation for this audit.
    lane = replace(lane, model=model)
    directory.mkdir(parents=True, exist_ok=True)
    if plan_snapshot_file and snapshot.text is not None:
        (directory / plan_snapshot_file).write_bytes(snapshot.text.encode("utf-8"))
    candidate = ShadowCandidate(
        schema_version=SHADOW_SCHEMA_VERSION,
        captured_at=now_iso(),
        cache_key=cache_key,
        origin=context.origin,
        event=context.event,
        tool_name=context.tool_name,
        target_path=context.target_path,
        new_content=context.new_content,
        raw_diff=context.raw_diff,
        action_fingerprint=action_fingerprint(context),
        tool_args=context.tool_args,
        repo_root=context.repo_root,
        session_name=context.session_name,
        plan_snapshot_hash=plan_snapshot_hash,
        plan_snapshot_file=plan_snapshot_file,
        resume_id=resolved.resume_id if resolved else None,
        direct=config.direct,
        base_url=config.base_url,
        proxy=config.proxy,
        forge_root=config.forge_root,
        timeout_seconds=config.timeout_seconds,
        fork_session=config.fork_session,
        lane=LaneRecord(lane.runtime_id, lane.backend_id, lane.model),
        auth_mode=config.auth_mode,
        supervisor_model=model,
        model_source=model_source,
        supervisor_effort=config.supervisor_effort,
        source_kind="conversation+plan" if config.resume_id else "plan",
        source_plan_path=snapshot.path,
        source_cwd=(resolved.source_cwd if resolved else None) or context.repo_root,
        tier1_reason=tier1_reason,
        checker_provider=checker_provider,
        checker_model=checker_model,
        checker_prompt_version=checker_prompt_version,
        checker_budget_tokens=checker_budget_tokens,
    )

    out = directory / f"{cand_hash}.json"
    out.write_text(json.dumps(asdict(candidate), indent=2))
    _log.debug("Captured shadow candidate %s for session %s", cand_hash, context.session_name)
    return out


def _freeze_model(
    config: SupervisorConfig, runtime: str, lane_model: str, resume_id: str | None, cwd: str
) -> tuple[str, str]:
    if config.supervisor_model:
        return config.supervisor_model, "explicit"
    if runtime == "codex":
        return lane_model, "lane"
    from forge.core.reactive.env import build_claude_env
    from forge.core.reactive.reviewer_settings import inherited_auth_settings
    from forge.core.reactive.routing import resolve_subprocess_routing
    from forge.core.transcript import parse_jsonl_transcript, resolve_entry_role
    from forge.session.claude.paths import get_transcript_path

    base_url = (
        None
        if config.direct
        else resolve_subprocess_routing(
            explicit_base_url=config.base_url, explicit_proxy=config.proxy, require_route=False
        ).base_url
    )
    if base_url:
        return "opus", "proxy-tier"
    env = build_claude_env(direct=config.direct)
    inherited_auth_settings(env, cwd=cwd, direct=config.direct)
    model = env.get("ANTHROPIC_MODEL")
    source = "environment"
    if not model and resume_id:
        for entry in reversed(parse_jsonl_transcript(get_transcript_path(cwd, resume_id))):
            message = entry.get("message")
            if resolve_entry_role(entry) == "assistant" and isinstance(message, dict):
                value = message.get("model")
                if isinstance(value, str) and value.startswith("claude-"):
                    model, source = value, "conversation"
                    break
    if not model:
        raise ValueError(
            "Cannot freeze the legacy supervisor model; set an explicit supervisor --model before shadowing."
        )
    for tier in ("OPUS", "SONNET", "HAIKU"):
        if tier.lower() in model and env.get(f"ANTHROPIC_DEFAULT_{tier}_MODEL"):
            model, source = env[f"ANTHROPIC_DEFAULT_{tier}_MODEL"], "environment"
            break
    from forge.policy.semantic.identity import select_supervisor_lane

    return select_supervisor_lane(model=model).model, source
