"""Codex rollout (session transcript) discovery (codex_frontend Phases 2 + 5).

Codex writes one rollout JSONL per thread at
``$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<ts>-<session_id>.jsonl``, where
``<session_id>`` equals the stream's ``thread.started.thread_id`` (binary-paired by
probe stage 61, codex-cli 0.138.0). Discovery is hook-free: Codex hooks only fire from
trust-enrolled homes, so the bridge CLI globs the filesystem instead of relying on a
SessionStart payload.

Two discovery directions:

- :func:`find_rollout_path` (Phase 2, headless): thread_id known from the JSONL
  stream; find its rollout file.
- :func:`find_rollouts_since` (Phase 5, interactive): the TUI owns stdout so there is
  no stream; find rollouts created after launch and read the thread_id FROM the
  filename.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Filename shape pinned by probe stage 61 / the Phase 4 payload fixture:
# rollout-2026-06-10T03-36-19-<thread_id>.jsonl. The timestamp prefix is strict; the
# id is captured opaquely (Phase 2's find_rollout_path also treats it as opaque).
_ROLLOUT_FILENAME_RE = re.compile(r"^rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-(.+)\.jsonl$")

# Allowance for clock-vs-filesystem timestamp granularity when filtering by mtime.
_MTIME_SKEW_SECONDS = 2.0

# Rollout head lines are small; bound the read so a corrupt multi-GB line can't stall
# best-effort discovery.
_HEAD_READ_LIMIT = 65536

_CWD_SEARCH_MAX_DEPTH = 4


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


@dataclass(frozen=True)
class DiscoveredRollout:
    """One rollout found by post-exit discovery; thread_id parsed from the filename."""

    thread_id: str
    path: Path


def parse_rollout_filename(path: Path) -> DiscoveredRollout | None:
    """Parse ``rollout-<ts>-<thread_id>.jsonl``; None when the name doesn't match."""
    match = _ROLLOUT_FILENAME_RE.match(path.name)
    if match is None:
        return None
    return DiscoveredRollout(thread_id=match.group(1), path=path)


def find_rollouts_since(
    since: datetime, *, cwd: str | None = None, home: Path | None = None
) -> list[DiscoveredRollout]:
    """Return rollouts created at/after ``since`` (newest mtime first).

    Post-exit discovery for interactive sessions (codex_frontend Phase 5): the TUI
    owns stdout, so the thread_id comes FROM the rollout filename instead of a
    ``thread.started`` stream event. Filtering is by **mtime** with a small skew
    allowance -- the filename timestamp's timezone is unpinned across codex versions.

    When ``cwd`` is given and more than one rollout qualifies, the set is narrowed to
    candidates whose head-line ``cwd`` matches. Narrowing applies only when it leaves
    at least one candidate: an unreadable or unknown-shape head must not eliminate the
    true rollout. Callers treat anything but exactly one result as ambiguous and
    refuse to guess.
    """
    base = (home if home is not None else codex_home()) / "sessions"
    cutoff = since.timestamp() - _MTIME_SKEW_SECONDS
    try:
        candidates = list(base.glob("*/*/*/rollout-*.jsonl"))
    except OSError:
        return []
    qualified: list[tuple[float, DiscoveredRollout]] = []
    for path in candidates:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            continue
        parsed = parse_rollout_filename(path)
        if parsed is None:
            continue
        qualified.append((mtime, parsed))
    qualified.sort(key=lambda item: item[0], reverse=True)
    results = [rollout for _, rollout in qualified]
    if cwd is not None and len(results) > 1:
        target = _canonical_path(cwd)
        narrowed = [r for r in results if _head_cwd_matches(r.path, target)]
        if narrowed:
            return narrowed
    return results


def _head_cwd_matches(path: Path, target: str) -> bool:
    head_cwd = _rollout_head_cwd(path)
    return head_cwd is not None and _canonical_path(head_cwd) == target


def _rollout_head_cwd(path: Path) -> str | None:
    """Best-effort ``cwd`` from the rollout's first line (session metadata).

    The head shape is not pinned across codex versions, so this searches the first
    JSON object for a ``cwd`` string wherever it nests; any failure degrades to None
    (no narrowing) rather than guessing.
    """
    try:
        with path.open(encoding="utf-8") as fh:
            line = fh.readline(_HEAD_READ_LIMIT)
    except OSError:
        return None
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(record, dict):
        return None
    return _find_cwd(record, depth=0)


def _find_cwd(node: dict[str, object], *, depth: int) -> str | None:
    if depth > _CWD_SEARCH_MAX_DEPTH:
        return None
    value = node.get("cwd")
    if isinstance(value, str) and value:
        return value
    for child in node.values():
        if isinstance(child, dict):
            found = _find_cwd(child, depth=depth + 1)
            if found is not None:
                return found
    return None


def _canonical_path(path_str: str) -> str:
    """Resolve symlinks for comparison (macOS /var -> /private/var); best-effort."""
    try:
        return str(Path(path_str).resolve())
    except OSError:
        return os.path.normpath(path_str)
