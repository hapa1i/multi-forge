"""Staged-handoff files for Codex SessionStart hook delivery.

Path layout and atomic file helpers for the opt-in hook delivery path
(``--context-delivery hook``): the CLI stages the framed transfer body under the
session directory, the trust-enrolled ``forge hook codex-session-start`` handler
consumes it (writing a delivery receipt), and the CLI reconciles the receipt into
``confirmed.codex`` after the turn.

Layout::

    <forge_root>/.forge/sessions/<name>/codex/
    +-- pending-context.md     # staged handoff (one-shot; never survives the start turn)
    +-- context-receipt.json   # the hook's only write (the manifest stays CLI-owned)

The receipt is written BEFORE the pending file is unlinked and before the hook prints
its wire JSON: a delivered-but-unreceipted turn would make the CLI report
``hook_undelivered`` dishonestly, so the receipt errs toward existing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from forge.core.state import atomic_write_json, now_iso
from forge.core.state.io import atomic_write_text

logger = logging.getLogger(__name__)

HANDOFF_DIR = "codex"
PENDING_CONTEXT_FILENAME = "pending-context.md"
RECEIPT_FILENAME = "context-receipt.json"


@dataclass(frozen=True)
class DeliveryReceipt:
    """The hook's record of a delivered handoff (from the SessionStart payload)."""

    session_id: str  # Codex thread UUID (also the rollout filename suffix)
    transcript_path: str | None  # rollout path as reported by codex itself
    source: str | None  # SessionStart source: startup | resume | clear | compact
    delivered_at: str


def pending_context_path(session_dir: Path) -> Path:
    return session_dir / HANDOFF_DIR / PENDING_CONTEXT_FILENAME


def receipt_path(session_dir: Path) -> Path:
    return session_dir / HANDOFF_DIR / RECEIPT_FILENAME


def stage_pending_context(session_dir: Path, content: str) -> Path:
    """Stage the framed handoff body for the SessionStart hook to deliver."""
    path = pending_context_path(session_dir)
    atomic_write_text(path, content)
    return path


def clear_pending_context(session_dir: Path) -> bool:
    """Remove a staged handoff if present; return True when something was removed.

    Enforces the one-shot invariant: reconciliation clears an undelivered staging so a
    later enrolled resume turn can never late-deliver stale context mid-thread.
    """
    try:
        pending_context_path(session_dir).unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("Could not clear staged codex handoff: %s", exc)
        return False
    return True


def read_receipt(session_dir: Path) -> DeliveryReceipt | None:
    """Read the delivery receipt; None on missing or malformed (best-effort).

    The receipt is written by a hook subprocess (system boundary): a malformed file
    degrades to "no receipt" with a warning, which reconciliation reports as
    ``hook_undelivered``.
    """
    path = receipt_path(session_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Malformed codex delivery receipt at %s", path)
        return None
    if not isinstance(data, dict):
        logger.warning("Malformed codex delivery receipt at %s (not an object)", path)
        return None
    session_id = data.get("session_id")
    delivered_at = data.get("delivered_at")
    if not isinstance(session_id, str) or not session_id or not isinstance(delivered_at, str):
        logger.warning("Malformed codex delivery receipt at %s (missing fields)", path)
        return None
    transcript_path = data.get("transcript_path")
    source = data.get("source")
    return DeliveryReceipt(
        session_id=session_id,
        transcript_path=transcript_path if isinstance(transcript_path, str) else None,
        source=source if isinstance(source, str) else None,
        delivered_at=delivered_at,
    )


def consume_pending_context(
    session_dir: Path,
    *,
    session_id: str,
    transcript_path: str | None,
    source: str | None,
) -> str | None:
    """Read and consume the staged handoff, leaving a delivery receipt.

    Returns the staged content, or None when nothing is staged (the normal case for
    every turn except an opted-in start) or the receipt could not be written -- in the
    latter case the pending file is deliberately NOT consumed, so nothing is delivered
    that the receipt cannot vouch for.
    """
    pending = pending_context_path(session_dir)
    try:
        content = pending.read_text(encoding="utf-8")
    except OSError:
        return None
    receipt = DeliveryReceipt(
        session_id=session_id,
        transcript_path=transcript_path,
        source=source,
        delivered_at=now_iso(),
    )
    try:
        atomic_write_json(receipt_path(session_dir), asdict(receipt))
    except (OSError, TypeError) as exc:
        logger.warning("Could not write codex delivery receipt: %s", exc)
        return None
    try:
        pending.unlink()
    except OSError as exc:
        logger.warning("Could not remove consumed codex handoff: %s", exc)
    return content
