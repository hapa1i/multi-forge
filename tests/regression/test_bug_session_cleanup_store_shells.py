"""Regression: harmless session-store entries blocked every cleanup in a project.

Bug: session_cleanup_store_shells.
Root cause: dependency discovery refused any non-directory under
``.forge/sessions/`` other than an authority lock, so Finder's ``.DS_Store``
blocked delete, purge and clean. It also refused every directory without a
manifest, including the lock-only shell a manifest update racing deletion
leaves behind, which made one interrupted delete block later cleanup.

Fix: regular files cannot hold a session and are skipped. An unindexed shell
that holds only the manifest lock reserves nothing and is skipped. Other
directories without manifests, symlinks, and indexed rows whose manifest is
missing still refuse.

Affected: src/forge/session/cleanup_dependencies.py, src/forge/session/store.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.session import SessionManager, SessionStore
from forge.session.deletion import plan_session_deletion
from forge.session.exceptions import ForgeSessionError
from forge.session.index import IndexStore
from forge.session.models import create_session_state
from forge.session.store import MANIFEST_FILENAME
from tests.fixtures.session_state import seed_row_only_session

pytestmark = pytest.mark.regression


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".forge").mkdir()
    SessionManager(index_store=IndexStore()).start_session("victim", worktree_path=str(root), direct=True)
    return root


def _refusals(project: Path) -> tuple[str, ...]:
    """Preview refusals, including discovery failures raised before a plan exists."""
    try:
        plan = plan_session_deletion(IndexStore(), "victim", forge_root=str(project), delete_worktree=False)
    except ForgeSessionError as error:
        return (str(error),)
    return plan.refusals


def test_stray_file_and_lock_only_shell_do_not_block_delete(project: Path) -> None:
    sessions = project / ".forge" / "sessions"
    (sessions / ".DS_Store").write_bytes(b"\0\0\0\1Bud1")
    shell = sessions / "interrupted"
    shell.mkdir()
    (shell / f"{MANIFEST_FILENAME}.lock").touch()
    (sessions / "empty").mkdir()

    assert _refusals(project) == ()

    SessionManager(index_store=IndexStore()).delete_session("victim", forge_root=str(project), delete_worktree=False)
    assert not SessionStore(str(project), "victim").exists()
    assert shell.is_dir(), "cleanup of one session must not remove another name's shell"


@pytest.mark.parametrize("content", ["notes.txt", "review-identity"])
def test_directory_with_unmanifested_content_still_refuses(project: Path, content: str) -> None:
    orphan = project / ".forge" / "sessions" / "orphan"
    orphan.mkdir()
    (orphan / content).write_text("unknown\n")

    assert any("orphan" in refusal and "missing manifest" in refusal for refusal in _refusals(project))


def test_symlinked_store_entry_still_refuses(tmp_path: Path, project: Path) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    (project / ".forge" / "sessions" / "linked").symlink_to(target, target_is_directory=True)

    assert any("unexpected session-store entry" in refusal for refusal in _refusals(project))


def test_indexed_row_without_manifest_still_refuses(project: Path) -> None:
    # Violates the coherent-publication invariant on purpose: an indexed name with
    # no manifest needs repair, and an empty directory must not hide it.
    index = IndexStore()
    state = create_session_state("degraded", worktree_path=str(project))
    seed_row_only_session(index, state, project)
    (project / ".forge" / "sessions" / "degraded").mkdir(exist_ok=True)

    assert any("degraded" in refusal and "forge session repair" in refusal for refusal in _refusals(project))
