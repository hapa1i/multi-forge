"""Codex rollout (session transcript) discovery (codex_frontend Phase 2).

Codex writes one rollout JSONL per thread at
``$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<ts>-<session_id>.jsonl``, where
``<session_id>`` equals the stream's ``thread.started.thread_id`` (binary-paired by
probe stage 61, codex-cli 0.138.0). Discovery is hook-free: Codex hooks only fire from
trust-enrolled homes, so the bridge CLI globs the filesystem instead of relying on a
SessionStart payload.
"""

from __future__ import annotations

import os
from pathlib import Path


def codex_home() -> Path:
    """Return ``$CODEX_HOME`` (else ``~/.codex``) -- the directory codex-cli owns."""
    env_home = os.environ.get("CODEX_HOME")
    return Path(env_home) if env_home else Path.home() / ".codex"


def find_rollout_path(thread_id: str, *, home: Path | None = None) -> Path | None:
    """Return the rollout JSONL for ``thread_id``, or None when absent.

    The glob is depth-bounded to the known ``sessions/YYYY/MM/DD/`` layout. A
    multi-match is uuid-improbable but resolved newest-mtime-wins; an unreadable
    home degrades to None (best-effort discovery -- callers record provenance
    only on a hit).
    """
    if not thread_id:
        return None
    base = (home if home is not None else codex_home()) / "sessions"
    try:
        matches = list(base.glob(f"*/*/*/rollout-*-{thread_id}.jsonl"))
    except OSError:
        return None
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    return max(matches, key=_mtime)
