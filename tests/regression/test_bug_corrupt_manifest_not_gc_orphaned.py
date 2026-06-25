"""Regression: forge clean must not delete a live child's transfer context when a
session manifest is unreadable.

Bug: ``_build_transfer_context_reference_set`` swallowed every read error
(``except Exception: continue``), dropping the unreadable session's
``derivation.context_file`` from the protected set. ``_detect_orphan_transfer_files``
then classified the live child's ``children/<child>.md`` as orphaned and
``_clean_transfer_files`` unlinked authoritative context (the file appended to the
child session's system prompt). The same swallow fed the codex stale-snapshot guard,
which would unlink a referenced snapshot it deemed unreferenced. Both failed OPEN
toward deletion of durable, in-use state.

Root cause: ``src/forge/core/ops/gc.py:_build_transfer_context_reference_set``.
Fix: corruption (``StateCorruptedError``) propagates so callers fail closed; only a
genuinely-missing manifest (``SessionFileNotFoundError``) is skipped as protecting
nothing. The GC detector degrades that one category to empty; the codex guard's
existing rollback preserves the foreign snapshot.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.core.ops.gc import (
    _build_transfer_context_reference_set,
    _detect_orphan_transfer_files,
)
from forge.core.state.exceptions import StateCorruptedError
from forge.session import SessionStore, create_session_state
from forge.session.models import Derivation

pytestmark = pytest.mark.regression


def _seed_child_with_context(fr: Path) -> Path:
    """Seed a parent + child whose derivation references ``parent/children/child.md``.

    Returns the on-disk child context file path.
    """
    SessionStore(str(fr), "parent").write(create_session_state("parent", worktree_path=str(fr)))

    child_state = create_session_state("child", worktree_path=str(fr), parent_session="parent")
    child_state.forge_root = str(fr)
    child_state.confirmed.derivation = Derivation(
        parent_session="parent",
        resume_mode="transfer",
        context_file=".forge/prev_sessions/parent/children/child.md",
    )
    SessionStore(str(fr), "child").write(child_state)

    children_dir = fr / ".forge" / "prev_sessions" / "parent" / "children"
    children_dir.mkdir(parents=True)
    (children_dir.parent / "generated.md").write_text("# Cache")
    child_md = children_dir / "child.md"
    child_md.write_text("# Live transfer context")
    return child_md


def _corrupt_manifest(fr: Path, name: str) -> None:
    manifest = fr / ".forge" / "sessions" / name / "forge.session.json"
    manifest.write_text("{ this is not valid json", encoding="utf-8")


def test_corrupt_child_manifest_does_not_orphan_live_context(tmp_path: Path) -> None:
    fr = tmp_path / "project"
    child_md = _seed_child_with_context(fr)
    _corrupt_manifest(fr, "child")  # still indexed (live), manifest now unreadable

    ref_set = {("parent", str(fr)), ("child", str(fr))}
    result = _detect_orphan_transfer_files(ref_set, {fr})

    # Fail closed: the unreadable manifest's protected path is unknown, so the
    # detector degrades to empty rather than deleting the live child's context.
    assert result.count == 0
    assert str(child_md) not in result.items
    assert child_md.exists()


def test_build_reference_set_propagates_corruption(tmp_path: Path) -> None:
    """The codex stale-snapshot guard relies on this raise to fail closed."""
    fr = tmp_path / "project"
    _seed_child_with_context(fr)
    _corrupt_manifest(fr, "child")

    ref_set = {("parent", str(fr)), ("child", str(fr))}
    with pytest.raises(StateCorruptedError):
        _build_transfer_context_reference_set(ref_set)


def test_missing_manifest_still_skipped_as_unprotected(tmp_path: Path) -> None:
    """A genuinely-missing manifest protects nothing -- distinct from corruption.

    Guards the narrowing: SessionFileNotFoundError must still be swallowed (the
    session references nothing), or every dangling-entry race would abort clean.
    """
    fr = tmp_path / "project"
    SessionStore(str(fr), "parent").write(create_session_state("parent", worktree_path=str(fr)))
    # "ghost" is in the ref_set but has no manifest on disk.
    ref_set = {("parent", str(fr)), ("ghost", str(fr))}

    # No raise, ghost simply contributes no protected paths.
    assert _build_transfer_context_reference_set(ref_set) == set()
