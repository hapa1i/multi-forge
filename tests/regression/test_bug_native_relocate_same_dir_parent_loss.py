"""Regression: native-relocate same-dir collision must not delete the parent's original transcript.

Bug (audit P3, high): native-relocate had no source != dest guard. When the relocate
destination encoded to the parent's OWN Claude project dir -- via ``fork --into <parent's
own worktree>`` or via ``encode_project_path`` collapsing ``/``, ``.``, and ``_`` all to
``-`` (non-injective) -- ``relocate_transcript`` hit its idempotent no-op branch while the
fork still recorded ``derivation.relocated_parent_session_id``. Later child deletion then
unlinked ``get_transcript_path(<shared dir>, parent_uuid)`` -- the parent's ORIGINAL live
transcript (data loss). The shipped contract test only used ``create_worktree=True`` (a
distinct child dir), so the collision was unguarded and untested.

Fix: ``relocate_transcript`` raises ``RelocateSameDirError`` on source == dest
(``relocate.py``); the fork preflight + relocate handler reject it (``session_fork.py``);
and ``delete_session``'s relocate-GC skips the unlink when the child dir collides with a
recorded parent root (``manager.py``).

Affected: src/forge/session/claude/relocate.py, src/forge/cli/session_fork.py,
src/forge/session/manager.py, src/forge/session/claude/paths.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.session.claude import RelocateSameDirError, relocate_transcript
from forge.session.claude.paths import encode_project_path, get_transcript_path
from forge.session.manager import SessionManager

pytestmark = pytest.mark.regression


def _write_transcript(project_root: str, uuid: str, content: str = "PARENT\n") -> Path:
    path = get_transcript_path(project_root, uuid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_relocate_rejects_same_source_and_dest(tmp_path: Path) -> None:
    """Layer 1: relocate raises (not no-ops) when source and dest are the same dir."""
    proj = str(tmp_path / "proj")
    Path(proj).mkdir()
    src = _write_transcript(proj, "uuid-same")

    with pytest.raises(RelocateSameDirError):
        relocate_transcript(session_id="uuid-same", source_project_root=proj, dest_project_root=proj)
    assert src.read_text() == "PARENT\n", "source transcript must be untouched"


def test_relocate_rejects_encode_collision(tmp_path: Path) -> None:
    """Layer 1: distinct CWDs that encode_project_path collapses to the same dir are rejected."""
    src_root = str(tmp_path / "proj_x")
    dst_root = str(tmp_path / "proj-x")
    Path(src_root).mkdir()
    Path(dst_root).mkdir()
    # Precondition: '_' and '-' both map to '-', so these distinct paths encode identically.
    assert encode_project_path(src_root) == encode_project_path(dst_root)
    src = _write_transcript(src_root, "uuid-collide")

    with pytest.raises(RelocateSameDirError):
        relocate_transcript(session_id="uuid-collide", source_project_root=src_root, dest_project_root=dst_root)
    assert src.read_text() == "PARENT\n", "parent's original (under the colliding dir) must be untouched"


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], capture_output=True, check=True, cwd=str(path))
    subprocess.run(["git", "config", "user.name", "T"], capture_output=True, check=True, cwd=str(path))
    (path / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], capture_output=True, check=True, cwd=str(path))
    subprocess.run(["git", "commit", "-m", "init"], capture_output=True, check=True, cwd=str(path))


def test_delete_preserves_parent_original_on_dir_collision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Layer 3 (defense-in-depth): deleting a native-relocate child whose encoded dir collides
    with the parent's own dir must NOT unlink the parent's original transcript."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    parent_repo = tmp_path / "repo"
    _init_git_repo(parent_repo)
    (parent_repo / ".claude").mkdir(exist_ok=True)
    (parent_repo / ".forge").mkdir(exist_ok=True)

    manager = SessionManager()
    manager.start_session(name="parent", worktree_path=str(parent_repo))
    pstore = manager.get_session_store("parent")
    pstate = pstore.read()
    pstate.confirmed.claude_session_id = "puuid"
    pstore.write(pstate)

    _, fork = manager.fork_session("parent", "child", create_worktree=True, resume_mode="native-relocate")
    assert fork.confirmed.derivation is not None
    assert fork.confirmed.derivation.relocated_parent_session_id == "puuid"

    # Force the collision: point the child's claude_project_root at the PARENT's dir so the
    # relocate-GC computes _reloc_path == the parent's original transcript.
    fstore = manager.get_session_store("child")
    fchild = fstore.read()
    fchild.confirmed.claude_project_root = str(parent_repo)
    fchild.confirmed.claude_session_id = None
    fstore.write(fchild)

    parent_original = _write_transcript(str(parent_repo), "puuid")

    manager.delete_session("child", delete_transcripts=True, delete_worktree=False, force=True)

    assert parent_original.exists(), "parent's original transcript must be preserved on dir collision"
    assert parent_original.read_text() == "PARENT\n"
