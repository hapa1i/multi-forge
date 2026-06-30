"""Memory writer for automatic memory doc updates.

The memory writer runs after session stop (via work queue) to update
designated project memory documents. It spawns ``claude -p`` as a headless
subprocess that reads the session transcript and writes updates to
configured designated docs.

Transfer context assembly (parent->child context for ``forge session
resume --fresh``) is in ``transfer.py`` -- a separate concept.

Supports two modes:
- **Direct update (Mode 1)**: Agent edits designated docs in-place.
- **Shadow/propose (Mode 2)**: Agent writes suggestions to a shadow file
  for human review, reading the official doc first for comparison.

Each run persists its stdout to
``<forge_root>/.forge/artifacts/<session>/handoff/review-<timestamp>.md`` so
users can inspect proposed/applied changes -- surfaced via
``forge session memory report``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from forge.core.lanes import Consumer, Lane
from forge.core.reactive.env import FORGE_COMMAND_VAR, FORGE_SESSION_VAR
from forge.core.reactive.routing import resolve_subprocess_routing
from forge.core.reactive.session_runner import run_claude_session
from forge.core.telemetry.upstream import UpstreamStatus, record_upstream_operation
from forge.core.transcript import parse_jsonl_transcript
from forge.session.claude.invoke import is_claude_available
from forge.session.exceptions import PassportError
from forge.session.models import DesignatedDoc, MemoryWriterConfig
from forge.session.passport import (
    Passport,
    ResolvedDocSpec,
    check_writer_access,
    read_passport,
    resolve_doc_spec,
    resolve_passport_source,
)
from forge.session.validation import is_safe_designated_doc_path

logger = logging.getLogger(__name__)


# Consumer-lane identity (epic consumer_lanes, T0). claude-max is the only non-default lane
# (claude_code runtime, subscription posture); backend_id is load-bearing for billing only --
# dispatch stays claude_code/run_claude_session.
MEMORY_WRITER_CONSUMER = Consumer(
    id="memory_writer",
    capability_floor="tool_agent",
    default_lane=Lane(runtime_id="claude_code", backend_id="anthropic-direct", model="opus"),
    allowed_lanes=(Lane(runtime_id="claude_code", backend_id="claude-max", model="opus"),),
)


def _default_timeout() -> int:
    from forge.runtime_config import get_runtime_config

    return get_runtime_config().memory_writer_timeout


def _record_memory_writer_outcome(
    session_name: str,
    status: UpstreamStatus,
    *,
    reason_code: str | None = None,
    message: str | None = None,
    run_id: str | None = None,
    parent_run_id: str | None = None,
    root_run_id: str | None = None,
    latency_ms: float | None = None,
) -> None:
    record_upstream_operation(
        command="memory-writer",
        operation="memory_writer.run",
        status=status,
        session=session_name,
        reason_code=reason_code,
        message=message,
        run_id=run_id,
        parent_run_id=parent_run_id,
        root_run_id=root_run_id,
        latency_ms=latency_ms,
    )


MULTI_DOC_PROMPT_TEMPLATE = """\
You are a project documentation agent. Your job is to update project documents \
based on a completed Claude Code session.

## Session Information
- Session name: {session_name}
- Transcript: {transcript_path}

## Instructions
1. Read the session transcript at `{transcript_path}`
2. For EACH file listed below, read the existing content first
3. {action_instruction}

IMPORTANT: Read each file BEFORE modifying it.
Only make the minimal edits described in each file's instructions below.
Do not duplicate, rephrase, or remove content beyond what the per-file instructions specify.
If everything is already documented for a file, skip it entirely.

## Files to Update
{file_sections}
"""

MULTI_DOC_AUGMENT_INSTRUCTION = "Apply the specified updates to each file"
MULTI_DOC_REVIEW_INSTRUCTION = "Print to stdout what changes you would make to each file. Do NOT modify any files."


def build_multi_doc_prompt(
    *,
    session_name: str,
    transcript_path: str,
    mode: str = "augment",
    docs: list[ResolvedDocSpec],
) -> str:
    """Build a multi-doc prompt for the memory writer.

    Generates a single prompt that instructs ``claude -p`` to update
    multiple designated documents with per-doc strategies. For shadow docs
    (``spec.official_path`` is set), the prompt instructs reading the
    official document first before proposing changes.

    Args:
        session_name: The Forge session name.
        transcript_path: Absolute path to the transcript artifact.
        mode: "augment" (write updates) or "review-only" (print suggestions).
        docs: Passport-resolved doc specs (no file I/O in this function).
    """
    action_instruction = MULTI_DOC_AUGMENT_INSTRUCTION if mode == "augment" else MULTI_DOC_REVIEW_INSTRUCTION

    sections: list[str] = []
    for spec in docs:
        lines: list[str] = []

        if spec.official_path:
            lines.append(f"### `{spec.write_path}` (proposes changes to `{spec.official_path}`)")
            lines.append(f"1. Read the OFFICIAL document at `{spec.official_path}` first.")
            lines.append(f"2. Read this shadow document at `{spec.write_path}` (if it exists).")
            lines.append(
                "3. Propose additions as `- [ ]` checkboxes, each with a brief rationale "
                "and source reference (session name, file changed, or context). "
                "Be liberal: include anything potentially useful that is not already in "
                "the official doc -- the human will review and promote selectively. "
                "Remove checkboxes whose content has been merged into the official "
                "document (self-prune). "
                "Do NOT duplicate suggestions already present in either file."
            )
        else:
            lines.append(f"### `{spec.write_path}`")

        if spec.intent:
            lines.append(f"**Purpose**: {spec.intent}")
        if spec.captures:
            lines.append(f"**Captures**: {', '.join(spec.captures)}")
        if spec.excludes:
            lines.append(f"**Excludes**: {', '.join(spec.excludes)}")
        if spec.approval == "human-promoted":
            lines.append("**Approval**: human-promoted -- propose only, do not make authoritative changes")
        if spec.custom_instruction:
            lines.append(spec.custom_instruction)
        lines.append(spec.strategy_instruction)
        if spec.compact_when:
            lines.append(f"**Compact when**: {spec.compact_when}")

        sections.append("\n".join(lines))

    file_sections = "\n\n".join(sections)

    return MULTI_DOC_PROMPT_TEMPLATE.format(
        session_name=session_name,
        transcript_path=transcript_path,
        action_instruction=action_instruction,
        file_sections=file_sections,
    )


def count_conversation_turns(transcript_path: Path) -> int:
    """Count user-initiated conversation turns in a transcript JSONL file.

    For newer format (requestId + message.role): counts unique requestId groups
    that contain at least one user message.
    For older format (type field): counts entries with type 'human'.

    Args:
        transcript_path: Path to the JSONL transcript file.

    Returns:
        Number of conversation turns. 0 if file is missing or empty.
    """
    entries = parse_jsonl_transcript(transcript_path)
    if not entries:
        return 0

    has_request_ids = any(e.get("requestId") for e in entries)

    if has_request_ids:
        user_request_ids: set[str] = set()
        for entry in entries:
            request_id = entry.get("requestId", "")
            if not request_id:
                continue
            message = entry.get("message", {})
            if isinstance(message, dict) and message.get("role") == "user":
                user_request_ids.add(request_id)
        return len(user_request_ids)

    return sum(1 for e in entries if e.get("type") == "human")


def resolve_writer_base_url(
    proxy_id: str | None,
    confirmed_proxy_base_url: str | None = None,
    env_base_url: str | None = None,
    *,
    direct: bool = False,
    subprocess_proxy: str | None = None,
) -> str | None:
    """Resolve ANTHROPIC_BASE_URL for the memory writer.

    When direct=True, short-circuits the entire chain and returns None
    (forces direct Anthropic routing regardless of session proxy).

    Delegates to ``resolve_subprocess_routing()`` with fail-open semantics.
    The writer's proxy_id is soft (preferred, not strict) because the writer
    is async/best-effort — using the session's confirmed proxy is better
    than failing.

    Priority chain (when not direct):
    1. proxy_id -> preferred_proxy (writer config, soft)
    2. subprocess_proxy -> persisted session subprocess proxy (soft)
    3. confirmed_proxy_base_url -> session's confirmed proxy
    4. env_base_url -> current ANTHROPIC_BASE_URL
    5. None -> Anthropic direct

    Args:
        proxy_id: Optional proxy from MemoryWriterConfig. Soft: falls through
            on miss (unlike workflow's strict --proxy).
        confirmed_proxy_base_url: Base URL from session's confirmed proxy.
        env_base_url: Fallback base URL from environment.
        direct: When True, force direct routing (skip all proxy resolution).
        subprocess_proxy: Session-level subprocess proxy intent.

    Returns:
        base_url string or None.
    """
    if direct:
        return None

    for candidate in (proxy_id, subprocess_proxy):
        if not candidate:
            continue
        result = resolve_subprocess_routing(
            preferred_proxy=candidate,
            require_route=False,
            use_environment=False,
        )

        if result.base_url:
            return result.base_url

    return confirmed_proxy_base_url or env_base_url


_PERMISSION_DENIED_PATTERNS = [
    re.compile(r"(?:need|require|don.t have).{0,30}(?:write|edit|permission)", re.IGNORECASE),
    re.compile(r"(?:not|isn.t|aren.t).{0,20}(?:allowed|permitted).{0,20}(?:write|edit|modify)", re.IGNORECASE),
    re.compile(r"cannot (?:write|edit|modify) files", re.IGNORECASE),
]


def _stdout_indicates_permission_denied(stdout: str) -> bool:
    """Detect permission-denied responses where Claude exits 0 but couldn't write."""
    if not stdout:
        return False
    # Only check the first ~2000 chars — permission messages appear early
    sample = stdout[:2000]
    return any(p.search(sample) for p in _PERMISSION_DENIED_PATTERNS)


def _validate_designated_docs(
    designated_docs: list[DesignatedDoc],
    forge_root: Path,
) -> list[DesignatedDoc]:
    """Validate and filter designated docs.

    Guards (per doc):
    1. Path safety: reject absolute, unsafe chars, traversal
       (applied to both ``path`` and ``shadows``).
    2. Empty shadows: reject ``shadows=""`` unconditionally.
    3. Self-shadow: reject when ``path == shadows``.

    Args:
        designated_docs: List of docs to validate.
        forge_root: Resolved worktree directory (base for path resolution).

    Returns:
        Filtered list containing only valid docs.
    """
    valid: list[DesignatedDoc] = []
    resolved_base = forge_root.resolve()
    for doc in designated_docs:
        reason = is_safe_designated_doc_path(doc.path, forge_root, resolved_base)
        if reason:
            logger.warning("Skipping designated_doc (%s): %s", doc.path, reason)
            continue

        if doc.shadows is not None and doc.shadows == "":
            logger.warning("Skipping designated_doc %s: 'shadows' must be non-empty", doc.path)
            continue

        if doc.shadows is not None:
            reason = is_safe_designated_doc_path(doc.shadows, forge_root, resolved_base)
            if reason:
                logger.warning("Skipping designated_doc shadows (%s): %s", doc.shadows, reason)
                continue

        if doc.shadows and doc.path == doc.shadows:
            logger.warning(
                "Skipping designated_doc %s: 'path' and 'shadows' must differ",
                doc.path,
            )
            continue

        valid.append(doc)
    return valid


def _dedupe_specs(specs: list[ResolvedDocSpec]) -> list[ResolvedDocSpec]:
    """Drop specs that resolve to the same ``(official_path, write_path)`` target.

    One doc can enter the run twice and resolve to the same write path — e.g. a
    session extra on a shadow-only-passported official plus the project scan's
    shadow entry both map to the doc's shadow file. Without this, the prompt
    gets duplicate sections and the agent can double-write. Keep the first.
    """
    deduped: list[ResolvedDocSpec] = []
    seen: set[tuple[str | None, str]] = set()
    for spec in specs:
        key = (spec.official_path, spec.write_path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(spec)
    return deduped


def run_memory_writer(
    *,
    session_name: str,
    forge_root: Path,
    transcript_snapshot_rel: str,
    config: MemoryWriterConfig,
    base_url: str | None = None,
    timeout_seconds: int | None = None,
    designated_docs: list[DesignatedDoc] | None = None,
    backend_id: str | None = None,
) -> bool:
    """Run the memory writer as a ``claude -p`` subprocess.

    This is the main entry point called by ``forge memory-writer run``.

    Args:
        session_name: Forge session name.
        forge_root: Forge project root (where .forge/ lives). Designated doc paths
                    resolve against this directory. Also used as cwd for the subprocess.
        transcript_snapshot_rel: Forge-root-relative path to transcript artifact.
        config: MemoryWriterConfig with mode, min_turns, proxy_id.
        base_url: Resolved ANTHROPIC_BASE_URL (or None for direct).
        timeout_seconds: Max seconds for the agent to run.
        designated_docs: List of docs to update. If None or empty, the agent
                         has nothing to do and returns True (skip).

    Returns:
        True if agent completed successfully (or skipped), False on error.
    """
    project_root = forge_root

    # Validate transcript path (system boundary: CLI args / marker payload)
    reason = is_safe_designated_doc_path(transcript_snapshot_rel, project_root, project_root.resolve())
    if reason:
        logger.warning("Memory writer: unsafe transcript path (%s)", reason)
        _record_memory_writer_outcome(session_name, "error", reason_code="unsafe_transcript_path", message=reason)
        return False
    transcript_abs = (project_root / transcript_snapshot_rel).resolve()

    if not transcript_abs.is_file():
        logger.warning("Memory writer: transcript not found at %s", transcript_abs)
        _record_memory_writer_outcome(
            session_name,
            "error",
            reason_code="transcript_not_found",
            message=str(transcript_abs),
        )
        return False

    turn_count = count_conversation_turns(transcript_abs)
    if turn_count < config.min_turns:
        logger.info(
            "Memory writer skipped: session %s had %d turns (min_turns=%d)",
            session_name,
            turn_count,
            config.min_turns,
        )
        _record_memory_writer_outcome(
            session_name,
            "skipped",
            reason_code="below_min_turns",
            message=f"{turn_count} turns < min_turns={config.min_turns}",
        )
        return True  # Not a failure — just below threshold

    _VALID_MODES = {"augment", "review-only"}
    if config.mode not in _VALID_MODES:
        logger.warning("Memory writer: unknown mode %r (expected %s)", config.mode, _VALID_MODES)
        _record_memory_writer_outcome(session_name, "error", reason_code="unknown_mode", message=config.mode)
        return False

    if not is_claude_available():
        logger.warning("Memory writer: claude CLI not found in PATH")
        _record_memory_writer_outcome(session_name, "error", reason_code="claude_unavailable")
        return False

    if not designated_docs:
        logger.info(
            "No designated_docs configured; memory writer has nothing to update (session %s)",
            session_name,
        )
        _record_memory_writer_outcome(session_name, "skipped", reason_code="no_designated_docs")
        return True

    safe_docs = _validate_designated_docs(designated_docs, forge_root)

    # Read passports and filter by writer authorization
    passport_resolved: list[tuple[DesignatedDoc, Passport | None]] = []
    for doc in safe_docs:
        passport_source = resolve_passport_source(doc)
        passport = None
        try:
            passport = read_passport(forge_root / passport_source)
        except FileNotFoundError:
            pass  # File doesn't exist yet; existence check happens below
        except PassportError as e:
            logger.warning("Skipping %s: malformed passport: %s", doc.path, e)
            continue

        if passport and not check_writer_access(passport.update.writers, session_name):
            logger.info(
                "Session %s not authorized for %s (writer: %s)",
                session_name,
                doc.path,
                passport.update.writers,
            )
            continue

        # Warn if shadow file has its own passport (official doc passport wins)
        if doc.shadows:
            try:
                shadow_passport = read_passport(forge_root / doc.path)
            except (FileNotFoundError, PassportError):
                shadow_passport = None
            if shadow_passport:
                logger.warning(
                    "Ignoring passport on shadow file %s (official doc %s passport is authoritative)",
                    doc.path,
                    doc.shadows,
                )

        passport_resolved.append((doc, passport))

    # Resolve effective doc specs and check file existence
    ready_specs: list[ResolvedDocSpec] = []
    for doc, passport in passport_resolved:
        spec = resolve_doc_spec(doc, passport)
        if not (forge_root / spec.write_path).is_file():
            logger.info("Skipping missing file: %s", spec.write_path)
            continue
        if spec.official_path and not (forge_root / spec.official_path).is_file():
            logger.info(
                "Skipping: official doc %s not found",
                spec.official_path,
            )
            continue
        ready_specs.append(spec)

    ready_specs = _dedupe_specs(ready_specs)

    if not ready_specs:
        logger.info(
            "No designated_docs ready after validation/existence checks (session %s)",
            session_name,
        )
        _record_memory_writer_outcome(session_name, "skipped", reason_code="no_ready_docs")
        return True

    prompt = build_multi_doc_prompt(
        session_name=session_name,
        transcript_path=str(transcript_abs),
        mode=config.mode,
        docs=ready_specs,
    )

    logger.info(
        "Running memory writer for session %s (mode=%s, turns=%d)",
        session_name,
        config.mode,
        turn_count,
    )

    # Use forge_root as cwd so designated doc paths (relative) resolve
    # against the correct branch content. Transcript path is absolute.
    from forge.core.reactive.cost_tracking import track_verb_cost
    from forge.core.usage import emit_usage_for_session_result

    effective_timeout = timeout_seconds if timeout_seconds is not None else _default_timeout()
    tracking_url = base_url

    with track_verb_cost("memory-writer", [tracking_url] if tracking_url else []) as cost:
        result = run_claude_session(
            prompt,
            base_url=base_url,
            direct=config.direct,
            timeout_seconds=effective_timeout,
            cwd=str(forge_root),
            # Group the writer's proxied requests under this session + role (Phase 1).
            extra_env={FORGE_SESSION_VAR: session_name, FORGE_COMMAND_VAR: "memory_writer"},
            reasoning_effort=config.effort,
        )

    # Attribute before the failure branch so failed runs are recorded too.
    emit_usage_for_session_result(
        result,
        command="memory-writer",
        cost=cost,
        session=session_name,
        base_url=base_url,
        direct=config.direct,
        backend_id=backend_id,
    )

    if not result.success:
        detail = result.error or (result.stderr[:500] if result.stderr else f"exit {result.returncode}")
        logger.warning("Memory writer for %s failed: %s", session_name, detail)
        reason_code = "timeout" if result.timed_out else f"exit_{result.returncode}"
        if result.error and not result.timed_out:
            reason_code = "subprocess_error"
        _record_memory_writer_outcome(
            session_name,
            "timeout" if result.timed_out else "error",
            reason_code=reason_code,
            message=detail,
            run_id=result.run_id,
            parent_run_id=result.parent_run_id,
            root_run_id=result.root_run_id,
            latency_ms=round(cost.duration_ms, 1) if cost.duration_ms is not None else None,
        )
        return False

    # Persist the agent's stdout to a per-session review file so users can
    # inspect what was proposed (review-only mode) or what was applied
    # (augment mode). The work-queue spawns this command detached with
    # stdout/stderr -> DEVNULL, so the file is the only visible artifact.
    try:
        _persist_review_report(
            forge_root=forge_root,
            session_name=session_name,
            mode=config.mode,
            turn_count=turn_count,
            stdout=result.stdout,
        )
    except OSError as e:
        # Best-effort: don't fail the agent if the review file can't be written
        logger.warning("Could not persist memory writer review file for %s: %s", session_name, e)

    # Only check for permission denial in augment mode. review-only mode
    # explicitly tells Claude "Do NOT modify any files", so a compliant
    # response like "I cannot modify files" is expected, not an error.
    if config.mode == "augment" and _stdout_indicates_permission_denied(result.stdout):
        logger.warning(
            "Memory writer for %s: Claude lacked Write/Edit permissions — no files modified. "
            "Run 'forge claude preset edit' to add Write/Edit to permissions.allow.",
            session_name,
        )
        _record_memory_writer_outcome(
            session_name,
            "error",
            reason_code="permission_denied",
            run_id=result.run_id,
            parent_run_id=result.parent_run_id,
            root_run_id=result.root_run_id,
            latency_ms=round(cost.duration_ms, 1) if cost.duration_ms is not None else None,
        )
        return False

    logger.info("Memory writer completed for session %s", session_name)
    _record_memory_writer_outcome(
        session_name,
        "success",
        run_id=result.run_id,
        parent_run_id=result.parent_run_id,
        root_run_id=result.root_run_id,
        latency_ms=round(cost.duration_ms, 1) if cost.duration_ms is not None else None,
    )
    return True


def memory_report_dir(forge_root: Path, session_name: str) -> Path:
    """Return the directory where memory writer review reports live."""
    # Path intentionally kept as …/handoff/ to avoid orphaning existing artifacts
    return forge_root / ".forge" / "artifacts" / session_name / "handoff"


def _persist_review_report(
    *,
    forge_root: Path,
    session_name: str,
    mode: str,
    turn_count: int,
    stdout: str,
) -> Path:
    """Write the agent's stdout to a timestamped review file.

    Returns the absolute path of the written file. The work queue spawns the
    agent detached so stdout/stderr go to DEVNULL; this file is the only way
    users can inspect what the agent proposed or applied. See
    ``forge session memory report``.
    """
    from datetime import datetime, timezone

    output_dir = memory_report_dir(forge_root, session_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S-%f")
    target = output_dir / f"review-{stamp}.md"

    header = (
        f"# Memory Writer Report -- {session_name}\n\n"
        f"**Mode**: {mode}\n"
        f"**Timestamp**: {now.isoformat()}\n"
        f"**Turns**: {turn_count}\n\n"
        "---\n\n"
    )
    target.write_text(header + (stdout or "_(no output)_\n"), encoding="utf-8")
    return target
