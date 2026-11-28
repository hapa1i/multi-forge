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
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID

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


def find_rollouts_by_thread_id(thread_id: str, *, home: Path | None = None) -> list[Path]:
    """Return every rollout JSONL matching ``thread_id``.

    The glob is depth-bounded to the known ``sessions/YYYY/MM/DD/`` layout; an
    unreadable home degrades to an empty list.

    Returns all matches rather than one, so callers that must not guess -- notably
    adoption, which binds a session to whichever it picks -- can reject an
    ambiguous result instead of inheriting ``find_rollout_path``'s newest-wins
    tie-break.

    The glob only tests that the name *ends* with the id, so
    ``rollout-<ts>-not-the-thread-<wanted>.jsonl`` matches it. Every hit is
    therefore re-parsed and kept only when the parsed thread id equals the
    requested one -- the filename grammar, not the glob, decides identity.
    """
    if not thread_id:
        return []
    base = (home if home is not None else codex_home()) / "sessions"
    try:
        candidates = list(base.glob(f"*/*/*/rollout-*-{thread_id}.jsonl"))
    except OSError:
        return []
    return [
        p for p in candidates if (parsed := parse_rollout_filename(p)) is not None and parsed.thread_id == thread_id
    ]


@contextmanager
def directory_fd(path: Path) -> Iterator[int]:
    """Pin each directory component, including the owned home itself."""
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Expected an absolute native-store path")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def open_bound_rollout(thread: str, bound_path: str | None) -> Iterator[tuple[Path, BinaryIO, os.stat_result]]:
    """Open the unique bound rollout and verify that its contents stayed stable during the read."""
    UUID(thread)
    home = codex_home().expanduser().resolve(strict=True)
    if (home / "sessions").is_symlink():
        raise ValueError("the Codex sessions directory is a symbolic link")
    paths = find_rollouts_by_thread_id(thread, home=home)
    if len(paths) != 1 or (bound_path and paths[0] != Path(bound_path).resolve(strict=True)):
        raise ValueError("the bound rollout is missing or ambiguous")
    path = paths[0]
    with directory_fd(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise ValueError("the bound rollout is not an ordinary file")
            yield path, stream, before
            after = os.fstat(fd)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ValueError("the bound rollout changed during reconciliation")


def decode_rollout_row(line: bytes) -> tuple[str, dict[str, Any]]:
    if not line.endswith(b"\n"):
        raise ValueError("the native rollout is incomplete")
    row = json.loads(line)
    if not isinstance(row, dict) or not isinstance(row.get("payload"), dict) or not isinstance(row.get("type"), str):
        raise ValueError("unrecognized native rollout record")
    return row["type"], row["payload"]


def find_rollout_path(thread_id: str, *, home: Path | None = None) -> Path | None:
    """Return the rollout JSONL for ``thread_id``, or None when absent.

    A multi-match is uuid-improbable but resolved newest-mtime-wins; callers that
    cannot tolerate a guess should use ``find_rollouts_by_thread_id`` instead.
    Best-effort discovery -- callers record provenance only on a hit.
    """
    matches = find_rollouts_by_thread_id(thread_id, home=home)
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

    When ``cwd`` is given, a rollout with a known, mismatching head-line ``cwd`` is
    rejected if it is the only candidate. With multiple candidates, matching heads
    narrow the set; if no head matches, unreadable or unknown-shape heads keep the set
    ambiguous instead of eliminating the true rollout. Callers treat anything but
    exactly one result as ambiguous and refuse to guess.
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
    if cwd is not None and results:
        target = _canonical_path(cwd)
        heads = [(rollout, rollout_head_cwd(rollout.path)) for rollout in results]
        narrowed = [rollout for rollout, head in heads if head is not None and _canonical_path(head) == target]
        if narrowed:
            return narrowed
        # Rejection is deliberately lone-candidate-only: dropping known strangers from
        # a multi-candidate set could leave a lone unknown-head candidate that would
        # then be recorded -- a guess. Ambiguity must stay ambiguous.
        if len(results) == 1 and heads[0][1] is not None:
            return []
    return results


def rollout_head_cwd(path: Path) -> str | None:
    """Best-effort ``cwd`` from the rollout's first line (session metadata).

    The head shape is not pinned across codex versions, so this searches the first
    JSON object for a ``cwd`` string wherever it nests; any failure degrades to None
    (no narrowing) rather than guessing.
    """
    cwd, _ = rollout_head_route(path)
    return cwd


def rollout_head_route(path: Path) -> tuple[str | None, str | None]:
    """Read the launch directory and recorded provider from the same metadata row."""
    try:
        with path.open(encoding="utf-8") as fh:
            line = fh.readline(_HEAD_READ_LIMIT)
        record = json.loads(line)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(record, dict):
        return None, None
    payload = record.get("payload")
    provider = payload.get("model_provider") if isinstance(payload, dict) else None
    return _find_cwd(record, depth=0), provider if isinstance(provider, str) else None


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
