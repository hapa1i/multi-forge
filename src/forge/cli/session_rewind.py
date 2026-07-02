"""CLI helpers for the rewind resume strategy."""

from __future__ import annotations

import logging
import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path

from forge.core.state.io import atomic_write_text
from forge.session import SessionState, SessionStore
from forge.session.prev_sessions import child_path
from forge.session.rewind import (
    REWIND_CODE_DELTA_PRIVACY_WARNING_PREFIX,
    REWIND_CODE_DELTA_SCHEMA,
    RewindPrefixResult,
    generate_rewind_code_delta_context,
    write_rewind_transcript_prefix,
)
from forge.session.transfer import ResumeStrategy, _build_frontmatter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RewindLaunchArtifacts:
    """Prepared rewind artifacts for a native-style launch."""

    resume_id: str
    context_path: Path | None
    warnings: list[str]
    prefix_result: RewindPrefixResult | None
    rewind_relocated_session_id: str | None


def _persist_rewind_derivation(
    *,
    manifest: SessionState,
    parent_name: str,
    context_path: Path,
    requested_drop_last: int,
    rewind_relocated_session_id: str,
) -> SessionState:
    """Persist rewind-specific derivation details after artifacts are written."""
    worktree_path = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
    forge_root = Path(manifest.forge_root) if manifest.forge_root else worktree_path

    try:
        context_file = str(context_path.relative_to(forge_root))
    except ValueError:
        context_file = str(context_path)

    def _mutate(m: SessionState) -> None:
        if m.confirmed.derivation is None:
            from forge.session.models import Derivation

            m.confirmed.derivation = Derivation(parent_session=parent_name)
        m.confirmed.derivation.resume_mode = "native-relocate"
        m.confirmed.derivation.strategy = ResumeStrategy.REWIND.value
        m.confirmed.derivation.context_file = context_file
        m.confirmed.derivation.relocated_parent_session_id = None
        m.confirmed.derivation.dropped_turns = requested_drop_last
        m.confirmed.derivation.rewind_relocated_session_id = rewind_relocated_session_id

    return SessionStore(str(forge_root), manifest.name).update(timeout_s=5.0, mutate=_mutate)


def _prepare_rewind_launch_artifacts(
    *,
    manifest: SessionState,
    parent_name: str,
    parent_state: SessionState,
    parent_uuid: str,
    drop_last: int,
) -> RewindLaunchArtifacts:
    """Write a truncated native-resume transcript and its code-delta context."""
    from forge.session.claude.paths import (
        get_transcript_path,
        resolve_claude_project_root,
    )

    parent_project_root = parent_state.confirmed.claude_project_root or resolve_claude_project_root(parent_state)
    child_project_root = resolve_claude_project_root(manifest)
    source_path = get_transcript_path(parent_project_root, parent_uuid)
    if not source_path.is_file():
        return _plain_native_rewind_fallback(
            parent_uuid=parent_uuid,
            parent_project_root=parent_project_root,
            child_project_root=child_project_root,
            warning="Rewind could not find the parent transcript; falling back to plain native resume.",
        )

    rewind_uuid = str(_uuid.uuid4())
    dest_path = get_transcript_path(child_project_root, rewind_uuid)
    try:
        prefix_result = write_rewind_transcript_prefix(
            source_path=source_path,
            dest_path=dest_path,
            drop_last=drop_last,
        )
    except ValueError as exc:
        return _plain_native_rewind_fallback(
            parent_uuid=parent_uuid,
            parent_project_root=parent_project_root,
            child_project_root=child_project_root,
            warning=f"Rewind transcript prefix was not safe to write ({exc}); falling back to plain native resume.",
        )
    except OSError as exc:
        return _plain_native_rewind_fallback(
            parent_uuid=parent_uuid,
            parent_project_root=parent_project_root,
            child_project_root=child_project_root,
            warning=f"Rewind transcript prefix could not be written ({exc}); falling back to plain native resume.",
        )

    if prefix_result.kept_turns == 0:
        try:
            dest_path.unlink(missing_ok=True)
        except OSError:
            logger.debug("rewind empty-prefix cleanup failed", exc_info=True)
        return _plain_native_rewind_fallback(
            parent_uuid=parent_uuid,
            parent_project_root=parent_project_root,
            child_project_root=child_project_root,
            warning=(
                f"--drop-last {drop_last} would leave no resumable transcript turns; "
                "falling back to plain native resume."
            ),
        )

    warnings: list[str] = []
    if prefix_result.kept_turns < prefix_result.requested_keep_turns:
        extra_dropped = prefix_result.requested_keep_turns - prefix_result.kept_turns
        warnings.append(
            f"Safe rewind boundary dropped {extra_dropped} additional turn(s) "
            f"({prefix_result.actual_dropped_turns} total dropped)."
        )

    body, code_delta_warnings, schema_marker = generate_rewind_code_delta_context(
        parent_name=parent_name,
        lineage=[parent_name],
        transcript_path=source_path,
        kept_turns=prefix_result.kept_turns,
    )
    if schema_marker != REWIND_CODE_DELTA_SCHEMA:
        # The generator's compatibility body is useful for primitive callers,
        # but a launched rewind child must not rely on a degraded code delta.
        _remove_rewind_transcript(dest_path)
        fallback = _plain_native_rewind_fallback(
            parent_uuid=parent_uuid,
            parent_project_root=parent_project_root,
            child_project_root=child_project_root,
            warning="Rewind code-delta unavailable; falling back to plain native resume.",
        )
        privacy_warnings = [
            warning for warning in code_delta_warnings if warning.startswith(REWIND_CODE_DELTA_PRIVACY_WARNING_PREFIX)
        ]
        if not privacy_warnings:
            return fallback
        return RewindLaunchArtifacts(
            resume_id=fallback.resume_id,
            context_path=fallback.context_path,
            warnings=[*privacy_warnings, *fallback.warnings],
            prefix_result=fallback.prefix_result,
            rewind_relocated_session_id=fallback.rewind_relocated_session_id,
        )
    warnings.extend(code_delta_warnings)

    worktree_path = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
    forge_root = Path(manifest.forge_root) if manifest.forge_root else worktree_path
    context_path = child_path(forge_root, parent_name, manifest.name)
    content = (
        _build_frontmatter(
            parent_name=parent_name,
            strategy=ResumeStrategy.REWIND.value,
            schema=schema_marker,
            depth=1,
            lineage=[parent_name],
            transcript_artifact=None,
            token_estimate=None,
        )
        + body
    )
    atomic_write_text(context_path, content)

    updated = _persist_rewind_derivation(
        manifest=manifest,
        parent_name=parent_name,
        context_path=context_path,
        requested_drop_last=drop_last,
        rewind_relocated_session_id=rewind_uuid,
    )
    _preseed_rewind_project_root(manifest=updated, project_root=child_project_root)

    return RewindLaunchArtifacts(
        resume_id=rewind_uuid,
        context_path=context_path,
        warnings=warnings,
        prefix_result=prefix_result,
        rewind_relocated_session_id=rewind_uuid,
    )


def _preseed_rewind_project_root(*, manifest: SessionState, project_root: str) -> SessionState:
    """Persist the child Claude project root before hook reconciliation."""
    worktree_path = Path(manifest.worktree.path) if manifest.worktree else Path.cwd()
    forge_root = Path(manifest.forge_root) if manifest.forge_root else worktree_path

    return SessionStore(str(forge_root), manifest.name).update(
        timeout_s=5.0,
        mutate=lambda m: setattr(m.confirmed, "claude_project_root", project_root),
    )


def _remove_rewind_transcript(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.debug("rewind fallback transcript cleanup failed: %s", path, exc_info=True)


def _plain_native_rewind_fallback(
    *,
    parent_uuid: str,
    parent_project_root: str,
    child_project_root: str,
    warning: str,
) -> RewindLaunchArtifacts:
    warnings = [warning]
    warnings.extend(
        _relocate_parent_for_plain_native_fallback(
            session_id=parent_uuid,
            source_project_root=parent_project_root,
            dest_project_root=child_project_root,
        )
    )
    return RewindLaunchArtifacts(
        resume_id=parent_uuid,
        context_path=None,
        warnings=warnings,
        prefix_result=None,
        rewind_relocated_session_id=None,
    )


def _relocate_parent_for_plain_native_fallback(
    *,
    session_id: str,
    source_project_root: str,
    dest_project_root: str,
) -> list[str]:
    """Best-effort full transcript relocation for rewind fallback paths."""
    from forge.session.claude import RelocateSameDirError, relocate_transcript

    try:
        relocate_transcript(
            session_id=session_id,
            source_project_root=source_project_root,
            dest_project_root=dest_project_root,
        )
    except RelocateSameDirError:
        return []
    except OSError as exc:
        return [f"Plain native-relocate fallback could not copy the full parent transcript ({exc})"]
    return []
