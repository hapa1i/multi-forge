"""Regression: `forge clean` must not orphan a child's user-notes overlay.

Bug: GC (``_detect_orphan_transfer_files``) treated every ``*.md`` under
``children/`` as a deletable orphan, keyed off ``Derivation.context_file`` --
which only ever names ``children/<child>.md``. A ``children/<child>.notes.md``
overlay (user-authored, never referenced by any derivation) was therefore
flagged as an orphan and deleted by ``forge clean --yes``, silently losing
user notes paired with a live child.

Root cause: ``iter_children`` yielded notes files, and the orphan loop deleted
any child file not in the reference set.

Fix: ``iter_children`` excludes ``*.notes.md`` and GC pairs a notes file's
liveness to its snapshot (``src/forge/session/prev_sessions.py``,
``src/forge/core/ops/gc.py``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.core.ops.gc import _detect_orphan_transfer_files

pytestmark = pytest.mark.regression


def _write_child_with_notes(children: Path, name: str) -> tuple[Path, Path]:
    snapshot = children / f"{name}.md"
    notes = children / f"{name}.notes.md"
    snapshot.write_text(f"# {name} snapshot", encoding="utf-8")
    notes.write_text("## User Notes\n\nimportant decision", encoding="utf-8")
    return snapshot, notes


def test_live_child_notes_survive_gc_and_dead_child_notes_are_removed(tmp_path: Path) -> None:
    from forge.session import SessionStore, create_session_state
    from forge.session.models import Derivation

    forge_root = tmp_path
    (forge_root / ".forge").mkdir()

    # A live child whose derivation references children/live-child.md.
    child_state = create_session_state("live-child", worktree_path=str(forge_root), parent_session="parent")
    child_state.forge_root = str(forge_root)
    child_state.confirmed.derivation = Derivation(
        parent_session="parent",
        resume_mode="transfer",
        context_file=".forge/prev_sessions/parent/children/live-child.md",
    )
    SessionStore(str(forge_root), "live-child").write(child_state)

    children = forge_root / ".forge" / "prev_sessions" / "parent" / "children"
    children.mkdir(parents=True)
    (children.parent / "generated.md").write_text("# Cache", encoding="utf-8")
    live_snapshot, live_notes = _write_child_with_notes(children, "live-child")
    dead_snapshot, dead_notes = _write_child_with_notes(children, "deleted-child")

    ref_set = {("parent", str(forge_root)), ("live-child", str(forge_root))}
    orphans = _detect_orphan_transfer_files(ref_set, {forge_root}).items

    # The live child's snapshot AND its user notes are preserved (the bug).
    assert str(live_snapshot) not in orphans
    assert str(live_notes) not in orphans
    # The unreferenced child's snapshot and its notes are orphaned together.
    assert str(dead_snapshot) in orphans
    assert str(dead_notes) in orphans
