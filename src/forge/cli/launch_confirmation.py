"""Post-launch confirmation writers for the session manifest.

Split from session_lifecycle.py (file-size compliance + shared ownership):
both ``session_lifecycle`` and ``session_fork`` record launch facts, so the
writers live in a neutral module instead of one importing the other.

These functions write to the *confirmed* half of the manifest after a launch:

- ``record_launch_confirmed`` -- routing + api-key posture into ``confirmed.launch``
- ``_infer_launch_confirmation`` -- Claude session UUID/transcript backfill

Both are best-effort: a missing or mid-run-deleted manifest must never break a
launch (status-line UX is non-critical).
"""

from __future__ import annotations

import logging

from forge.core.reactive.env import InteractiveApiKeyDecision
from forge.core.state import now_iso
from forge.session import SessionState, SessionStore
from forge.session.exceptions import SessionFileNotFoundError

logger = logging.getLogger(__name__)

# Shared surface: consumed by session_lifecycle and session_fork. The underscore
# helpers are module-internal by convention but imported by siblings, so they are
# named here to document the exported API.
__all__ = [
    "record_launch_confirmed",
    "_routing_mode_for",
    "_infer_launch_confirmation",
]


def record_launch_confirmed(
    store: SessionStore,
    *,
    routing_mode: str,
    proxy_id: str | None,
    base_url: str | None,
    decision: InteractiveApiKeyDecision,
) -> None:
    """Write immutable launch facts to ``confirmed.launch``.

    Centralized so every interactive entry point -- start, resume, the host fork
    closures, and sidecar -- records the same shape. ``decision`` is the child's
    api-key posture: host callers pass
    ``compute_interactive_api_key_decision(interactive=True)``; the sidecar caller
    builds it from the container env (the in-container child, not the host).
    """
    from forge.session.models import LaunchConfirmed

    launch = LaunchConfirmed(
        routing_mode=routing_mode,
        proxy_id=proxy_id,
        base_url=base_url,
        api_key_available_to_child=decision.available,
        api_key_source=decision.source,
    )
    try:
        store.update(timeout_s=5.0, mutate=lambda m: setattr(m.confirmed, "launch", launch))
    except Exception:
        # Best-effort status-line UX: a missing or locked manifest must not break the
        # launch (mirrors the claude_project_root preseed). The launch segment simply
        # won't render for this session.
        logger.debug("record_launch_confirmed: manifest update failed", exc_info=True)


def _routing_mode_for(base_url: str | None, proxy_id: str | None) -> str:
    """Classify how an interactive launch reaches the model, for launch metadata."""
    if not base_url:
        return "direct"
    return "proxy" if proxy_id else "custom_base_url"


def _infer_launch_confirmation(
    *,
    store: SessionStore,
    manifest: SessionState,
    session_id: str | None,
) -> None:
    """Backfill transcript/runtime confirmation after a successful host launch."""
    if session_id is None or manifest.confirmed.is_sandboxed:
        return

    try:
        from forge.session.claude.paths import (
            get_transcript_path,
            resolve_claude_project_root,
        )
    except ImportError:
        return

    # Prefer persisted launch root; fall back to computed root
    if manifest.confirmed.claude_project_root:
        transcript_path = get_transcript_path(manifest.confirmed.claude_project_root, session_id)
    else:
        transcript_path = get_transcript_path(resolve_claude_project_root(manifest), session_id)
    if not transcript_path.is_file():
        return

    def _mutate(state: SessionState) -> None:
        # 1:1 model: overwrite UUID directly (no accumulation)
        state.confirmed.claude_session_id = session_id
        state.confirmed.transcript_path = str(transcript_path)
        state.confirmed.confirmed_at = now_iso()
        if state.confirmed.confirmed_by is None:
            state.confirmed.confirmed_by = "cli:launch:inferred"

    # Preflight: if the session was deleted while Claude ran, skip the backfill.
    # Entering store.update() would make the lock layer recreate the session dir
    # to hold its lockfile (file_lock mkdir-parents), resurrecting a deleted
    # session as a lock-only directory.
    if not store.exists():
        logger.debug("Skipping launch confirmation: session %r manifest already removed", manifest.name)
        return

    try:
        store.update(timeout_s=5.0, mutate=_mutate)
    except SessionFileNotFoundError:
        # Deleted in the narrow window between the exists() check and the locked
        # read; degrade quietly (no traceback).
        logger.debug("Skipping launch confirmation: session %r manifest removed mid-run", manifest.name)
