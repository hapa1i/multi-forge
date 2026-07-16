"""Passport discovery and scan helpers for project memory docs.

Passports (YAML frontmatter in docs) select which docs the memory writer
should update. Session activation (``memory.auto_update.enabled``) decides
whether the writer runs. This module owns the scan that discovers passported
docs under configured roots when the detached memory writer runs.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from pathlib import Path

from forge.session.exceptions import PassportError
from forge.session.memory_inheritance import create_shadow_file
from forge.session.models import DesignatedDoc, SessionIntent, SessionState
from forge.session.passport import (
    Passport,
    check_writer_access,
    derive_shadow_path,
    read_passport,
    validate_okf_reserved_basenames,
)
from forge.session.validation import is_safe_designated_doc_path

logger = logging.getLogger(__name__)

DEFAULT_SCAN_ROOTS: tuple[str, ...] = ("docs/",)


# ---------------------------------------------------------------------------
# Passport discovery (detached-writer scan)
# ---------------------------------------------------------------------------

_SCAN_EXCLUDE_DIRS: frozenset[str] = frozenset({".git", "node_modules", "__pycache__", ".venv"})
_MEMORY_DIR_REL = ".forge/memory"
_MAX_SCANNED_DOCS = 50


def effective_scan_roots(roots: Sequence[str]) -> list[str]:
    """Return *roots* plus the always-on ``.forge/memory/`` dir, sorted.

    ``.forge/memory/`` holds shadow files and is always scanned even when
    roots are narrowed.
    """
    return sorted(set(roots) | {_MEMORY_DIR_REL})


def is_under_scan_roots(path: str, forge_root: Path, roots: Sequence[str]) -> bool:
    """Return True if *path* resolves under any effective scan root.

    Uses real path containment (resolve + ``is_relative_to``), not string
    prefixes, so ``docs-extra/x.md`` is not treated as under ``docs/``. Unsafe
    roots (absolute, escaping, or ``..``-traversal) are skipped to match
    :func:`scan_passported_docs`, which rejects them before scanning.
    """
    forge_root = forge_root.resolve()
    abs_path = (forge_root / path).resolve()
    for root in effective_scan_roots(roots):
        if _reject_unsafe_path(root, forge_root):
            continue
        root_dir = (forge_root / root).resolve()
        if abs_path == root_dir or abs_path.is_relative_to(root_dir):
            return True
    return False


def _is_excluded(rel_parts: tuple[str, ...]) -> bool:
    if any(part in _SCAN_EXCLUDE_DIRS for part in rel_parts):
        return True
    # Forge runtime trees never hold authored memory docs; .forge/memory/ is scanned.
    return len(rel_parts) >= 2 and rel_parts[0] == ".forge" and rel_parts[1] in {"sessions", "artifacts"}


def _reject_unsafe_path(path: str, forge_root: Path) -> str | None:
    """Return a rejection reason for an unsafe scan path, else None.

    Stricter than ``is_safe_designated_doc_path``: also rejects ``..``
    components that resolve back inside ``forge_root`` (e.g. ``docs/..`` would
    silently scan the whole repo). Scan roots and shadow write paths must stay
    clean and forge-root-relative. An explicit ``.`` root remains legal.
    """
    if ".." in Path(path).parts:
        return f"contains '..': {path}"
    resolved_root = forge_root.resolve()
    return is_safe_designated_doc_path(path, resolved_root, resolved_root)


def _reject_unsafe_shadow_path(path: str, forge_root: Path) -> str | None:
    """Reject unsafe or OKF-reserved logical/resolved shadow targets."""
    reason = _reject_unsafe_path(path, forge_root)
    if reason:
        return reason
    try:
        validate_okf_reserved_basenames(path, (forge_root / path).resolve())
    except PassportError as exc:
        return str(exc)
    return None


def is_memory_enabled(manifest: SessionState, effective: SessionIntent) -> bool:
    """Return True if the memory writer should run for this session.

    Checks incognito exclusion and effective ``auto_update.enabled``.
    Used by the Stop-hook enqueue gate and the detached memory-writer runner.
    """
    return (
        not manifest.is_incognito
        and effective.memory is not None
        and effective.memory.auto_update is not None
        and effective.memory.auto_update.enabled
    )


def _iter_candidate_markdown(forge_root: Path, roots: Sequence[str]) -> Iterator[str]:
    """Yield sorted, deduped, forge-root-relative POSIX paths for ``.md`` files.

    Shared walk logic for passport scanning. Validates roots, excludes
    VCS/build/runtime trees, rejects symlinks that escape the project.
    """
    valid_roots: list[str] = []
    for root in effective_scan_roots(roots):
        reason = _reject_unsafe_path(root, forge_root)
        if reason:
            logger.warning("Skipping unsafe scan root %r: %s", root, reason)
            continue
        valid_roots.append(root)

    seen: set[str] = set()
    candidates: list[str] = []
    for root in valid_roots:
        root_dir = forge_root / root
        if not root_dir.is_dir():
            continue
        for md in root_dir.rglob("*.md"):
            if not md.is_file():
                continue
            try:
                rel_path = md.relative_to(forge_root)
            except ValueError:
                continue
            if _is_excluded(rel_path.parts):
                continue
            if not md.resolve().is_relative_to(forge_root):
                continue
            rel = rel_path.as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            candidates.append(rel)
    candidates.sort()
    yield from candidates


def _build_scanned_doc(
    passport: Passport, official_rel: str, forge_root: Path, *, materialize: bool = True
) -> DesignatedDoc | None:
    if passport.update.mode != "shadow-only":
        return DesignatedDoc(path=official_rel, strategy=passport.update.strategy, shadows=None)

    shadow_path = passport.update.shadow_path or derive_shadow_path(official_rel)
    reason = _reject_unsafe_shadow_path(shadow_path, forge_root)
    if reason:
        logger.warning("Skipping shadow doc %s: unsafe shadow_path %r (%s)", official_rel, shadow_path, reason)
        return None
    if materialize:
        try:
            create_shadow_file(shadow_path, forge_root)
        except ValueError as e:
            logger.warning("Could not materialize shadow %s for %s: %s", shadow_path, official_rel, e)
            return None
    return DesignatedDoc(path=shadow_path, strategy=passport.update.strategy, shadows=official_rel)


def scan_passported_docs(forge_root: Path, roots: Sequence[str], session_name: str) -> list[DesignatedDoc]:
    """Scan configured roots for passported docs *session_name* may write.

    ``.forge/memory/`` is always scanned (shadow files live there). Root
    containment is validated, VCS/build/runtime trees are skipped, malformed
    passports are logged and skipped per file, writers are filtered, and the
    result is capped at 50 docs AFTER filtering so ordinary markdown cannot
    starve real memory docs. Returned paths are forge-root-relative.
    """
    forge_root = forge_root.resolve()
    docs: list[DesignatedDoc] = []
    for rel in _iter_candidate_markdown(forge_root, roots):
        try:
            passport = read_passport(forge_root / rel)
        except PassportError as e:
            logger.warning("Skipping doc with malformed passport %s: %s", rel, e)
            continue
        except OSError as e:
            logger.warning("Skipping unreadable doc %s: %s", rel, e)
            continue
        if passport is None:
            continue
        if not check_writer_access(passport.update.writers, session_name):
            continue
        doc = _build_scanned_doc(passport, rel, forge_root)
        if doc is None:
            continue
        docs.append(doc)
        if len(docs) >= _MAX_SCANNED_DOCS:
            logger.warning("Scan cap of %d reached; additional passported docs ignored", _MAX_SCANNED_DOCS)
            break
    return docs


def scan_all_passported_docs(forge_root: Path, roots: Sequence[str]) -> list[DesignatedDoc]:
    """Scan roots for ALL passported docs regardless of writer restrictions.

    Used by ``forge memory list`` for a project-level overview. Read-only:
    does not materialize shadow files (listing should not mutate the checkout).
    Uncapped -- hiding docs in a user-facing overview is confusing.
    """
    forge_root = forge_root.resolve()
    docs: list[DesignatedDoc] = []
    for rel in _iter_candidate_markdown(forge_root, roots):
        try:
            passport = read_passport(forge_root / rel)
        except PassportError as e:
            logger.warning("Skipping doc with malformed passport %s: %s", rel, e)
            continue
        except OSError as e:
            logger.warning("Skipping unreadable doc %s: %s", rel, e)
            continue
        if passport is None:
            continue
        doc = _build_scanned_doc(passport, rel, forge_root, materialize=False)
        if doc is None:
            continue
        docs.append(doc)
    return docs


def _iter_shadow_passports(forge_root: Path, roots: Sequence[str]) -> Iterator[tuple[str, str, str]]:
    """Yield ``(official_rel, shadow_path, strategy)`` for shadow-only passports.

    Lazy so callers that only need the first match (collision check) can
    short-circuit and skip the rest of the walk. Unlike :func:`scan_passported_docs`,
    this does NOT filter by writer and does NOT materialize shadow files.
    Malformed/unreadable passports and unsafe shadow paths are skipped (debug
    log). Paths are forge-root-relative.
    """
    forge_root = forge_root.resolve()
    for rel in _iter_candidate_markdown(forge_root, roots):
        try:
            passport = read_passport(forge_root / rel)
        except PassportError as e:
            logger.debug("Skipping malformed passport during shadow scan %s: %s", rel, e)
            continue
        except OSError as e:
            logger.debug("Skipping unreadable doc during shadow scan %s: %s", rel, e)
            continue
        if passport is None or passport.update.mode != "shadow-only":
            continue
        shadow_path = passport.update.shadow_path or derive_shadow_path(rel)
        if _reject_unsafe_shadow_path(shadow_path, forge_root):
            continue
        yield (rel, shadow_path, passport.update.strategy)


def scan_shadow_passports(forge_root: Path, roots: Sequence[str]) -> list[tuple[str, str, str]]:
    """Eagerly collect all shadow-only passports under *roots* (read-only).

    Full discovery for ``forge memory shadows list/show/review``. Uncapped --
    hiding valid shadows would be worse than the walk cost. For first-match
    needs (collision), use :func:`_iter_shadow_passports` directly.
    """
    return list(_iter_shadow_passports(forge_root, roots))


def check_shadow_path_collision_in_roots(
    shadow_path: str,
    official_path: str,
    forge_root: Path,
    roots: Sequence[str],
) -> str | None:
    """Detect a shadow-only passport that already claims *shadow_path*.

    Short-circuits on the first *different* official doc whose passport
    declares the same ``shadow_path``. Returns an actionable error message on
    collision, ``None`` when safe. Re-authoring the same official doc is not a
    collision. Malformed passports are skipped inside
    :func:`_iter_shadow_passports`, so an unrelated bad doc cannot block authoring.
    """
    for existing_official, existing_shadow, _ in _iter_shadow_passports(forge_root, roots):
        if existing_shadow != shadow_path:
            continue
        if existing_official == official_path:
            continue  # same official re-authored -- upsert, not collision
        return (
            f"Shadow path {shadow_path} is already used for {existing_official}. "
            "Use --shadow-path <path> to specify a different shadow path."
        )
    return None
