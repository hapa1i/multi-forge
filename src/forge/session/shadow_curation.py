"""Shadow proposal curation: LLM-powered synthesis of shadow docs.

Collects shadow proposals across sessions, reads official + shadow content,
and produces a curated review report via ``run_claude_session()``.

Also owns shadow discovery (``collect_shadow_entries``), used by the
``forge memory shadows`` CLI commands.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from forge.core.lanes import Consumer, Lane, LaneError, resolve_lane
from forge.core.ops.context import ExecutionContext
from forge.core.telemetry.upstream import UpstreamStatus, record_upstream_operation
from forge.session.models import LaneRecord

logger = logging.getLogger(__name__)


# Consumer-lane identity (epic consumer_lanes, T0/T6b). Two non-default lanes: claude-max
# (claude_code runtime, subscription posture) and codex (the T6b dispatch arm). backend_id is
# load-bearing for billing only; model is nominal on the codex lane (codex picks its own model).
SHADOW_CURATION_CONSUMER = Consumer(
    id="shadow_curation",
    capability_floor="tool_agent",
    default_lane=Lane(runtime_id="claude_code", backend_id="anthropic-direct", model="opus"),
    allowed_lanes=(
        Lane(runtime_id="claude_code", backend_id="claude-max", model="opus"),
        Lane(runtime_id="codex", backend_id="chatgpt", model="gpt-5-codex"),
    ),
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ShadowEntry:
    """A shadow doc entry with source identity."""

    official: str
    shadow_path: str
    strategy: str
    session: str
    forge_root: str
    content: str = ""


@dataclass
class CurationResult:
    """Outcome of a curation run."""

    success: bool
    report_path: Path | None
    stdout: str
    # Actionable failure hint surfaced by the CLI (human + --json), e.g. a cold-codex-preflight
    # refresh hint (T6b). stdout stays the human-only zero-schema fallback; error is the carrier.
    error: str | None = None


# ---------------------------------------------------------------------------
# Shadow discovery (moved from CLI layer)
# ---------------------------------------------------------------------------


def collect_shadow_entries(
    *,
    ctx: ExecutionContext,
    scope: str,
    session_filter: str | None,
) -> tuple[list[ShadowEntry], set[str]]:
    """Collect shadow entries across sessions in *scope*.

    Returns (entries, scanned_roots). Each entry carries the forge_root
    for repo-scope deduplication and file reads.
    """
    from forge.core.ops.session import list_sessions

    result = list_sessions(ctx=ctx, include_incognito=False, scope=scope)
    entries: list[ShadowEntry] = []
    scanned_roots: set[str] = set()

    for item in result.sessions:
        if session_filter and item.name != session_filter:
            continue
        entry = item.entry
        fr = entry.forge_root or entry.worktree_path
        if not fr:
            continue
        scanned_roots.add(fr)

    # Shadow docs are discovered via passport scan, not session manifests.
    # Scan passported shadow docs under the scope-appropriate roots.
    # Skip when filtering to a named session: project shadows belong to no session.
    if session_filter is None:
        from forge.session.project_memory import (
            DEFAULT_SCAN_ROOTS,
            scan_shadow_passports,
        )

        roots_to_scan: set[str] = set()
        if scope == "project":
            if ctx.forge_root is not None:
                roots_to_scan.add(str(ctx.forge_root))
        else:
            roots_to_scan |= scanned_roots
            if ctx.forge_root is not None:
                roots_to_scan.add(str(ctx.forge_root))

        seen_keys = {(e.forge_root, e.shadow_path) for e in entries}
        for fr in sorted(roots_to_scan):
            fr_path = Path(fr)
            for official_rel, shadow_path, strategy in scan_shadow_passports(fr_path, DEFAULT_SCAN_ROOTS):
                key = (fr, shadow_path)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                scanned_roots.add(fr)
                entries.append(
                    ShadowEntry(
                        official=official_rel,
                        shadow_path=shadow_path,
                        strategy=strategy,
                        session="(project)",
                        forge_root=fr,
                    )
                )

    return entries, scanned_roots


# ---------------------------------------------------------------------------
# Curation prompt
# ---------------------------------------------------------------------------

_CURATION_TEMPLATE = """\
You are a documentation curation agent. Your job is to review shadow proposals \
against an official document and produce a structured synthesis.


## Official Document

**Path**: {official_path}

{official_block}

## Shadow Proposals

{shadow_sections}

## Instructions

Compare each shadow proposal against the official document. Produce exactly \
four sections:

### Promote

Genuinely new information worth adding to the official document.
Format each item as a checkbox with source citation:
`- [ ] <proposed addition> (source: <shadow_path>, session: <session>)`

### Already Present

Items that duplicate what the official document already says. One bullet each, brief.

### Conflicts

Items that contradict the official document. State both versions with paths.

### Discard

Noise, session-specific details, or speculative items not worth promoting.
One bullet each with brief rationale.

Do NOT modify any files. This is a read-only review."""


def _fenced_markdown_block(content: str) -> str:
    """Wrap content in a Markdown fence that cannot be closed by the content."""
    longest_backtick_run = max((len(m.group(0)) for m in re.finditer(r"`+", content)), default=0)
    fence = "`" * max(3, longest_backtick_run + 1)
    return f"{fence}\n{content}\n{fence}"


def build_curation_prompt(
    *,
    official_path: str,
    official_content: str,
    shadow_entries: list[ShadowEntry],
) -> str:
    """Build a self-contained curation prompt with inlined doc contents."""
    sections: list[str] = []
    for entry in shadow_entries:
        header = f"### {entry.shadow_path} (session: {entry.session}, root: {entry.forge_root})"
        body = entry.content.strip() if entry.content else "_(empty)_"
        sections.append(f"{header}\n\n{_fenced_markdown_block(body)}")

    shadow_text = "\n\n".join(sections) if sections else "_(no shadow proposals)_"

    return _CURATION_TEMPLATE.format(
        official_path=official_path,
        official_block=_fenced_markdown_block(official_content),
        shadow_sections=shadow_text,
    )


# ---------------------------------------------------------------------------
# Report persistence
# ---------------------------------------------------------------------------


def _doc_slug(official_path: str) -> str:
    """Derive a filename slug from an official doc path.

    Strips extension, replaces ``/`` with ``_``, strips leading dots/underscores,
    truncates to 60 chars. Appends a 6-char hash of the original path to prevent
    collisions (``a/b.md`` vs ``a_b.md`` vs truncation).
    """
    stem = re.sub(r"\.[^.]+$", "", official_path)
    slug = stem.replace("/", "_").replace("\\", "_")
    slug = slug.lstrip("._")
    slug = slug[:60]
    path_hash = hashlib.sha256(official_path.encode()).hexdigest()[:6]
    return f"{slug}-{path_hash}"


def curation_report_dir(forge_root: Path, session_name: str) -> Path:
    """Return ``.forge/artifacts/{session}/memory/``."""
    return forge_root / ".forge" / "artifacts" / session_name / "memory"


def persist_curation_report(
    *,
    forge_root: Path,
    session_name: str,
    official_path: str,
    scope: str,
    shadow_count: int,
    content: str,
) -> Path:
    """Write a timestamped curation report. Returns the path."""
    from datetime import datetime, timezone

    output_dir = curation_report_dir(forge_root, session_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S-%f")
    slug = _doc_slug(official_path)
    target = output_dir / f"curation-{slug}-{stamp}.md"

    header = (
        f"# Shadow Curation Report -- {session_name}\n\n"
        f"**Official doc**: {official_path}\n"
        f"**Timestamp**: {now.isoformat()}\n"
        f"**Shadow sources**: {shadow_count}\n"
        f"**Scope**: {scope}\n\n"
        "---\n\n"
    )
    target.write_text(header + (content or "_(no output)_\n"), encoding="utf-8")
    return target


def report_glob_pattern(official_path: str) -> str:
    """Return the glob pattern for ``--show-latest`` filtering by doc."""
    slug = _doc_slug(official_path)
    return f"curation-{slug}-*.md"


# ---------------------------------------------------------------------------
# Curation orchestrator
# ---------------------------------------------------------------------------


def run_shadow_curation(
    *,
    session_name: str,
    forge_root: Path,
    official_path: str,
    official_content: str,
    shadow_entries: list[ShadowEntry],
    base_url: str | None = None,
    direct: bool = False,
    timeout_seconds: int = 120,
    scope: str = "project",
    reasoning_effort: str | None = None,
    backend_id: str | None = None,
    lane_record: LaneRecord | None = None,
    on_dispatch: Callable[[], None] | None = None,
) -> CurationResult:
    """Build prompt, validate the bound lane, call the resolved runtime, persist report.

    The caller (CLI) resolves routing via ``resolve_writer_base_url()`` and passes ``base_url`` +
    ``direct``. ``reasoning_effort`` is the ``claude --effort`` level for the curation ``claude -p``
    run. ``lane_record`` is the consumer-lane binding (``read_bound_lane``, epic consumer_lanes T6b);
    it is validated against ``SHADOW_CURATION_CONSUMER``'s declared candidates and its runtime selects
    the dispatch arm: ``"claude_code"`` runs ``claude -p``; ``"codex"`` runs ``codex exec`` via
    ``_dispatch_codex_shadow_curation`` (read-only, blind/inlined prompt, fail-loud on a cold
    preflight). ``None`` resolves to the default (claude) lane; an invalid/drifted explicit binding
    fails loud. ``base_url``/``direct``/``reasoning_effort``/``backend_id`` are claude-arm-only.
    """
    from forge.core.reactive.cost_tracking import track_verb_cost
    from forge.core.reactive.session_runner import run_claude_session
    from forge.core.usage import emit_usage_for_session_result

    prompt = build_curation_prompt(
        official_path=official_path,
        official_content=official_content,
        shadow_entries=shadow_entries,
    )

    # Validate the bound lane against the consumer's declared candidates BEFORE selecting an arm
    # (mirrors the supervisor's LaneRecord -> Lane -> resolve_lane guard, supervisor.py). A
    # LaneRecord is Forge-owned durable state, so a stale/corrupt explicit binding -- a codex
    # runtime paired with a non-codex backend, or an unknown runtime -- must fail loud as a no-call,
    # never silently dispatch the wrong arm or degrade to claude. A None binding (no placement)
    # resolves to the default claude lane with no error.
    try:
        # Keyword args, not positional: the LaneRecord/Lane field-parity test guards names, not
        # constructor order (matches consumer_lanes._record_to_lane + the supervisor path).
        override = (
            None
            if lane_record is None
            else Lane(runtime_id=lane_record.runtime_id, backend_id=lane_record.backend_id, model=lane_record.model)
        )
        runtime_id = resolve_lane(SHADOW_CURATION_CONSUMER, override=override).runtime_id
    except LaneError as e:
        logger.warning("Shadow-curation lane binding invalid for %s (session %s): %s", official_path, session_name, e)
        return CurationResult(
            success=False,
            report_path=None,
            stdout="",
            error=(
                f"Shadow-curation is bound to an invalid lane: {e}. Re-pin it with "
                "'forge session lane set --consumer shadow_curation --runtime <claude_code|codex>' "
                "or clear it with 'forge session lane clear --consumer shadow_curation'."
            ),
        )

    # Runtime-keyed dispatch (epic consumer_lanes T6b): the codex arm is a self-contained early
    # return that owns its own preflight gate, freeze timing, and (auto) emission, so the claude
    # path below stays byte-identical to pre-T6b.
    if runtime_id == "codex":
        return _dispatch_codex_shadow_curation(
            prompt=prompt,
            session_name=session_name,
            forge_root=forge_root,
            official_path=official_path,
            scope=scope,
            shadow_count=len(shadow_entries),
            timeout_seconds=timeout_seconds,
            on_dispatch=on_dispatch,
        )

    tracking_urls = [base_url] if base_url else []

    # Committed to a claude -p dispatch -- notify the caller so the consumer-lane freeze
    # records only a lane that actually ran (epic consumer_lanes T6a).
    if on_dispatch is not None:
        on_dispatch()

    with track_verb_cost("curation", tracking_urls) as cost:
        result = run_claude_session(
            prompt,
            base_url=base_url,
            direct=direct,
            timeout_seconds=timeout_seconds,
            cwd=str(forge_root),
            reasoning_effort=reasoning_effort,
        )

    # Attribute before the failure branch so failed runs are recorded too.
    emit_usage_for_session_result(
        result,
        command="curation",
        cost=cost,
        session=session_name,
        base_url=base_url,
        direct=direct,
        backend_id=backend_id,
    )
    status: UpstreamStatus = "success" if result.success else "timeout" if result.timed_out else "error"
    reason_code = None
    if not result.success:
        reason_code = "timeout" if result.timed_out else f"exit_{result.returncode}"
        if result.error and not result.timed_out:
            reason_code = "subprocess_error"
    record_upstream_operation(
        command="curation",
        operation="memory.shadow_curation",
        status=status,
        session=session_name,
        run_id=getattr(result, "run_id", None),
        parent_run_id=getattr(result, "parent_run_id", None),
        root_run_id=getattr(result, "root_run_id", None),
        reason_code=reason_code,
        message=None if result.success else result.error or result.stderr[:200],
        latency_ms=round(cost.duration_ms, 1) if cost.duration_ms is not None else None,
    )

    if not result.success:
        logger.warning(
            "Curation failed for %s (session %s): rc=%s, error=%s",
            official_path,
            session_name,
            result.returncode,
            result.error or result.stderr[:200],
        )
        return CurationResult(success=False, report_path=None, stdout=result.stdout or "")

    report_path = persist_curation_report(
        forge_root=forge_root,
        session_name=session_name,
        official_path=official_path,
        scope=scope,
        shadow_count=len(shadow_entries),
        content=result.stdout,
    )

    logger.info("Curation report written to %s", report_path)
    return CurationResult(success=True, report_path=report_path, stdout=result.stdout)


def _dispatch_codex_shadow_curation(
    *,
    prompt: str,
    session_name: str,
    forge_root: Path,
    official_path: str,
    scope: str,
    shadow_count: int,
    timeout_seconds: int,
    on_dispatch: Callable[[], None] | None,
) -> CurationResult:
    """Run shadow curation on the codex-exec lane (epic consumer_lanes T6b).

    Mirrors ``_dispatch_codex_supervisor`` but maps codex failure into shadow-curation's
    **fail-loud** degrade (D3), not the supervisor's fail-open: this is a user-invoked consumer,
    so a cold/stale/unready preflight or a failed codex turn returns ``success=False`` with a
    CLI-visible refresh hint -- it never silently falls back to claude.

    Read-only sandbox: the curation prompt is self-contained (official + shadow content inlined),
    so codex needs no file access -- ``stdout`` IS the report. Preflight is read from the cache
    (``forge runtime preflight codex`` writes it); ``codex doctor`` is never spawned in this path.

    Emission: ``CodexHeadlessInvoker`` auto-emits the SOLE usage event AND the upstream row via
    the request's ``Attribution``. ``operation`` is pinned to ``"memory.shadow_curation"`` (not the
    ``Attribution`` default ``workflow.worker``, not ``None``) so that row matches the claude arm's
    ``record_upstream_operation``. Unlike the supervisor arm (``operation=None``, because its engine
    logs ``policy.evaluate``), shadow-curation has no engine row, so the invoker's row is its only
    one. This arm therefore must NOT call ``emit_usage_for_session_result`` -- that double-counts.

    Freeze: ``on_dispatch`` (the consumer-lane freeze) fires only *after* the preflight gate passes
    -- a cold-preflight skip-return never spawns codex, so per ``impl_notes`` (freeze only past
    every skip-return) it must not freeze. A turn that spawns and then fails still freezes, matching
    the claude arm where ``on_dispatch`` fires before the run regardless of outcome.
    """
    from forge.core.invoker.codex import CodexHeadlessInvoker, prepare_codex_request
    from forge.core.invoker.types import Attribution
    from forge.core.runtime.codex_preflight_cache import read_fresh_codex_preflight

    refresh_hint = "Run 'forge runtime preflight codex' to refresh."

    # Setup (preflight gate + request shaping). A failure here is a skip-return: codex never
    # spawns, so on_dispatch must NOT fire (no freeze of a lane that did not run).
    try:
        preflight = read_fresh_codex_preflight()
        if preflight is None or not preflight.ready:
            reason = (preflight.blocking_reason if preflight else None) or "no fresh preflight cached"
            return CurationResult(
                success=False,
                report_path=None,
                stdout="",
                error=f"Codex curation unavailable: {reason}. {refresh_hint}",
            )
        request = prepare_codex_request(
            prompt=prompt,
            preflight=preflight,
            attribution=Attribution(
                command="curation",
                session=session_name,
                operation="memory.shadow_curation",
            ),
            model=None,  # codex picks its own model; the lane's backend_id/model are nominal
            cwd=str(forge_root),  # parity with the claude arm; prompt is self-contained (read-only)
            sandbox="read-only",
            timeout_seconds=timeout_seconds,
            label="curation",
        )
    except Exception as e:  # cache read / request shaping failure -> fail loud, no spawn, no freeze
        logger.warning("Codex curation setup failed for %s (session %s): %s", official_path, session_name, e)
        return CurationResult(
            success=False,
            report_path=None,
            stdout="",
            error=f"Codex curation setup failed: {e}. {refresh_hint}",
        )

    # Past every skip-return: committed to a real codex dispatch -> freeze the lane now.
    if on_dispatch is not None:
        on_dispatch()

    result = CodexHeadlessInvoker().run(request)

    # HeadlessResult.success is returncode-only; fold runtime_is_error so an exit-0-but-failed turn
    # (codex reported an in-stream error) fails loud instead of persisting an empty report.
    if not result.success or result.runtime_is_error:
        reason = result.error or (result.stderr.strip()[:200] if result.stderr.strip() else "codex turn failed")
        logger.warning("Codex curation failed for %s (session %s): %s", official_path, session_name, reason)
        return CurationResult(
            success=False,
            report_path=None,
            stdout=result.stdout or "",
            error=f"Codex curation failed: {reason}",
        )

    report_path = persist_curation_report(
        forge_root=forge_root,
        session_name=session_name,
        official_path=official_path,
        scope=scope,
        shadow_count=shadow_count,
        content=result.stdout,
    )
    logger.info("Codex curation report written to %s", report_path)
    return CurationResult(success=True, report_path=report_path, stdout=result.stdout)
