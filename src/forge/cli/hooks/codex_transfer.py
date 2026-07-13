"""Codex SessionStart transfer delivery: the handler half of ``--context-delivery hook``.

The CLI stages a framed handoff under the session directory
(``forge.session.codex_handoff``); this module turns a Codex SessionStart hook payload
into the probe-pinned ``additionalContext`` wire JSON, consuming the staged file and
leaving a delivery receipt for the CLI to reconcile post-turn.

Deliberately manifest-free: the handler needs only ``store.session_dir`` (staged-file
presence picks the path -- staged turns deliver, nothing-staged turns record an
observation receipt for interactive thread capture), so it takes no manifest lock and
writes no manifest field. ``confirmed.codex`` stays CLI-written (design.md section
3.5); receipt files are the hooks' only writes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from forge.install.project_compat import diagnose_project_compatibility_for_hook
from forge.session.codex_handoff import (
    consume_pending_context,
    pending_context_path,
    write_observation_receipt,
)
from forge.session.hooks.session_start import resolve_session_store

logger = logging.getLogger(__name__)


def format_session_start_context(additional_context: str) -> str:
    """Build the strict SessionStart additionalContext wire JSON (single line).

    Key set and order are pinned by the probe response fixture
    ``scripts/experiments/codex-hooks/responses/sessionstart-additionalcontext.json``
    (30e PASSED: this shape lands in the model context headless from an enrolled home).
    Codex FAILS OPEN on malformed hook output, so this must stay a plain ``json.dumps``
    of a literal dict -- no extra keys, no pretty-printing.
    """
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": additional_context,
            }
        }
    )


def run_codex_session_start(data: dict[str, Any]) -> str | None:
    """Resolve the session, then deliver a staged handoff or record an observation.

    Returns None (silent: no stdout/stderr) on every non-delivery path: wrong event,
    missing session_id, no resolvable session, nothing staged. A user-scope
    registration fires this for every Codex session, so unrelated sessions must see no
    Forge noise. Nothing-staged turns in a *managed* session additionally write an
    observation receipt (Phase 5 interactive thread capture) -- still silent.
    Diagnostics log at debug (the hooks log, see ``forge.core.logging``). Never raises.
    """
    if data.get("hook_event_name") != "SessionStart":
        return None

    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None

    # The hook process's own CWD is unpinned; the payload's is authoritative (also for
    # forge_root derivation in session-store resolution) -- the codex-policy-check rule.
    payload_cwd = data.get("cwd")
    cwd = Path(payload_cwd).resolve() if isinstance(payload_cwd, str) and payload_cwd else Path.cwd().resolve()

    # Codex's payload session_id is a Codex thread UUID, never in the Claude UUID
    # index; FORGE_SESSION (probe-verified to reach the hook env) is the path.
    store = resolve_session_store(cwd, session_id=None)
    if store is None:
        logger.debug("Codex session-start: no session resolved")
        return None
    diagnose_project_compatibility_for_hook(
        store.forge_root,
        operation="codex-session-start",
    )

    transcript_path = data.get("transcript_path")
    source = data.get("source")
    safe_transcript = transcript_path if isinstance(transcript_path, str) else None
    safe_source = source if isinstance(source, str) else None

    # Branch on staged-file PRESENCE, not the consume return value: consume returns
    # None both for "nothing staged" and "staged but the delivery receipt could not
    # be written" -- the latter is a delivery failure and must NOT be recorded as a
    # nothing-staged observation.
    if not pending_context_path(store.session_dir).exists():
        try:
            write_observation_receipt(
                store.session_dir,
                session_id=session_id,
                transcript_path=safe_transcript,
                source=safe_source,
            )
        except Exception as e:  # Never break a codex turn over observation (fail open).
            logger.debug("Codex session-start: observation write failed: %s", e)
        return None

    try:
        content = consume_pending_context(
            store.session_dir,
            session_id=session_id,
            transcript_path=safe_transcript,
            source=safe_source,
        )
    except Exception as e:  # Never break a codex turn over delivery (fail open).
        logger.debug("Codex session-start: staged-context read failed: %s", e)
        return None
    if content is None:
        return None
    return format_session_start_context(content)
