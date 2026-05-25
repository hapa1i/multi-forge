"""Project-scoped memory activation.

A checkout-local ``<forge_root>/.forge/memory.yaml`` declares whether the
handoff agent runs for *every* session in this checkout, instead of each
session re-declaring participation. ``memory_activation()`` is the single
resolver both gates consult (the Stop-hook enqueue site and the detached
``forge handoff run`` runner), so a project enable cannot be honored by one
gate and ignored by the other.

Authority split:
- passport frontmatter (in each doc) -> the doc's update contract
- this project config -> checkout-level activation consent
- session overrides -> sparse per-session toggles on top
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import dacite
import yaml

from forge.core.state.io import atomic_write_text
from forge.session.exceptions import PassportError, ProjectMemoryConfigError
from forge.session.memory_inheritance import create_shadow_file
from forge.session.models import DesignatedDoc, SessionState
from forge.session.passport import (
    Passport,
    check_writer_access,
    derive_shadow_path,
    read_passport,
)
from forge.session.validation import is_safe_designated_doc_path

logger = logging.getLogger(__name__)

_SUPPORTED_VERSIONS: frozenset[int] = frozenset({1})
PROJECT_MEMORY_FILENAME = "memory.yaml"
DEFAULT_SCAN_ROOTS: tuple[str, ...] = ("docs/",)


# ---------------------------------------------------------------------------
# Config model
# ---------------------------------------------------------------------------


@dataclass
class ProjectAutoUpdateConfig:
    """Checkout-level handoff activation settings."""

    enabled: bool = True
    mode: str = "augment"  # "augment" | "review-only"
    min_turns: int = 5
    proxy: str | None = None  # proxy_id for routing the handoff agent


@dataclass
class ProjectMemoryConfig:
    """``.forge/memory.yaml`` schema (v1).

    ``version`` is mandatory: durable state is a strict contract, not a
    best-effort optional config.
    """

    version: int
    auto_update: ProjectAutoUpdateConfig = field(default_factory=ProjectAutoUpdateConfig)
    roots: list[str] = field(default_factory=lambda: list(DEFAULT_SCAN_ROOTS))


def get_project_memory_path(forge_root: str | Path) -> Path:
    """Return ``<forge_root>/.forge/memory.yaml``."""
    return Path(forge_root) / ".forge" / PROJECT_MEMORY_FILENAME


# ---------------------------------------------------------------------------
# Config I/O (strict durable-state reader, modeled on SessionStore)
# ---------------------------------------------------------------------------


def read_project_memory_config(forge_root: Path) -> ProjectMemoryConfig | None:
    """Read project memory config; ``None`` if the file is absent.

    Raises:
        ProjectMemoryConfigError: malformed YAML, non-mapping document,
            unsupported version, or unknown keys. Stale/unknown durable
            state fails loud rather than degrading to an empty default.
    """
    path = get_project_memory_path(forge_root)
    if not path.is_file():
        return None

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ProjectMemoryConfigError(str(path), f"malformed YAML: {e}") from e
    except OSError as e:
        raise ProjectMemoryConfigError(str(path), f"read error: {e}") from e

    if not isinstance(raw, dict):
        raise ProjectMemoryConfigError(
            str(path),
            f"expected a mapping, got {type(raw).__name__}",
        )

    version = raw.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ProjectMemoryConfigError(
            str(path),
            f"version must be an integer (got {type(version).__name__})",
        )
    if version not in _SUPPORTED_VERSIONS:
        raise ProjectMemoryConfigError(
            str(path),
            f"unsupported version {version} (this Forge expects {sorted(_SUPPORTED_VERSIONS)}). "
            "Delete this file and run 'forge memory enable' to recreate it.",
        )

    try:
        return dacite.from_dict(
            data_class=ProjectMemoryConfig,
            data=raw,
            config=dacite.Config(strict=True),
        )
    except (dacite.DaciteError, TypeError, KeyError, ValueError) as e:
        raise ProjectMemoryConfigError(str(path), f"invalid config: {e}") from e


def write_project_memory_config(forge_root: Path, config: ProjectMemoryConfig) -> None:
    """Write project memory config atomically.

    Serializes via ``asdict`` + ``yaml.safe_dump`` so the file never carries
    Python object tags that ``safe_load`` would later reject.
    """
    path = get_project_memory_path(forge_root)
    content = yaml.safe_dump(asdict(config), sort_keys=False)
    atomic_write_text(path, content)


# ---------------------------------------------------------------------------
# Activation resolver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActivationConfig:
    """Resolved handoff activation for one session.

    A ``None`` return from :func:`memory_activation` means "do not run", so
    there is intentionally no ``enabled`` field here -- callers check
    ``activation is not None``.
    """

    mode: str
    min_turns: int
    proxy: str | None
    direct: bool
    needs_project_scan: bool  # scan passported docs across the checkout
    roots: tuple[str, ...]  # scan roots (project config or built-in default)


_UNSET: Any = object()


def _get_override_leaf(state: SessionState, leaf: str) -> Any:
    """Read ``overrides.memory.auto_update.<leaf>`` from the raw override dict.

    Returns the value if the key is present, ``_UNSET`` if absent. Overrides
    are the only truly sparse source: a leaf is present only when a user
    explicitly set it (e.g. ``memory.auto_update.enabled``), so absence means
    "inherit", never "False".
    """
    memory = state.overrides.get("memory")
    if not isinstance(memory, dict):
        return _UNSET
    auto_update = memory.get("auto_update")
    if not isinstance(auto_update, dict):
        return _UNSET
    if leaf not in auto_update:
        return _UNSET
    return auto_update[leaf]


def memory_activation(state: SessionState, forge_root: Path | str | None) -> ActivationConfig | None:
    """Resolve whether the handoff agent runs for *state*.

    Three tiers with different merge semantics:

    1. Project config (``.forge/memory.yaml``) -- baseline, whole block.
    2. Session intent (``intent.memory.auto_update`` when ``enabled is True``)
       -- legacy whole-session config. ``HandoffConfig`` defaults are
       indistinguishable from explicit values, so it overlays as one unit,
       never per-leaf.
    3. Session overrides (``overrides.memory.auto_update.<leaf>``) -- sparse
       per-leaf, the only source that can explicitly disable.

    Returns ``None`` when handoff must not run (incognito, or resolved
    ``enabled`` is not True).
    """
    if state.is_incognito:
        return None

    root = Path(forge_root) if forge_root is not None else None

    project_config: ProjectMemoryConfig | None = None
    if root is not None:
        project_config = read_project_memory_config(root)

    # Tier 1: project baseline (or built-in defaults).
    if project_config is not None:
        au = project_config.auto_update
        enabled = au.enabled
        mode = au.mode
        min_turns = au.min_turns
        proxy = au.proxy
    else:
        enabled = False
        mode = "augment"
        min_turns = 5
        proxy = None
    direct = False  # session-only; not a project-config concept

    # Tier 2: legacy intent overlay (whole block, only when enabled is True).
    intent_memory = state.intent.memory
    intent_au = intent_memory.auto_update if intent_memory is not None else None
    if intent_au is not None and intent_au.enabled is True:
        enabled = True
        mode = intent_au.mode
        min_turns = intent_au.min_turns
        proxy = intent_au.proxy
        direct = intent_au.direct

    # Tier 3: sparse overrides (per-leaf; can disable).
    ov_enabled = _get_override_leaf(state, "enabled")
    if ov_enabled is not _UNSET:
        enabled = bool(ov_enabled)
    ov_mode = _get_override_leaf(state, "mode")
    if ov_mode is not _UNSET:
        mode = ov_mode
    ov_min_turns = _get_override_leaf(state, "min_turns")
    if ov_min_turns is not _UNSET:
        min_turns = ov_min_turns
    ov_proxy = _get_override_leaf(state, "proxy")
    if ov_proxy is not _UNSET:
        proxy = ov_proxy
    ov_direct = _get_override_leaf(state, "direct")
    if ov_direct is not _UNSET:
        direct = bool(ov_direct)

    if enabled is not True:
        return None

    # Scanning is a project-config concept: a session that only tweaks
    # mode/proxy/min_turns must not suppress checkout-wide discovery.
    needs_project_scan = project_config is not None and project_config.auto_update.enabled is True
    roots = tuple(project_config.roots) if project_config is not None else DEFAULT_SCAN_ROOTS

    return ActivationConfig(
        mode=mode,
        min_turns=min_turns,
        proxy=proxy,
        direct=direct,
        needs_project_scan=needs_project_scan,
        roots=roots,
    )


# ---------------------------------------------------------------------------
# Passport discovery (Stop-time scan)
# ---------------------------------------------------------------------------

_SCAN_EXCLUDE_DIRS: frozenset[str] = frozenset({".git", "node_modules", "__pycache__", ".venv"})
_MEMORY_DIR_REL = ".forge/memory"
_MAX_SCANNED_DOCS = 50


def effective_scan_roots(roots: Sequence[str]) -> list[str]:
    """Return *roots* plus the always-on ``.forge/memory/`` dir, sorted.

    ``.forge/memory/`` holds shadow files and is always scanned even when a
    project config narrows ``roots``.
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


def _build_scanned_doc(passport: Passport, official_rel: str, forge_root: Path) -> DesignatedDoc | None:
    if passport.update.mode != "shadow-only":
        return DesignatedDoc(path=official_rel, strategy=passport.update.strategy, shadows=None)

    shadow_path = passport.update.shadow_path or derive_shadow_path(official_rel)
    reason = _reject_unsafe_path(shadow_path, forge_root)
    if reason:
        logger.warning("Skipping shadow doc %s: unsafe shadow_path %r (%s)", official_rel, shadow_path, reason)
        return None
    try:
        create_shadow_file(shadow_path, forge_root)
    except ValueError as e:  # defensive: _reject_unsafe_path already screened this
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

    valid_roots: list[str] = []
    for root in effective_scan_roots(roots):
        reason = _reject_unsafe_path(root, forge_root)
        if reason:
            logger.warning("Skipping unsafe scan root %r: %s", root, reason)
            continue
        valid_roots.append(root)

    # Collect forge-root-relative markdown paths deterministically. The path
    # string comes from the unresolved walk (preserving authored identity);
    # the symlink-escape check uses the resolved path.
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
                continue  # symlink escaping the project
            rel = rel_path.as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            candidates.append(rel)
    candidates.sort()

    docs: list[DesignatedDoc] = []
    for rel in candidates:
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


def _iter_shadow_passports(forge_root: Path, roots: Sequence[str]) -> Iterator[tuple[str, str, str]]:
    """Yield ``(official_rel, shadow_path, strategy)`` for shadow-only passports.

    Lazy so callers that only need the first match (collision check) can
    short-circuit and skip the rest of the walk. Unlike :func:`scan_passported_docs`,
    this does NOT filter by writer and does NOT materialize shadow files.
    Malformed/unreadable passports and unsafe shadow paths are skipped (debug
    log). Paths are forge-root-relative.
    """
    forge_root = forge_root.resolve()
    seen: set[str] = set()
    for root in effective_scan_roots(roots):
        if _reject_unsafe_path(root, forge_root):
            continue
        root_dir = forge_root / root
        if not root_dir.is_dir():
            continue
        for md in sorted(root_dir.rglob("*.md")):
            if not md.is_file():
                continue
            try:
                rel_path = md.relative_to(forge_root)
            except ValueError:
                continue
            if _is_excluded(rel_path.parts):
                continue
            if not md.resolve().is_relative_to(forge_root):
                continue  # symlink escaping the project
            rel = rel_path.as_posix()
            if rel in seen:
                continue
            seen.add(rel)
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
            if _reject_unsafe_path(shadow_path, forge_root):
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
            "Use --shadow <path> to specify a different shadow path."
        )
    return None
