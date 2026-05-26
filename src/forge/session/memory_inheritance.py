"""Memory doc inheritance for fork and resume --fresh.

Handles selective inheritance of designated memory docs when deriving child
sessions. Only session extras (``origin="extra"``) are inherited; project
memory is discovered live from passports at Stop time.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .models import SessionState
from .validation import is_safe_designated_doc_path

logger = logging.getLogger(__name__)


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


def apply_memory_inheritance(
    *,
    parent_state: SessionState,
    child_state: SessionState,
    inherit_extras: bool = True,
) -> list[str]:
    """Filter and assign child memory from parent effective state.

    Only session extras (``origin="extra"``) are carried forward. Project
    docs are passport-discovered in the child checkout, not inherited.

    Returns a list of warning strings (currently empty; keeps interface
    extensible).
    """
    from .effective import compute_effective_intent

    effective_intent = compute_effective_intent(parent_state)
    effective_memory = effective_intent.memory

    if effective_memory is None:
        child_state.intent.memory = None
        return []

    extras = [d for d in effective_memory.designated_docs if d.origin == "extra"]
    effective_memory.designated_docs = extras if inherit_extras else []

    has_docs = bool(effective_memory.designated_docs)
    has_auto_update = effective_memory.auto_update is not None

    if not has_docs and not has_auto_update:
        child_state.intent.memory = None
    else:
        child_state.intent.memory = effective_memory

    return []
