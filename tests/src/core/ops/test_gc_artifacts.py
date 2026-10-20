"""Orphan artifacts require absent sessions, no dependencies, and unchanged content."""

from pathlib import Path

import pytest

from forge.core.ops.context import ExecutionContext
from forge.core.ops.gc import (
    CleanReport,
    CleanResult,
    _clean_orphan_artifacts,
    _detect_orphan_artifacts,
    collect_clean_report,
    run_clean,
)
from forge.search.content_store import ContentStore
from forge.session.index import IndexStore
from forge.session.models import Derivation, create_session_state
from tests.fixtures.session_state import publish_session


def _artifact(root: Path, name: str) -> Path:
    path = root / ".forge/artifacts" / name / "transcripts/session.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("private transcript")
    return path


def _report(root: Path) -> CleanReport:
    category, refused, plans = _detect_orphan_artifacts({root})
    return CleanReport(categories=[category, refused], scope="project", _orphan_artifact_plans=plans)


def _ctx(root: Path) -> ExecutionContext:
    return ExecutionContext(cwd=root, worktree_root=root, project_root=root, forge_root=root)


def test_clean_reports_and_removes_unreferenced_artifacts_and_search_text(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    artifact = _artifact(root, "deleted")
    ContentStore(root).add(str(artifact), "private searchable text")
    before = artifact.read_bytes()
    report = collect_clean_report(ctx=_ctx(root), scope="project")
    category = next(category for category in report.categories if category.category == "orphan_artifacts")
    assert category.items == [str(root / ".forge/artifacts/deleted")]
    assert artifact.read_bytes() == before
    result = run_clean(ctx=_ctx(root), scope="project")
    assert not result.failed
    assert result.categories_cleaned["orphan_artifacts"] == 1
    assert not artifact.exists()
    assert ContentStore(root).read_all() == {}


def test_live_session_and_unindexed_manifest_protect_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "project"
    live = _artifact(root, "live")
    state = create_session_state("live", worktree_path=str(root))
    publish_session(IndexStore(), state, root, forge_root=root)
    unindexed = _artifact(root, "recoverable")
    manifest_dir = root / ".forge/sessions/recoverable"
    manifest_dir.mkdir(parents=True)
    # A raw directory represents crash residue; even its unreadable manifest must protect content.
    (manifest_dir / "forge.session.json").write_text("unreadable crash residue")
    category, _, plans = _detect_orphan_artifacts({root})
    assert not category.items and not plans
    assert live.exists() and unindexed.exists()


def test_cross_root_dependency_protects_orphan_artifacts(tmp_path: Path) -> None:
    root, other = tmp_path / "project", tmp_path / "other"
    artifact = _artifact(root, "ancestor")
    state = create_session_state("child", worktree_path=str(other), parent_session="ancestor")
    state.confirmed.derivation = Derivation(
        parent_session="ancestor",
        parent_forge_root=str(root),
        parent_transcript=str(artifact),
    )
    publish_session(IndexStore(), state, other, forge_root=other)
    category, refused, plans = _detect_orphan_artifacts({root})
    assert not category.items and not plans
    assert len(refused.items) == 1 and "child" in refused.items[0]
    assert artifact.exists()


@pytest.mark.parametrize("changed", ["session", "bytes", "dependency", "symlink"])
def test_apply_rechecks_claims_dependencies_and_file_identity(tmp_path: Path, changed: str) -> None:
    root = tmp_path / "project"
    artifact = _artifact(root, "deleted")
    report = _report(root)
    items = report.categories[0].items
    assert items
    if changed == "session":
        publish_session(
            IndexStore(),
            create_session_state("deleted", worktree_path=str(root)),
            root,
            forge_root=root,
        )
    elif changed == "bytes":
        artifact.write_text("changed after preview")
    elif changed == "dependency":
        other = tmp_path / "other"
        state = create_session_state("new-child", worktree_path=str(other), parent_session="deleted")
        state.confirmed.derivation = Derivation(parent_session="deleted", parent_forge_root=str(root))
        publish_session(IndexStore(), state, other, forge_root=other)
    else:
        outside = tmp_path / "outside.txt"
        outside.write_text("preserve")
        artifact.unlink()
        artifact.symlink_to(outside)
    result = CleanResult()
    assert _clean_orphan_artifacts(items, report, result) == 0
    assert result.failed
    assert artifact.exists()


def test_symlinked_artifact_tree_is_report_only(tmp_path: Path) -> None:
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    outside.mkdir()
    target = root / ".forge/artifacts/deleted"
    target.parent.mkdir(parents=True)
    target.symlink_to(outside, target_is_directory=True)
    category, refused, plans = _detect_orphan_artifacts({root})
    assert not category.items and not plans
    assert refused.items and str(target) in refused.items[0]
    assert outside.exists()
