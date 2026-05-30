"""Regression: resume_mode value renamed handoff -> transfer (memory_substrate Phase 2).

Change: the durable token persisted at ``confirmed.derivation.resume_mode`` was
renamed ``"handoff"`` -> ``"transfer"``. Old manifests on disk still carry
``"handoff"``. Because ``resume_mode`` is a loosely-typed ``str | None`` field and
no reader branches on a *loaded* parent's mode token (only ``== "native"`` is
special-cased), legacy values must remain tolerated on read with no migration
code, while freshly derived sessions record ``"transfer"``.

Affected files:
- src/forge/session/models.py (Derivation.resume_mode)
- src/forge/session/manager.py (default param, validation set, write site, comparisons)
- src/forge/cli/session_lifecycle.py (--resume-mode flag + fork persist)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.session import SessionStore, create_session_state
from forge.session.models import Derivation

pytestmark = pytest.mark.regression


def test_legacy_handoff_resume_mode_loads_unchanged(tmp_path: Path) -> None:
    """A manifest written with the legacy "handoff" value still deserializes cleanly."""
    forge_root = tmp_path / "proj"
    forge_root.mkdir()
    state = create_session_state("legacy", worktree_path=str(forge_root))
    state.forge_root = str(forge_root)
    state.confirmed.derivation = Derivation(parent_session="p", resume_mode="handoff")

    store = SessionStore(str(forge_root), "legacy")
    store.write(state)

    # Strict deserialization must tolerate the legacy string value: no rejection,
    # no normalization. resume_mode is str|None and only "native" is special-cased.
    loaded = store.read()
    assert loaded.confirmed.derivation is not None
    assert loaded.confirmed.derivation.resume_mode == "handoff"


def test_fresh_resume_from_legacy_handoff_parent_records_transfer(tmp_path: Path) -> None:
    """Resume from a parent carrying the legacy "handoff" derivation.

    Covers the actual compatibility claim: the pre-rename parent manifest loads
    during a live resume, and the freshly derived child records the new
    "transfer" token (not "handoff").
    """
    from forge.session.index import IndexStore
    from forge.session.manager import SessionManager

    forge_root = tmp_path / "proj"
    forge_root.mkdir()
    parent = create_session_state("parent", worktree_path=str(forge_root))
    parent.forge_root = str(forge_root)
    # Parent was written by pre-rename Forge: its derivation carries "handoff".
    parent.confirmed.derivation = Derivation(parent_session="grandparent", resume_mode="handoff")
    SessionStore(str(forge_root), "parent").write(parent)
    IndexStore().add_from_state(parent, str(forge_root))

    child_state, _ = SessionManager().resume_session("parent", child_name="child", forge_root=str(forge_root))

    assert child_state.confirmed.derivation is not None
    assert child_state.confirmed.derivation.resume_mode == "transfer"
