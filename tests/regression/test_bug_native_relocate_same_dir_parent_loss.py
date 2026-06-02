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
(``relocate.py``); the fork preflight + relocate handler reject it (``session_fork.py``).
``delete_session``'s relocate-GC now routes the relocated copy through the path-resolved
shared-transcript scan (``manager.py``): the relocated UUID is the parent's
``claude_session_id``, so the scan skips the unlink whenever the parent's original OR a
co-resident native-relocate sibling still resolves to that path -- replacing an earlier
encoded-dir guard that used index identity and so missed root-level-worktree parents and
sibling sharing (audit HIGH sibling-bug + backstop source-of-truth).

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


def test_delete_sibling_preserves_shared_relocated_transcript(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Audit HIGH sibling-bug: two `fork --into <same-checkout> --resume-mode native-relocate`
    children relocate the SAME parent UUID into the SAME dir (idempotent relocate), so both record
    relocated_parent_session_id pointing at one shared copy. Deleting one sibling must NOT unlink the
    copy the other still needs. Pre-fix the relocate-GC had no sibling awareness and unlinked it.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    parent_repo = tmp_path / "repo"
    _init_git_repo(parent_repo)
    (parent_repo / ".claude").mkdir(exist_ok=True)
    (parent_repo / ".forge").mkdir(exist_ok=True)
    # A separate checkout both siblings fork --into (distinct from the parent's own dir).
    target = tmp_path / "repo-feat"
    _init_git_repo(target)
    (target / ".claude").mkdir(exist_ok=True)
    (target / ".forge").mkdir(exist_ok=True)

    manager = SessionManager()
    manager.start_session(name="parent", worktree_path=str(parent_repo))
    pstore = manager.get_session_store("parent")
    pstate = pstore.read()
    pstate.confirmed.claude_session_id = "puuid"
    pstore.write(pstate)

    _, child_a = manager.fork_session("parent", "child-a", into_path=str(target), resume_mode="native-relocate")
    _, child_b = manager.fork_session("parent", "child-b", into_path=str(target), resume_mode="native-relocate")
    assert child_a.confirmed.derivation is not None
    assert child_b.confirmed.derivation is not None
    assert child_a.confirmed.derivation.relocated_parent_session_id == "puuid"
    assert child_b.confirmed.derivation.relocated_parent_session_id == "puuid"

    # The shared relocated copy in the target checkout (what a real launch would have written),
    # plus the parent's untouched original under its own checkout.
    shared_reloc = _write_transcript(str(target), "puuid", "RELOCATED\n")
    parent_original = _write_transcript(str(parent_repo), "puuid", "PARENT\n")

    manager.delete_session("child-a", delete_transcripts=True, delete_worktree=False, force=True)
    assert shared_reloc.exists(), "shared relocated copy must survive while sibling child-b references it"
    assert shared_reloc.read_text() == "RELOCATED\n"

    # Once the last referencing sibling is gone, the copy is reclaimed; the parent's own original
    # (under a different checkout) is never touched by either child deletion.
    manager.delete_session("child-b", delete_transcripts=True, delete_worktree=False, force=True)
    assert not shared_reloc.exists(), "relocated copy reclaimed once no session references it"
    assert parent_original.exists(), "parent's own original (different checkout) untouched throughout"
    assert parent_original.read_text() == "PARENT\n"


def test_delete_preserves_divergent_topology_parent_original(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Audit backstop source-of-truth: a parent whose Claude CWD (claude_project_root) diverges from
    its forge_root (root-level worktree) -- the child collides with the parent's CLAUDE CWD, not its
    forge_root. The old _parent_dirs guard built its set from index identity (parent_forge_root/
    project_root) and so missed this dir, unlinking the parent's original. The path-resolved
    shared-transcript scan finds the parent (it references the same UUID at the same resolved path).
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    main_repo = tmp_path / "repo"
    _init_git_repo(main_repo)
    (main_repo / ".claude").mkdir(exist_ok=True)
    (main_repo / ".forge").mkdir(exist_ok=True)
    parent_cwd = tmp_path / "repo-parentwt"  # parent's actual Claude CWD, != forge_root (main_repo)
    parent_cwd.mkdir()

    manager = SessionManager()
    manager.start_session(name="parent", worktree_path=str(main_repo))
    pstore = manager.get_session_store("parent")
    pstate = pstore.read()
    pstate.confirmed.claude_session_id = "puuid"
    pstate.confirmed.claude_project_root = str(parent_cwd)  # diverges from forge_root
    pstore.write(pstate)

    _, child = manager.fork_session("parent", "child", create_worktree=True, resume_mode="native-relocate")
    assert child.confirmed.derivation is not None
    assert child.confirmed.derivation.relocated_parent_session_id == "puuid"

    # Force the child's relocate dir to collide with the parent's CLAUDE CWD (not its forge_root).
    fstore = manager.get_session_store("child")
    fchild = fstore.read()
    fchild.confirmed.claude_project_root = str(parent_cwd)
    fchild.confirmed.claude_session_id = None
    fstore.write(fchild)

    parent_original = _write_transcript(str(parent_cwd), "puuid", "PARENT\n")

    manager.delete_session("child", delete_transcripts=True, delete_worktree=False, force=True)

    assert parent_original.exists(), "parent's original (under its Claude CWD, != forge_root) must survive"
    assert parent_original.read_text() == "PARENT\n"
