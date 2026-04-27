"""Read-only queries about supervisor relationships and session policy state.

Used by both the CLI (``forge guard status``) and direct commands
(``%guard status``) to display supervisor metadata and discover
supervised sessions.
"""

from __future__ import annotations

import re

from forge.session import SessionStore
from forge.session.effective import compute_effective_intent
from forge.session.models import SessionState

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def read_scoped_supervisor_target(
    resume_id: str,
    supervisor_forge_root: str | None,
    fallback_forge_root: str | None,
) -> SessionState | None:
    """Return supervisor target state, preferring the supervisor's stored scope.

    Handles both session-name and raw-UUID resume_id values. UUIDs are
    resolved via the index's reverse lookup (find_session_by_uuid).
    """
    try:
        from forge.session.manager import SessionManager

        mgr = SessionManager()
        fr = supervisor_forge_root or fallback_forge_root

        # Try name-based lookup first (common case)
        if not _UUID_RE.fullmatch(resume_id):
            return mgr.get_session(resume_id, forge_root=fr)

        # UUID: reverse lookup through the index
        result = mgr.index_store.find_session_by_uuid(resume_id)
        if result is None:
            return None
        display_name, entry_fr = result
        return mgr.get_session(display_name, forge_root=entry_fr)
    except Exception:
        return None


def find_sessions_supervised_by(
    target_name: str,
    target_uuid: str | None,
    target_forge_root: str | None,
) -> list[str]:
    """Find repo-scoped sessions whose supervisor points to the target.

    Matches on session name or Claude UUID. Verifies forge_root alignment
    when set to prevent false matches from duplicate names across projects.
    Best-effort: skips broken manifests, never crashes.

    Cost: O(N) manifest reads where N = repo-scoped sessions. Acceptable
    for typical workflows (2-10 sessions per repo).
    """
    try:
        from forge.session.manager import SessionManager

        mgr = SessionManager()
        if not target_forge_root:
            return []
        project_root = mgr.resolve_project_root(target_forge_root)
        siblings = mgr.list_sessions(project_root_filter=project_root)
    except Exception:
        return []

    supervised: list[str] = []
    for sib_name, sib_entry in siblings:
        if sib_name == target_name:
            continue
        try:
            sib_store = SessionStore(sib_entry.forge_root or sib_entry.worktree_path, sib_name)
            sib_state = sib_store.read()
            effective = compute_effective_intent(sib_state)
            if not effective.policy or not effective.policy.supervisor:
                continue
            sup = effective.policy.supervisor
            if not sup.resume_id:
                continue
            matched = sup.resume_id == target_name or (target_uuid and sup.resume_id == target_uuid)
            if not matched:
                continue
            if sup.forge_root and target_forge_root and sup.forge_root != target_forge_root:
                continue
            supervised.append(sib_name)
        except Exception:
            continue

    return supervised
