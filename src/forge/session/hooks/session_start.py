"""SessionStart hook handler.

Claude Code invokes this hook with session info on stdin. The hook:
1. Resolves session name using env var / UUID lookup / directory scan
2. Updates manifest confirmed fields (claude_session_id, transcript_path, proxy)

1:1 model: UUID is overwritten on /compact or /clear (no accumulation).
Transcript rollover still captured before overwriting.

CRITICAL: Always exit 0 - don't break Claude on errors.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import cast
from urllib.parse import urlparse

from forge.core.state import (
    FileLockTimeoutError,
    now_iso,
)

from ..artifacts import get_artifact_paths, resolve_forge_root, safe_copy_file
from ..exceptions import SessionFileNotFoundError
from ..index import IndexStore
from ..models import SessionState, StartedWithProxy
from ..store import HOOK_LOCK_TIMEOUT_S, SessionStore
from .models import HookInput, HookResult, HookSource, ResolutionContext

logger = logging.getLogger(__name__)

# Proxy-related environment variable names
ENV_ACTIVE_TEMPLATE = "ACTIVE_TEMPLATE"
ENV_ANTHROPIC_BASE_URL = "ANTHROPIC_BASE_URL"

# Environment variable names
ENV_FORK_NAME = "FORGE_FORK_NAME"
ENV_SESSION = "FORGE_SESSION"
ENV_PARENT_SESSION = "FORGE_PARENT_SESSION"


def resolve_session_name(
    source: HookSource,
    session_id: str,
    cwd: Path,
    index_store: IndexStore | None = None,
) -> ResolutionContext:
    """Resolve session name using three-level fallback.

    Resolution order:
    1. FORGE_FORK_NAME env var (fork registration path)
    2. FORGE_SESSION env var (fast path for startup/resume from our CLI)
    3. IndexStore UUID reverse lookup (index-backed, fast)

    No CWD-based scan — FORGE_SESSION is the authoritative source.

    Args:
        source: What triggered the hook (for logging/debugging context).
        session_id: Claude's session UUID.
        cwd: Current working directory (worktree root).
        index_store: Optional IndexStore for UUID lookup (uses default if None).

    Returns:
        ResolutionContext with session_name and resolution_method if found.
    """
    ctx = ResolutionContext()

    # Prefer FORGE_FORGE_ROOT env var (set by CLI launcher for exact scope).
    # Fall back to CWD derivation if not set.
    env_forge_root = os.environ.get("FORGE_FORGE_ROOT")
    if env_forge_root:
        ctx.forge_root = env_forge_root
    else:
        try:
            from forge.core.ops.context import find_forge_root

            _cwd_forge_root = find_forge_root(cwd)
            if _cwd_forge_root:
                ctx.forge_root = str(_cwd_forge_root)
        except Exception:
            pass  # Fail-open: forge_root stays None

    # 1. Check FORGE_FORK_NAME (fork registration)
    fork_name = os.environ.get(ENV_FORK_NAME)
    if fork_name:
        ctx.session_name = fork_name
        ctx.resolution_method = "fork_env"
        return ctx

    # 2. Check FORGE_SESSION (fast path)
    session_name = os.environ.get(ENV_SESSION)
    if session_name:
        ctx.session_name = session_name
        ctx.resolution_method = "session_env"
        return ctx

    # 3. IndexStore UUID reverse lookup (index-backed, O(1) after parse)
    store = index_store or IndexStore()
    try:
        uuid_result = store.find_session_by_uuid(session_id, timeout_s=HOOK_LOCK_TIMEOUT_S)
    except FileLockTimeoutError:
        ctx.errors.append("Index lock contended (skipped UUID lookup)")
        uuid_result = None
    except Exception as e:
        # Logged broad catch: IndexStore can raise IndexCorruptedError, OSError,
        # KeyError, etc. Hook must degrade to directory scan, never crash.
        logger.debug("UUID lookup failed for %s: %s", session_id, e)
        uuid_result = None
    if uuid_result:
        ctx.session_name = uuid_result[0]  # display name
        ctx.forge_root = uuid_result[1]  # for scoped subsequent lookups
        ctx.resolution_method = "uuid_lookup"
        return ctx

    # No CWD scan — FORGE_SESSION env var is the authoritative source.
    ctx.errors.append(f"Could not resolve session name: no env vars, " f"UUID {session_id[:8]}... not in index")
    return ctx


def resolve_session_for_hook(
    cwd: Path,
    session_id: str | None = None,
) -> str | None:
    """Resolve session name for a hook invocation (fail-open).

    Resolution order:
    1. FORGE_FORK_NAME env var
    2. FORGE_SESSION env var
    3. IndexStore UUID reverse lookup (fast, index-backed)

    No CWD-based scan — FORGE_SESSION is the authoritative source.

    Returns:
        Session name if found, None otherwise (fail-open).
    """
    # 1. Check env vars
    fork_name = os.environ.get(ENV_FORK_NAME)
    if fork_name:
        return fork_name
    name = os.environ.get(ENV_SESSION)
    if name:
        return name

    # 2. IndexStore UUID lookup (fast path)
    if session_id:
        try:
            store = IndexStore()
            uuid_result = store.find_session_by_uuid(session_id, timeout_s=HOOK_LOCK_TIMEOUT_S)
            if uuid_result:
                return uuid_result[0]  # display name
        except Exception:
            pass  # Fail-open: index unavailable

    return None


def _resolve_store_root(name: str, cwd: Path, forge_root: str | None = None) -> str:
    """Resolve the manifest storage root for a session (fail-open).

    When forge_root is provided (from CWD or UUID resolution), use it
    directly. Otherwise fall back to index lookup or raw CWD.
    """
    if forge_root:
        return forge_root
    try:
        index = IndexStore()
        entry = index.get_session(name)
        return entry.forge_root or entry.worktree_path
    except Exception:
        return str(cwd)


def resolve_session_store(
    cwd: Path,
    session_id: str | None = None,
) -> SessionStore | None:
    """Resolve SessionStore for a hook invocation (fail-open).

    Uses the full resolution context (including forge_root) to find the
    correct manifest root. Returns None if session name cannot be determined.
    """
    name = resolve_session_for_hook(cwd, session_id=session_id)
    if not name:
        return None

    # Derive forge_root from env or CWD for scoped store root resolution
    forge_root = os.environ.get("FORGE_FORGE_ROOT")
    if not forge_root:
        try:
            from forge.core.ops.context import find_forge_root

            fr = find_forge_root(cwd)
            if fr:
                forge_root = str(fr)
        except Exception:
            pass

    store_root = _resolve_store_root(name, cwd, forge_root=forge_root)
    return SessionStore(store_root, name)


def _should_capture_started_with_proxy(base_url: str | None) -> bool:
    """Return True if we should capture started_with_proxy info.

    Any non-empty ANTHROPIC_BASE_URL indicates proxy usage, so capture proxy info.
    The previous localhost gating was overly restrictive (missed remote proxies,
    Docker hostnames, IPv6, etc.).
    """
    return bool(base_url)


def _parse_port(base_url: str) -> int | None:
    try:
        parsed = urlparse(base_url)
    except ValueError:
        return None

    if parsed.port is not None:
        return int(parsed.port)

    return None


def _resolve_env_value(*, cwd: Path, key: str) -> str | None:
    """Resolve an env var value. No forge.env fallback."""
    return os.environ.get(key) or None


def handle_session_start(
    hook_input: HookInput,
    cwd: Path,
    index_store: IndexStore | None = None,
) -> HookResult:
    """Handle SessionStart hook invocation.

    This is the main entry point called by the CLI command.

    Args:
        hook_input: Parsed hook input from Claude Code.
        cwd: Current working directory (worktree root).
        index_store: Optional IndexStore (uses default if None).

    Returns:
        HookResult with success status and session info.
    """
    result = HookResult(
        success=False,
        received_session_id=hook_input.session_id,
        received_transcript_path=hook_input.transcript_path,
        received_source=hook_input.source,
    )

    ctx = resolve_session_name(
        source=hook_input.source,
        session_id=hook_input.session_id,
        cwd=cwd,
        index_store=index_store,
    )

    if not ctx.resolved:
        result.error = "session_not_found"
        result.message = "; ".join(ctx.errors) if ctx.errors else "Could not resolve session name"
        return result

    session_name = ctx.session_name
    assert session_name is not None  # for type checker
    resolved_forge_root = ctx.forge_root  # May be None if resolved via env var

    result.session_name = session_name

    manifest_store = SessionStore(_resolve_store_root(session_name, cwd, resolved_forge_root), session_name)

    # Collect transcript rollover capture info under lock, but copy outside lock.
    rollover: tuple[str, str | None] | None = None  # (previous_session_id, previous_transcript_path)

    new_uuid = hook_input.session_id

    try:

        def _mutate(state: SessionState) -> None:
            nonlocal rollover

            # Verify state name matches resolved name.
            if state.name != session_name:
                raise ValueError(f"State name '{state.name}' != resolved name '{session_name}'")

            confirmed = state.confirmed

            current_uuid = confirmed.claude_session_id
            current_transcript_path = confirmed.transcript_path

            # Capture transcript pointer before overwriting UUID on compact/clear
            if hook_input.source in ("compact", "clear") and current_uuid and current_uuid != new_uuid:
                rollover = (str(current_uuid), current_transcript_path)

            # Diagnostic: detect pre-seed mismatch on startup
            if hook_input.source == "startup" and current_uuid and current_uuid != new_uuid:
                logger.warning(
                    "SessionStart: pre-seeded UUID mismatch " "(manifest=%s..., hook=%s...)",
                    current_uuid[:8],
                    new_uuid[:8],
                )

            # T7: a fresh process re-entry (startup/resume) is the natural retry boundary for the
            # codex subscription degrade -- the weekly quota may have refilled since it exhausted,
            # so clear the sticky marker and let the next supervisor check re-probe codex. Preserve
            # it on compact/clear: those fire mid-sitting, where the quota is unchanged and re-arming
            # codex would just exhaust and re-degrade (flap).
            if hook_input.source in ("startup", "resume"):
                from forge.policy.supervisor_lane_degrade import (
                    clear_supervisor_degrade,
                )

                clear_supervisor_degrade(state)

            # 1:1 model: overwrite UUID (no accumulation)
            confirmed.claude_session_id = new_uuid

            confirmed.transcript_path = hook_input.transcript_path
            confirmed.confirmed_at = now_iso()
            confirmed.confirmed_by = f"hook:SessionStart:{hook_input.source}"

            # Skip proxy capture for sidecar sessions (container-local
            # localhost:8085 is meaningless from host perspective)
            base_url = _resolve_env_value(cwd=cwd, key=ENV_ANTHROPIC_BASE_URL)
            if _should_capture_started_with_proxy(base_url) and not confirmed.is_sandboxed:
                template = _resolve_env_value(cwd=cwd, key=ENV_ACTIVE_TEMPLATE)
                proxy_id: str | None = None

                # Derive proxy_id from registry (current truth, not stale env)
                if base_url:
                    try:
                        from forge.proxy.proxies import ProxyRegistryStore

                        entry = ProxyRegistryStore().find_by_base_url(base_url)
                        if entry:
                            proxy_id = entry.proxy_id
                            if not template:
                                template = entry.template
                    except Exception:
                        pass  # Fail-open: registry unavailable

                if base_url:
                    confirmed.started_with_proxy = StartedWithProxy(
                        base_url=base_url,
                        proxy_id=proxy_id,
                        template=template,
                        port=_parse_port(base_url),
                    )

        manifest_store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_mutate)

    except FileLockTimeoutError:
        # Always fail-open: do not break Claude.
        print(
            "[forge] SessionStart: skipped manifest update (lock contention)",
            file=sys.stderr,
        )
        result.success = True
        result.message = "Skipped manifest update due to lock contention"
        result.error = "skip_lock_contended"
        return result

    except Exception as e:
        # Always fail-open: do not break Claude.
        msg = str(e)

        if "State name" in msg and "resolved name" in msg:
            result.error = "name_mismatch"
            result.message = msg
            return result

        if isinstance(e, SessionFileNotFoundError):
            result.error = "manifest_not_found"
            result.message = f"No manifest found for session '{session_name}' in {cwd}"
            return result

        result.error = "manifest_update_failed"
        result.message = f"Failed to update manifest: {e}"
        return result

    # Sync UUID to index and active registry (best-effort, non-critical).
    # Pass forge_root for scoped lookup to avoid updating the wrong project's entry.
    try:
        idx = index_store or IndexStore()
        idx.update_uuid(session_name, new_uuid, forge_root=resolved_forge_root)
    except Exception:
        pass  # Index sync is opportunistic; CLI commands also sync

    try:
        from forge.session.active import ActiveSessionStore

        ActiveSessionStore().update_uuid(session_name, new_uuid, forge_root=resolved_forge_root)
    except Exception:
        pass  # Runtime registry is best-effort; stale-pruning covers crashes

    # Best-effort capture of the prior transcript copy.
    if rollover is not None:
        previous_session_id, previous_transcript_path = rollover
        _capture_transcript_rollover(
            cwd=cwd,
            session_name=session_name,
            forge_root=resolved_forge_root,
            previous_session_id=previous_session_id,
            previous_transcript_path=previous_transcript_path,
        )

    result.success = True
    result.message = f"Session '{session_name}' reconciled via {ctx.resolution_method}"
    return result


def _capture_transcript_rollover(
    *,
    cwd: Path,
    session_name: str,
    forge_root: str | None,
    previous_session_id: str,
    previous_transcript_path: str | None,
) -> None:
    """Best-effort capture of a transcript before compact/clear rollover.

    This function must never raise (SessionStart hook must not break Claude).
    """

    if not previous_transcript_path:
        return

    try:
        project_root = Path(forge_root) if forge_root else resolve_forge_root(cwd)
        paths = get_artifact_paths(project_root, session_name)

        src = Path(previous_transcript_path)
        dst_abs = paths.transcripts_abs / f"{previous_session_id}.jsonl"
        dst_rel = paths.transcripts_rel / f"{previous_session_id}.jsonl"

        # Idempotent copy: skip if already captured.
        copied = safe_copy_file(src, dst_abs, overwrite=False)

        store = SessionStore(_resolve_store_root(session_name, cwd, forge_root), session_name)

        def _mutate(state: SessionState) -> None:
            artifacts = state.confirmed.artifacts
            transcripts = artifacts.get("transcripts")
            if isinstance(transcripts, list):
                for artifact in transcripts:
                    if not isinstance(artifact, dict):
                        continue
                    if artifact.get("session_id") == previous_session_id and artifact.get("copied_path") == str(
                        dst_rel
                    ):
                        return

            _append_artifact_entry(
                artifacts,
                kind="transcripts",
                entry={
                    "captured_at": now_iso(),
                    "reason": "rollover",
                    "source_path": previous_transcript_path,
                    "session_id": previous_session_id,
                    "copied_path": str(dst_rel),
                    "copied": copied,
                },
            )

        store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_mutate)
    except Exception as e:
        print(f"[forge] Transcript rollover failed: {e}", file=sys.stderr)


def _append_artifact_entry(
    confirmed_artifacts: dict[str, object],
    *,
    kind: str,
    entry: dict[str, object],
) -> None:
    """Append an artifact record under confirmed.artifacts in a stable shape."""
    items = confirmed_artifacts.get(kind)
    if items is None:
        confirmed_artifacts[kind] = [entry]
        return

    if not isinstance(items, list):
        confirmed_artifacts[kind] = [entry]
        return

    items.append(entry)


def parse_hook_input(data: dict[str, object]) -> HookInput | None:
    """Parse hook input from JSON dict.

    Args:
        data: Dict from JSON stdin.

    Returns:
        HookInput if valid, None if missing required fields.
    """
    session_id = data.get("session_id")
    transcript_path = data.get("transcript_path")
    source = data.get("source")

    if not session_id or not isinstance(session_id, str):
        return None
    if not transcript_path or not isinstance(transcript_path, str):
        return None
    if source not in ("startup", "resume", "compact", "clear"):
        return None

    return HookInput(
        session_id=session_id,
        transcript_path=transcript_path,
        source=cast(HookSource, source),
    )
