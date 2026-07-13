"""Shared session operations (command-core).

These operations are UI-agnostic and can be invoked from both:

- the CLI (`forge session ...`), and
- the in-chat direct command dispatcher (`%session ...`).

They return structured data and raise typed exceptions on failure.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge.core.state.exceptions import StateCorruptedError, StateUnreadableError
from forge.session import (
    ForgeSessionError,
    SessionIndexEntry,
    SessionManager,
    SessionState,
    SessionStore,
    clear_overrides,
    compute_effective_intent,
    delete_override,
    set_override,
)
from forge.session.active import ActiveSessionStore
from forge.session.artifacts import resolve_artifact_path
from forge.session.exceptions import (
    InvalidOverrideKeyError,
    InvalidOverrideValueError,
)
from forge.session.overrides import parse_value, validate_key

from .context import ExecutionContext

_log = logging.getLogger(__name__)


class ForgeOpError(RuntimeError):
    """Raised when a command-core operation fails."""


@dataclass(frozen=True)
class ListSessionsItem:
    name: str
    entry: SessionIndexEntry
    proxy_template: str | None
    model: str | None
    models: tuple[str, ...]
    is_active: bool


@dataclass(frozen=True)
class ListSessionsResult:
    sessions: list[ListSessionsItem]


VALID_SCOPES = {"workspace", "project", "all"}


def _scope_filters(ctx: ExecutionContext, scope: str) -> tuple[str | None, str | None]:
    """Compute (project_root_filter, forge_root_filter) for a given scope.

    Shared by list_sessions() and list_sessions_older_than() to ensure
    identical fallback behavior.
    """
    if scope == "workspace":
        return str(ctx.project_root), None
    if scope == "project":
        if ctx.forge_root is not None:
            return None, str(ctx.forge_root)
        _log.debug("No forge_root for --scope project, falling back to workspace scope")
        return str(ctx.project_root), None
    # scope == "all"
    return None, None


def list_sessions(*, ctx: ExecutionContext, include_incognito: bool, scope: str = "workspace") -> ListSessionsResult:
    """List sessions with lightweight derived metadata.

    Args:
        ctx: execution context (provides project_root and forge_root for filtering).
        include_incognito: whether to include incognito sessions.
        scope: filtering scope:
            - ``"workspace"``: sessions in the same workspace / logical repo (project_root match). Default.
            - ``"project"``: sessions in the same Forge project (forge_root match).
            - ``"all"``: no filtering (global).

    Returns:
        ListSessionsResult.

    Raises:
        ForgeOpError: if the session subsystem fails or scope is invalid.
    """
    if scope not in VALID_SCOPES:
        raise ForgeOpError(f"Invalid scope: {scope!r}. Must be one of {VALID_SCOPES}")

    _log.debug(
        "list_sessions: cwd=%s, project_root=%s, forge_root=%s, scope=%s",
        ctx.cwd,
        ctx.project_root,
        ctx.forge_root,
        scope,
    )

    manager = SessionManager()
    project_root_filter, forge_root_filter = _scope_filters(ctx, scope)

    try:
        sessions = manager.list_sessions(
            include_incognito=include_incognito,
            project_root_filter=project_root_filter,
            forge_root_filter=forge_root_filter,
        )
    except (StateCorruptedError, StateUnreadableError):
        raise  # corruption defers to the unified top-level handler (uniform reset tip)
    except ForgeSessionError as e:
        raise ForgeOpError(str(e)) from e

    active_store = ActiveSessionStore()

    items: list[ListSessionsItem] = []
    for name, entry in sessions:
        proxy_template: str | None = None
        model: str | None = None
        models: tuple[str, ...] = ()

        try:
            session_forge_root = entry.forge_root or entry.worktree_path
            manifest = manager.get_session(name, forge_root=session_forge_root)
            if manifest.intent.proxy:
                proxy_template = manifest.intent.proxy.template
            else:
                proxy_template = "direct"
                models = _direct_model_history(manifest, forge_root=Path(session_forge_root))
                model = _display_model_history(models)
        except ForgeSessionError as e:
            # Best-effort: listing should not fail if a manifest is missing/corrupt.
            _log.debug("Failed to read manifest for session %r: %s", name, e)

        is_active = False
        try:
            is_active = active_store.is_session_active(name, forge_root=entry.forge_root or entry.worktree_path)
        except Exception:
            # Best-effort: a runtime-registry probe failure must not fail the listing.
            _log.debug("Active-session liveness probe failed for %r", name, exc_info=True)

        items.append(
            ListSessionsItem(
                name=name,
                entry=entry,
                proxy_template=proxy_template,
                model=model,
                models=models,
                is_active=is_active,
            )
        )

    return ListSessionsResult(sessions=items)


def _display_model_history(models: tuple[str, ...]) -> str | None:
    if not models:
        return None
    return " -> ".join(models)


def _direct_model_history(manifest: SessionState, *, forge_root: Path) -> tuple[str, ...]:
    """Return observed direct-model transitions, falling back to the launch pin."""
    observed = _direct_model_history_from_transcript_artifacts(manifest, forge_root=forge_root)
    if observed:
        return observed

    if manifest.intent.launch and manifest.intent.launch.direct_model:
        return (manifest.intent.launch.direct_model,)
    return ()


def _direct_model_history_from_transcript_artifacts(manifest: SessionState, *, forge_root: Path) -> tuple[str, ...]:
    transcript_paths = _transcript_artifact_paths(manifest.confirmed.artifacts, forge_root=forge_root)
    if not transcript_paths:
        return ()

    models: list[str] = []
    for transcript_path in transcript_paths:
        try:
            with transcript_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    model = _extract_transcript_model(line)
                    if model is None:
                        continue
                    if not models or models[-1] != model:
                        models.append(model)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            _log.debug(
                "Failed to scan transcript artifact for model history: %s",
                transcript_path,
                exc_info=True,
            )

    return tuple(models)


def _transcript_artifact_paths(artifacts: dict[str, Any], *, forge_root: Path) -> list[Path]:
    raw_transcripts = artifacts.get("transcripts")
    if not isinstance(raw_transcripts, list):
        return []

    paths: list[Path] = []
    seen: set[str] = set()
    for item in raw_transcripts:
        if not isinstance(item, dict):
            continue
        stored_path = item.get("copied_path") or item.get("source_path")
        if not isinstance(stored_path, (str, Path)):
            continue
        resolved = resolve_artifact_path(forge_root, stored_path)
        if resolved is None:
            continue
        key = str(resolved.resolve())
        if key in seen:
            continue
        seen.add(key)
        paths.append(resolved)
    return paths


def _extract_transcript_model(line: str) -> str | None:
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return None

    if not isinstance(entry, dict):
        return None
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    model = message.get("model")
    if not isinstance(model, str):
        return None

    model = model.strip()
    if not model or model == "<synthetic>":
        return None
    return model


def list_sessions_older_than(
    *,
    ctx: ExecutionContext,
    older_than_days: int,
    include_incognito: bool = True,
    scope: str = "workspace",
) -> list[tuple[str, SessionIndexEntry]]:
    """List sessions whose last_accessed_at is older than the threshold.

    Entries with unparseable timestamps are excluded (they cannot be confirmed
    as old). This is a shared op used by both CLI and %session list.
    Respects the same scope filters as list_sessions().
    """
    from datetime import UTC, datetime

    from forge.core.state import parse_iso

    if scope not in VALID_SCOPES:
        raise ForgeOpError(f"Invalid scope: {scope!r}. Must be one of {VALID_SCOPES}")

    manager = SessionManager()
    project_root_filter, forge_root_filter = _scope_filters(ctx, scope)
    all_sessions = manager.list_sessions(
        include_incognito=include_incognito,
        project_root_filter=project_root_filter,
        forge_root_filter=forge_root_filter,
    )

    result: list[tuple[str, SessionIndexEntry]] = []
    for name, entry in all_sessions:
        try:
            dt = parse_iso(entry.last_accessed_at)
            age_days = (datetime.now(UTC) - dt).total_seconds() / 86400
        except (ValueError, TypeError, AttributeError):
            continue
        if age_days > older_than_days:
            result.append((name, entry))
    return result


# --- Session resolution ---


@dataclass(frozen=True)
class ResolveSessionResult:
    """Result of resolving a session by name or CWD."""

    store: SessionStore
    state: SessionState


def _enforce_session_mutation_compatibility(store: SessionStore) -> None:
    """Block a session mutation when its owning Forge root is incompatible."""
    from forge.install.project_compat import (
        ProjectCompatibilityError,
        enforce_project_compatibility,
    )

    try:
        enforce_project_compatibility(store.forge_root)
    except ProjectCompatibilityError as e:
        raise ForgeOpError(str(e)) from e


def resolve_session(*, ctx: ExecutionContext, session_name: str | None = None) -> ResolveSessionResult:
    """Resolve a session by explicit name or current session from CWD.

    Named sessions use workspace-wide two-tier resolution (current forge_root
    preference, then workspace-scoped scan). Unnamed falls back to $FORGE_SESSION.

    Args:
        ctx: execution context (provides forge_root for scoped resolution).
        session_name: explicit session name. If None, resolves current session.

    Returns:
        ResolveSessionResult with store and state.

    Raises:
        ForgeOpError: if no active session or session not found.
    """
    manager = SessionManager()

    try:
        if session_name:
            from forge.core.ops.resolution import resolve_session_repo_wide

            cwd_fr = str(ctx.forge_root) if ctx.forge_root else None
            resolved = resolve_session_repo_wide(session_name, cwd_fr, manager=manager)
            return ResolveSessionResult(store=resolved.store, state=resolved.state)
        else:
            env_name = os.environ.get("FORGE_SESSION")
            if env_name:
                store = manager.get_session_store(env_name)
                state = store.read()
            else:
                raise ForgeOpError("No session specified. Use --session <name> or run inside a Forge-managed session.")
    except (StateCorruptedError, StateUnreadableError):
        raise  # corruption defers to the unified top-level handler (uniform reset tip)
    except ForgeSessionError as e:
        raise ForgeOpError(str(e)) from e

    return ResolveSessionResult(store=store, state=state)


# --- Session override mutations ---


@dataclass(frozen=True)
class SetOverrideResult:
    """Result of setting a session override."""

    key: str
    value: Any


def set_session_override(
    *,
    ctx: ExecutionContext,
    session_name: str | None = None,
    key: str,
    value_str: str,
) -> SetOverrideResult:
    """Validate, apply, and persist a session override.

    Args:
        ctx: execution context.
        session_name: explicit session name. If None, resolves current session.
        key: dot-notation override key (e.g., "agent", "proxy.template").
        value_str: string value (parsed as JSON first, then as string).

    Returns:
        SetOverrideResult with key and parsed value.

    Raises:
        ForgeOpError: on invalid key, invalid value, validation failure, or IO error.
    """
    resolved = resolve_session(ctx=ctx, session_name=session_name)
    store = resolved.store
    _enforce_session_mutation_compatibility(store)

    try:
        # Validate key before acquiring lock (wildcards handled by set_override)
        if "*" not in key:
            validate_key(key)

        parsed_value = parse_value(value_str)

        # Apply + validate + persist atomically under lock.
        # The mutate callback receives the fresh state from disk, avoiding TOCTOU.
        def _mutate(m: SessionState) -> None:
            set_override(m.overrides, key, parsed_value)
            compute_effective_intent(m, strict=True, override_key=key)

        store.update(timeout_s=5.0, mutate=_mutate)

        return SetOverrideResult(key=key, value=parsed_value)

    except (InvalidOverrideKeyError, InvalidOverrideValueError) as e:
        raise ForgeOpError(str(e)) from e
    except (StateCorruptedError, StateUnreadableError):
        raise  # corruption defers to the unified top-level handler (uniform reset tip)
    except ForgeSessionError as e:
        raise ForgeOpError(str(e)) from e


@dataclass(frozen=True)
class ResetOverridesResult:
    """Result of resetting session overrides."""

    cleared_all: bool
    key: str | None  # None if cleared all
    was_present: bool  # whether the key had an override (or overrides existed)


def reset_session_overrides(
    *,
    ctx: ExecutionContext,
    session_name: str | None = None,
    key: str | None = None,
) -> ResetOverridesResult:
    """Delete a single override or clear all overrides.

    Args:
        ctx: execution context.
        session_name: explicit session name. If None, resolves current session.
        key: override key to delete. If None, clears all overrides.

    Returns:
        ResetOverridesResult.

    Raises:
        ForgeOpError: on invalid key or IO error.
    """
    resolved = resolve_session(ctx=ctx, session_name=session_name)
    store = resolved.store
    _enforce_session_mutation_compatibility(store)

    try:
        if key:
            # Mutate under lock: delete_override on fresh state
            result_holder: dict[str, Any] = {}

            def _mutate_delete(m: SessionState) -> None:
                result_holder["deleted"] = delete_override(m.overrides, key)

            store.update(timeout_s=5.0, mutate=_mutate_delete)
            return ResetOverridesResult(
                cleared_all=False,
                key=key,
                was_present=result_holder.get("deleted", False),
            )
        else:
            # Peek at current state to report whether overrides existed
            had_overrides = bool(resolved.state.overrides)
            if had_overrides:
                store.update(
                    timeout_s=5.0,
                    mutate=lambda m: clear_overrides(m.overrides),
                )
            return ResetOverridesResult(cleared_all=True, key=None, was_present=had_overrides)

    except InvalidOverrideKeyError as e:
        raise ForgeOpError(str(e)) from e
    except (StateCorruptedError, StateUnreadableError):
        raise  # corruption defers to the unified top-level handler (uniform reset tip)
    except ForgeSessionError as e:
        raise ForgeOpError(str(e)) from e
