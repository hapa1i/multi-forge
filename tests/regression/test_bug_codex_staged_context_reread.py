"""Regression: a successful Codex hook delivery could leave stale staged context.

Bug: ``consume_pending_context`` returned the delivered content even when ``pending.unlink()``
failed, and the success reconciliation paths did not clear the staged file -> a later
``/clear``/``/compact``/resume could re-deliver stale context, violating the one-shot
invariant.

Fix: ``consume_pending_context`` empties the file if unlink fails (within-turn); the
delivered reconciliation branches clear it unconditionally as a backstop
(session/codex_handoff.py, core/ops/codex_session.py, core/ops/codex_interactive.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.core.ops.codex_session import CONTEXT_DELIVERY_HOOK, _reconcile_hook_delivery
from forge.core.state import atomic_write_json
from forge.session.codex_handoff import (
    consume_pending_context,
    pending_context_path,
    receipt_path,
    stage_pending_context,
)

pytestmark = pytest.mark.regression


def test_consume_empties_staged_file_when_unlink_fails(tmp_path, monkeypatch) -> None:
    session_dir = tmp_path
    stage_pending_context(session_dir, "STALE CONTEXT")
    pending = pending_context_path(session_dir)

    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if self == pending:
            raise OSError("cannot unlink")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    content = consume_pending_context(session_dir, session_id="t1", transcript_path=None, source="startup")

    assert content == "STALE CONTEXT"  # delivery still happened (receipt was written)
    # One-shot: the un-removable file is emptied, so a re-fired SessionStart can't re-deliver it.
    assert pending.exists()
    assert pending.read_text() == ""


def test_reconcile_clears_staged_file_on_delivery(tmp_path) -> None:
    session_dir = tmp_path
    stage_pending_context(session_dir, "ctx")
    # A delivered-but-not-removed staging: receipt present, pending survived (unlink failed).
    atomic_write_json(
        receipt_path(session_dir),
        {
            "session_id": "thread-1",
            "transcript_path": None,
            "source": "startup",
            "delivered_at": "2026-01-01T00:00:00Z",
        },
    )
    warnings: list[str] = []
    fact, tid, _rollout = _reconcile_hook_delivery(session_dir=session_dir, thread_id="thread-1", warnings=warnings)

    assert fact == CONTEXT_DELIVERY_HOOK
    assert tid == "thread-1"
    assert not pending_context_path(session_dir).exists()  # one-shot backstop cleared it
