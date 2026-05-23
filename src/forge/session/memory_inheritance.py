"""Memory doc inheritance for fork and resume --fresh.

Handles selective inheritance of designated memory docs when deriving child
sessions. Reads passports once, filters by mode/passport/writer, assigns
the child's memory intent, and provides shadow file materialization for
cross-worktree forks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .exceptions import PassportError
from .models import DesignatedDoc, SessionState
from .passport import Passport, check_writer_access, read_passport, resolve_passport_source
from .validation import is_safe_designated_doc_path

logger = logging.getLogger(__name__)


class InheritMemoryMode(str, Enum):
    ALL = "all"
    NONE = "none"
    SHADOWED = "shadowed"


@dataclass
class InheritanceDoc:
    """Single-read resolved doc info for inheritance decisions."""

    doc: DesignatedDoc
    passport: Passport | None
    is_shadow: bool
    shadow_path: str | None
    writer_spec: str
    inherit_on_fork: bool


def create_shadow_file(shadow_path: str, forge_root: Path) -> bool:
    """Create a shadow file under ``.forge/memory/`` if it doesn't exist.

    Returns True if created. Returns False for paths outside ``.forge/memory/``.
    Raises ValueError on unsafe paths.
    """
    resolved_base = forge_root.resolve()
    reason = is_safe_designated_doc_path(shadow_path, forge_root, resolved_base)
    if reason:
        raise ValueError(f"unsafe shadow path: {reason}")
    abs_shadow = (forge_root / shadow_path).resolve()
    if not abs_shadow.is_relative_to(resolved_base / ".forge" / "memory"):
        return False
    if abs_shadow.is_file():
        return False
    abs_shadow.parent.mkdir(parents=True, exist_ok=True)
    abs_shadow.write_text("", encoding="utf-8")
    return True


def _resolve_inheritance_docs(
    docs: list[DesignatedDoc],
    parent_forge_root: Path,
) -> tuple[list[InheritanceDoc], list[str]]:
    """Read each doc's passport once and build resolved inheritance info.

    Returns (resolved_docs, warnings). Malformed passports default to
    inherit_on_fork=True (fail open) with a warning.
    """
    resolved: list[InheritanceDoc] = []
    warnings: list[str] = []
    resolved_base = parent_forge_root.resolve()

    for doc in docs:
        passport: Passport | None = None
        passport_source = resolve_passport_source(doc)
        passport_path = parent_forge_root / passport_source

        try:
            passport = read_passport(passport_path)
        except FileNotFoundError:
            pass
        except PassportError as e:
            warnings.append(
                f"Malformed passport for {passport_source}: {e}. "
                "Defaulting to inherit_on_fork=true."
            )

        if passport and passport.update.mode == "shadow-only":
            is_shadow = True
            shadow_path = passport.update.shadow_path or doc.path
        elif doc.shadows is not None:
            is_shadow = True
            shadow_path = doc.path
        else:
            is_shadow = False
            shadow_path = None

        # Validate shadow_path safety if present
        if shadow_path:
            reason = is_safe_designated_doc_path(shadow_path, parent_forge_root, resolved_base)
            if reason:
                logger.debug("Skipping unsafe shadow path %s: %s", shadow_path, reason)
                shadow_path = None

        writer_spec = passport.update.writers if passport else "all-sessions"
        inherit_on_fork = passport.update.inherit_on_fork if passport else True

        resolved.append(
            InheritanceDoc(
                doc=doc,
                passport=passport,
                is_shadow=is_shadow,
                shadow_path=shadow_path,
                writer_spec=writer_spec,
                inherit_on_fork=inherit_on_fork,
            )
        )

    return resolved, warnings


def filter_docs_for_inheritance(
    resolved: list[InheritanceDoc],
    *,
    mode: InheritMemoryMode,
    child_session_name: str | None,
    cli_flag_explicit: bool,
) -> tuple[list[InheritanceDoc], list[str]]:
    """Filter resolved docs by inheritance mode and passport settings.

    Returns (selected_docs, warnings).
    """
    if mode == InheritMemoryMode.NONE:
        return [], []

    selected: list[InheritanceDoc] = []
    warnings: list[str] = []

    for item in resolved:
        if mode == InheritMemoryMode.SHADOWED and not item.is_shadow:
            continue

        if not item.inherit_on_fork:
            if cli_flag_explicit:
                source = resolve_passport_source(item.doc)
                warnings.append(
                    f"--inherit-memory {mode.value} overrides "
                    f"passport inherit_on_fork=false for {source}"
                )
            else:
                continue

        selected.append(item)

        if (
            child_session_name
            and item.writer_spec != "all-sessions"
            and not check_writer_access(item.writer_spec, child_session_name)
        ):
            source = resolve_passport_source(item.doc)
            warnings.append(
                f"Inherited doc {source} has writers={item.writer_spec!r}; "
                f"handoff agent will skip it for session {child_session_name!r}"
            )

    return selected, warnings


def materialize_inherited_shadows(
    shadow_docs: list[InheritanceDoc],
    target_forge_root: Path,
) -> tuple[list[str], list[str]]:
    """Create shadow files in the target forge root for cross-worktree forks.

    Returns (created_messages, skipped_messages).
    """
    created: list[str] = []
    skipped: list[str] = []

    for item in shadow_docs:
        if not item.is_shadow or not item.shadow_path:
            continue
        try:
            was_created = create_shadow_file(item.shadow_path, target_forge_root)
            if was_created:
                created.append(f"Inherited shadow created: {item.shadow_path}")
            elif not (target_forge_root / item.shadow_path).is_file():
                skipped.append(
                    f"Inherited shadow not auto-created (non-Forge-owned): {item.shadow_path}"
                )
        except ValueError:
            skipped.append(
                f"Inherited shadow not auto-created (non-Forge-owned): {item.shadow_path}"
            )

    return created, skipped


def apply_memory_inheritance(
    *,
    parent_state: SessionState,
    child_state: SessionState,
    mode: InheritMemoryMode,
    parent_forge_root: Path,
    child_session_name: str | None,
    cli_flag_explicit: bool,
) -> tuple[list[InheritanceDoc], list[str]]:
    """Filter and assign child memory from parent effective state.

    Owns the entire child memory assignment. Computes effective memory
    (intent + overrides merged), filters docs, and assigns to
    child_state.intent.memory.

    Does NOT materialize shadow files -- returns selected shadow docs
    so the caller can materialize after persistence.

    Returns (selected_shadow_docs, all_warnings).
    """
    from .effective import compute_effective_intent

    effective_intent = compute_effective_intent(parent_state)
    # compute_effective_intent returns a fresh dacite-built SessionIntent
    # (asdict + from_dict), so .memory is already a new object.
    effective_memory = effective_intent.memory

    if effective_memory is None:
        child_state.intent.memory = None
        return [], []

    resolved, resolve_warnings = _resolve_inheritance_docs(
        effective_memory.designated_docs, parent_forge_root
    )
    selected, filter_warnings = filter_docs_for_inheritance(
        resolved,
        mode=mode,
        child_session_name=child_session_name,
        cli_flag_explicit=cli_flag_explicit,
    )
    all_warnings = resolve_warnings + filter_warnings

    effective_memory.designated_docs = [item.doc for item in selected]

    if mode == InheritMemoryMode.NONE:
        effective_memory.auto_update = None

    has_docs = bool(effective_memory.designated_docs)
    has_auto_update = effective_memory.auto_update is not None

    if not has_docs and not has_auto_update:
        child_state.intent.memory = None
    else:
        child_state.intent.memory = effective_memory

    shadow_docs = [item for item in selected if item.is_shadow]
    return shadow_docs, all_warnings
