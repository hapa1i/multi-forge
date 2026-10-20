"""Deletion preserves aliased native copies; changed dependencies refuse the whole cleanup.

The old raw-transcript cleanup scan is retired. These guard the loss scenarios
behind its scan-order regressions through the shared frozen cleanup plan.
"""

import json
from pathlib import Path

import pytest

from forge.session import (
    ForgeSessionError,
    IndexStore,
    SessionManager,
    SessionStore,
    create_session_state,
)
from forge.session.claude.paths import get_transcript_path
from forge.session.deletion import apply_session_deletion, plan_session_deletion
from forge.session.models import Derivation
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression
NATIVE_ID = "11111111-1111-1111-1111-111111111111"


def _publish(root: Path):
    root.mkdir()
    state = create_session_state("child", worktree_path=str(root))
    state.confirmed.claude_session_id = NATIVE_ID
    state.confirmed.claude_project_root = str(root)
    state.confirmed.derivation = Derivation(
        parent_session="external-parent", relocated_parent_session_id=NATIVE_ID, resume_mode="native-relocate"
    )
    index = IndexStore()
    publish_session(index, state, root)
    native = get_transcript_path(str(root), NATIVE_ID)
    native.parent.mkdir(parents=True, exist_ok=True)
    native.write_text("synthetic native transcript\n")
    sidechain = native.parent / NATIVE_ID / "subagents" / "agent-test.jsonl"
    sidechain.parent.mkdir(parents=True)
    sidechain.write_text("synthetic sidechain\n")
    artifact = root / ".forge" / "artifacts" / "child" / "report.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("owned report\n")
    return index, native, sidechain, artifact


def test_delete_preserves_aliased_native_copy_and_sidechain(tmp_path: Path) -> None:
    root = tmp_path / "project"
    index, native, sidechain, artifact = _publish(root)
    SessionManager(index).delete_session("child", forge_root=str(root), delete_worktree=False)
    assert native.read_text() == "synthetic native transcript\n"
    assert sidechain.read_text() == "synthetic sidechain\n"
    assert not artifact.exists()


def test_corrupt_alias_cannot_authorize_any_cleanup(tmp_path: Path) -> None:
    root = tmp_path / "project"
    index, native, sidechain, artifact = _publish(root)
    store = SessionStore(str(root), "child")
    raw = json.loads(store.manifest_path.read_bytes())
    raw["unknown_field"] = True
    store.manifest_path.write_text(json.dumps(raw))
    with pytest.raises(ForgeSessionError, match="[Mm]anifest"):
        SessionManager(index).delete_session("child", forge_root=str(root), force=True)
    assert all(path.exists() for path in (native, sidechain, artifact, store.manifest_path))


def test_new_dependent_after_preview_prevents_partial_cleanup(tmp_path: Path) -> None:
    root = tmp_path / "project"
    index, native, sidechain, artifact = _publish(root)
    plan = plan_session_deletion(index, "child", forge_root=str(root), delete_worktree=False)
    assert not plan.refusals
    descendant = create_session_state("late-child", worktree_path=str(root), parent_session="child")
    publish_session(index, descendant, root)
    with pytest.raises(ForgeSessionError, match="depend"):
        apply_session_deletion(index, plan)
    assert all(path.exists() for path in (native, sidechain, artifact))
    assert SessionStore(str(root), "child").exists()
