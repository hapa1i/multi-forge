"""Memory activation inheritance for fork and resume --fresh.

Copies parent's memory activation (``auto_update``) to the child session.
Memory docs are passport-discovered at Stop time, not inherited.
"""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

from .models import MemoryIntent, MemoryWriterConfig, SessionState
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
    memory_flag: bool | None = None,
) -> list[str]:
    """Copy parent's memory activation to the child session.

    Constructs a fresh ``MemoryIntent(auto_update=...)`` from the parent's
    effective config. Only ``auto_update`` is inherited; other ``MemoryIntent``
    fields (auto_recall, tags, etc.) do not leak into the child.

    Args:
        memory_flag: ``True`` forces memory on, ``False`` forces off,
            ``None`` inherits parent's activation state.

    Returns a list of warning strings (currently empty; extensible).
    """
    from .effective import compute_effective_intent

    effective_intent = compute_effective_intent(parent_state)
    effective_memory = effective_intent.memory
    parent_auto = effective_memory.auto_update if effective_memory else None

    if memory_flag is True:
        base = parent_auto or MemoryWriterConfig()
        child_state.intent.memory = MemoryIntent(
            auto_update=dataclasses.replace(base, enabled=True),
        )
    elif memory_flag is False:
        child_state.intent.memory = MemoryIntent(
            auto_update=MemoryWriterConfig(enabled=False),
        )
    else:
        if parent_auto is not None:
            child_state.intent.memory = MemoryIntent(auto_update=parent_auto)
        else:
            child_state.intent.memory = None

    return []
