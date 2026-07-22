"""Tests for forge.core.ops.gc — garbage collection operations."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from forge.core.ops.context import ExecutionContext
from forge.core.ops.gc import (
    CleanError,
    CleanReport,
    OrphanCategory,
    _detect_dead_installations,
    _detect_orphan_session_dirs,
    _detect_orphan_transfer_files,
    _detect_stale_active_entries,
    _detect_stale_work_queue,
    _path_in_roots,
    _project_compatibility_skips,
    _resolve_tracked_roots,
    collect_clean_report,
    run_clean,
)
from forge.install.models import (
    Installation,
    InstalledFile,
    InstalledManifest,
    InstalledSkillPackage,
    make_installation_key,
)
from forge.install.skill_compiler import FORGE_PACKAGE_SENTINEL
from forge.install.tracking import TrackingStore, compute_checksum
from forge.session import IndexStore
from forge.session.models import create_session_state
from forge.session.store import SessionStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _forge_home() -> Path:
    """Return the test-isolated FORGE_HOME (set by autouse fixture)."""
    return Path(os.environ["FORGE_HOME"])


def _seed_session(tmp_path: Path, name: str, forge_root: Path | None = None) -> Path:
    """Create a session in the index + on disk. Returns the forge_root."""
    fr = forge_root or tmp_path / "project"
    session_dir = fr / ".forge" / "sessions" / name
    session_dir.mkdir(parents=True, exist_ok=True)
    # Write a valid manifest (not a `{}` sentinel): corrupt-state detection reads
    # the manifest strictly, so a seeded session must model a healthy one.
    SessionStore(str(fr), name).write(create_session_state(name, worktree_path=str(fr)))

    index = IndexStore()
    index.add_session(
        name=name,
        worktree_path=str(fr),
        project_root=str(tmp_path),
        forge_root=str(fr),
        checkout_root=str(fr),
        relative_path=".",
        is_incognito=False,
        is_fork=False,
        parent_session=None,
    )
    return fr


def _make_ctx(tmp_path: Path, forge_root: Path | None = None) -> ExecutionContext:
    return ExecutionContext(
        cwd=tmp_path,
        worktree_root=tmp_path,
        project_root=tmp_path,
        forge_root=forge_root,
    )


def _write_marked_skill_package(
    skill_root: Path,
    *,
    runtime: str = "codex",
    skill: str = "understand",
    content: bytes = b"---\nname: understand\n---\n",
) -> Path:
    package = skill_root / skill
    package.mkdir(parents=True)
    payload = package / "SKILL.md"
    payload.write_bytes(content)
    payload.chmod(0o644)
    marker = {
        "schema_version": 1,
        "producer": "multi-forge",
        "runtime": runtime,
        "skill": skill,
        "files": [
            {
                "path": "SKILL.md",
                "sha256": hashlib.sha256(content).hexdigest(),
                "mode": 0o644,
            }
        ],
    }
    (package / FORGE_PACKAGE_SENTINEL).write_text(
        json.dumps(marker, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return package


def _claim_project_package(project: Path, package: Path, *, runtime: str = "codex") -> None:
    file_paths = sorted(str(path) for path in (package / "SKILL.md", package / FORGE_PACKAGE_SENTINEL))
    installed_files = [
        InstalledFile(
            target_path=path,
            source_path=path,
            checksum=compute_checksum(Path(path)),
            mode="copy",
            installed_at="2026-07-22T00:00:00+00:00",
        )
        for path in file_paths
    ]
    installation = Installation(
        scope="project",
        project_path=str(project),
        mode="copy",
        profile="standard",
        modules_enabled=["skills"],
        files=installed_files,
        skill_packages=[
            InstalledSkillPackage(
                runtime=runtime,
                skill=package.name,
                target_dir=str(package),
                file_paths=file_paths,
            )
        ],
    )
    TrackingStore().write(
        InstalledManifest(
            installations={make_installation_key("project", str(project)): installation},
        )
    )


# ---------------------------------------------------------------------------
# _resolve_tracked_roots
# ---------------------------------------------------------------------------


class TestResolveTrackedRoots:
    def test_scope_project_requires_forge_root(self, tmp_path: Path) -> None:
        ctx = _make_ctx(tmp_path, forge_root=None)
        with pytest.raises(CleanError, match="Not inside a Forge project"):
            _resolve_tracked_roots(ctx, "project")

    def test_scope_project_returns_forge_root(self, tmp_path: Path) -> None:
        fr = tmp_path / "project"
        fr.mkdir()
        ctx = _make_ctx(tmp_path, forge_root=fr)
        roots = _resolve_tracked_roots(ctx, "project")
        assert roots == {fr}

    def test_scope_workspace_includes_index_entries(self, tmp_path: Path) -> None:
        fr = _seed_session(tmp_path, "alpha")
        ctx = _make_ctx(tmp_path, forge_root=fr)
        roots = _resolve_tracked_roots(ctx, "workspace")
        assert fr in roots

    def test_scope_all_includes_all_entries(self, tmp_path: Path) -> None:
        fr1 = _seed_session(tmp_path, "alpha", tmp_path / "proj-a")
        fr2 = _seed_session(tmp_path, "beta", tmp_path / "proj-b")
        ctx = _make_ctx(tmp_path)
        roots = _resolve_tracked_roots(ctx, "all")
        assert fr1 in roots
        assert fr2 in roots


# ---------------------------------------------------------------------------
# _detect_orphan_session_dirs
# ---------------------------------------------------------------------------


class TestDetectOrphanSessionDirs:
    def test_no_orphans(self, tmp_path: Path) -> None:

        fr = _seed_session(tmp_path, "alpha")
        ref_set = {("alpha", str(fr))}
        result = _detect_orphan_session_dirs(ref_set, {fr})
        assert result.count == 0

    def test_detects_orphan(self, tmp_path: Path) -> None:

        fr = _seed_session(tmp_path, "alpha")

        # Create an extra session dir not in the index
        orphan_dir = fr / ".forge" / "sessions" / "ghost"
        orphan_dir.mkdir(parents=True)
        (orphan_dir / "forge.session.json").write_text("{}")

        ref_set = {("alpha", str(fr))}
        result = _detect_orphan_session_dirs(ref_set, {fr})
        assert result.count == 1
        assert str(orphan_dir) in result.items[0]

    def test_skips_empty_dirs(self, tmp_path: Path) -> None:

        fr = _seed_session(tmp_path, "alpha")

        # Empty dir should be ignored
        empty_dir = fr / ".forge" / "sessions" / "empty"
        empty_dir.mkdir(parents=True)

        ref_set = {("alpha", str(fr))}
        result = _detect_orphan_session_dirs(ref_set, {fr})
        assert result.count == 0

    def test_name_reuse_across_forge_roots(self, tmp_path: Path) -> None:
        """Same name in different forge_roots should not mask each other."""

        fr_a = tmp_path / "proj-a"
        fr_b = tmp_path / "proj-b"
        _seed_session(tmp_path, "alpha", fr_a)

        # Create "alpha" dir in proj-b (not in index for proj-b)
        orphan_dir = fr_b / ".forge" / "sessions" / "alpha"
        orphan_dir.mkdir(parents=True)
        (orphan_dir / "forge.session.json").write_text("{}")

        ref_set = {("alpha", str(fr_a))}
        result = _detect_orphan_session_dirs(ref_set, {fr_a, fr_b})
        assert result.count == 1
        assert str(orphan_dir) in result.items[0]

    def test_codex_handoff_files_in_indexed_session_not_flagged(self, tmp_path: Path) -> None:
        """Phase 4 staged-handoff files live INSIDE the session dir, so an indexed
        session carrying codex/pending-context.md + context-receipt.json is never an
        orphan, and session deletion removes them with the dir."""
        from forge.session import SessionStore
        from forge.session.codex_handoff import (
            pending_context_path,
            receipt_path,
            stage_pending_context,
        )

        fr = _seed_session(tmp_path, "alpha")
        session_dir = fr / ".forge" / "sessions" / "alpha"
        stage_pending_context(session_dir, "# Handoff context\n\nbody\n")
        receipt_path(session_dir).write_text("{}")

        ref_set = {("alpha", str(fr))}
        result = _detect_orphan_session_dirs(ref_set, {fr})
        assert result.count == 0

        assert SessionStore(str(fr), "alpha").delete() is True
        assert not pending_context_path(session_dir).exists()
        assert not receipt_path(session_dir).exists()


# ---------------------------------------------------------------------------
# _detect_orphan_transfer_files
# ---------------------------------------------------------------------------


class TestDetectOrphanHandoffFiles:
    def test_no_orphans(self, tmp_path: Path) -> None:
        fr = _seed_session(tmp_path, "parent")

        # New layout: <parent>/generated.md + <parent>/children/<child>.md
        # Only "parent" is in the ref_set, but a self-resume (child = parent
        # name reuse via auto-gen suffix) wouldn't happen; for "no orphans"
        # we simulate a parent dir with no children yet.
        parent_dir = fr / ".forge" / "prev_sessions" / "parent"
        parent_dir.mkdir(parents=True)
        (parent_dir / "generated.md").write_text("# Cache")

        ref_set = {("parent", str(fr))}
        result = _detect_orphan_transfer_files(ref_set, {fr})
        assert result.count == 0

    def test_detects_orphan_parent_dir(self, tmp_path: Path) -> None:
        fr = _seed_session(tmp_path, "alpha")

        # Parent dir for a session that isn't in the index -- whole dir orphan
        orphan_parent = fr / ".forge" / "prev_sessions" / "deleted-parent"
        orphan_parent.mkdir(parents=True)
        (orphan_parent / "generated.md").write_text("# Stale cache")

        ref_set = {("alpha", str(fr))}
        result = _detect_orphan_transfer_files(ref_set, {fr})
        assert result.count == 1
        assert "deleted-parent" in result.items[0]

    def test_detects_orphan_child_file(self, tmp_path: Path) -> None:
        # Both parent and one valid child are in the index; an additional
        # child file under the same parent is orphaned (e.g., child was
        # deleted from the index but the file lingered).
        fr = _seed_session(tmp_path, "parent")
        _seed_session(tmp_path, "live-child", forge_root=fr)
        from forge.session import SessionStore, create_session_state
        from forge.session.models import Derivation

        live_state = create_session_state("live-child", worktree_path=str(fr))
        live_state.forge_root = str(fr)
        live_state.confirmed.derivation = Derivation(
            parent_session="parent",
            resume_mode="transfer",
            context_file=".forge/prev_sessions/parent/children/live-child.md",
        )
        SessionStore(str(fr), "live-child").write(live_state)

        parent_dir = fr / ".forge" / "prev_sessions" / "parent"
        parent_dir.mkdir(parents=True)
        (parent_dir / "generated.md").write_text("# Cache")
        children_dir = parent_dir / "children"
        children_dir.mkdir()
        (children_dir / "live-child.md").write_text("# Live child")
        (children_dir / "deleted-child.md").write_text("# Orphan child")

        ref_set = {("parent", str(fr)), ("live-child", str(fr))}
        result = _detect_orphan_transfer_files(ref_set, {fr})
        assert result.count == 1
        assert "deleted-child.md" in result.items[0]

    def test_preserves_cross_root_child_file_referenced_by_derivation(self, tmp_path: Path) -> None:
        parent_root = _seed_session(tmp_path, "parent")
        child_root = tmp_path / "child-root"
        child_root.mkdir()

        from forge.session import SessionStore, create_session_state
        from forge.session.models import Derivation

        child_state = create_session_state("child", worktree_path=str(child_root), parent_session="parent")
        child_state.forge_root = str(child_root)
        child_state.confirmed.derivation = Derivation(
            parent_session="parent",
            # Legacy "handoff" value retained intentionally: GC keys off context_file,
            # not the resume_mode token, so it must handle pre-rename manifests too.
            resume_mode="handoff",
            context_file=".forge/prev_sessions/parent/children/child.md",
        )
        SessionStore(str(child_root), "child").write(child_state)

        parent_dir = child_root / ".forge" / "prev_sessions" / "parent"
        children_dir = parent_dir / "children"
        children_dir.mkdir(parents=True)
        (parent_dir / "generated.md").write_text("# Cache")
        live_child = children_dir / "child.md"
        live_child.write_text("# Live context")
        stale_child = children_dir / "stale.md"
        stale_child.write_text("# Stale context")

        ref_set = {("parent", str(parent_root)), ("child", str(child_root))}
        result = _detect_orphan_transfer_files(ref_set, {parent_root, child_root})

        assert str(parent_dir) not in result.items
        assert str(live_child) not in result.items
        assert result.items == [str(stale_child)]

    def test_existing_session_name_does_not_keep_unreferenced_child_file(self, tmp_path: Path) -> None:
        fr = _seed_session(tmp_path, "parent")
        _seed_session(tmp_path, "native-child", forge_root=fr)

        parent_dir = fr / ".forge" / "prev_sessions" / "parent"
        children_dir = parent_dir / "children"
        children_dir.mkdir(parents=True)
        (parent_dir / "generated.md").write_text("# Cache")
        stale = children_dir / "native-child.md"
        stale.write_text("# Stale context")

        ref_set = {("parent", str(fr)), ("native-child", str(fr))}
        result = _detect_orphan_transfer_files(ref_set, {fr})

        assert result.count == 1
        assert result.items == [str(stale)]

    def test_ignores_non_md_files(self, tmp_path: Path) -> None:
        fr = tmp_path / "project"
        prev_dir = fr / ".forge" / "prev_sessions"
        prev_dir.mkdir(parents=True)
        (prev_dir / "data.json").write_text("{}")

        result = _detect_orphan_transfer_files(set(), {fr})
        assert result.count == 0


# ---------------------------------------------------------------------------
# Codex-session transfer pinning (codex_frontend Phase 2)
# ---------------------------------------------------------------------------


def _seed_codex_child_files(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Index planner + a codex-runtime impl whose derivation references its snapshot.

    Returns (forge_root, real_child, notes_overlay, synthetic_leftover).
    """
    from forge.session import SessionStore, create_session_state
    from forge.session.models import Derivation

    fr = _seed_session(tmp_path, "planner")
    _seed_session(tmp_path, "impl", forge_root=fr)
    state = create_session_state("impl", worktree_path=str(fr), runtime="codex")
    state.forge_root = str(fr)
    state.confirmed.derivation = Derivation(
        parent_session="planner",
        resume_mode="transfer",
        context_file=".forge/prev_sessions/planner/children/impl.md",
    )
    SessionStore(str(fr), "impl").write(state)

    parent_dir = fr / ".forge" / "prev_sessions" / "planner"
    children = parent_dir / "children"
    children.mkdir(parents=True)
    (parent_dir / "generated.md").write_text("# Cache")
    real_child = children / "impl.md"
    real_child.write_text("# Codex transfer context")
    notes = children / "impl.notes.md"
    notes.write_text("# User notes")
    # Pre-Phase-2 manual bridge runs keyed snapshots by synthetic per-run child
    # names; no derivation references them, so they are plain orphans.
    synthetic = children / "planner-codex-abc123.md"
    synthetic.write_text("# Synthetic child")
    return fr, real_child, notes, synthetic


class TestCodexTransferPinning:
    """The Phase 2 start op keys snapshots by real session name; GC must keep
    those (and their notes overlays) while still sweeping the synthetic
    per-run children the manual bridge used to leak."""

    def test_synthetic_child_flagged_real_child_and_notes_survive(self, tmp_path: Path) -> None:
        fr, _real_child, _notes, synthetic = _seed_codex_child_files(tmp_path)

        ref_set = {("planner", str(fr)), ("impl", str(fr))}
        result = _detect_orphan_transfer_files(ref_set, {fr})

        assert result.items == [str(synthetic)]

    def test_run_clean_removes_synthetic_keeps_codex_child(self, tmp_path: Path) -> None:
        fr, real_child, notes, synthetic = _seed_codex_child_files(tmp_path)

        ctx = _make_ctx(tmp_path, forge_root=fr)
        result = run_clean(ctx=ctx, scope="workspace")

        assert "transfer_files" in result.categories_cleaned
        assert not synthetic.exists()
        assert real_child.is_file()
        assert notes.is_file()


# ---------------------------------------------------------------------------
# _detect_stale_active_entries
# ---------------------------------------------------------------------------


class TestDetectStaleActiveEntries:
    def test_no_entries(self, tmp_path: Path) -> None:
        result = _detect_stale_active_entries({tmp_path})
        assert result.count == 0

    def test_detects_dead_pid(self, tmp_path: Path) -> None:
        from forge.session.active import ActiveSessionStore
        from forge.session.config import LAUNCH_MODE_HOST

        store = ActiveSessionStore()
        store.upsert_session(
            session_name="dead-session",
            worktree_path=str(tmp_path),
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=999999,  # almost certainly dead
        )

        result = _detect_stale_active_entries({tmp_path})
        assert result.count == 1
        # Items encoded as "name::forge_root" for scoped cleanup
        assert any(item.startswith("dead-session::") for item in result.items)


# ---------------------------------------------------------------------------
# _detect_stale_work_queue
# ---------------------------------------------------------------------------


class TestDetectStaleWorkQueue:
    def test_no_markers(self, tmp_path: Path) -> None:
        result = _detect_stale_work_queue(set(), {tmp_path})
        assert result.count == 0

    def test_detects_orphan_marker(self, tmp_path: Path) -> None:
        queue_dir = _forge_home() / "pending-work"
        queue_dir.mkdir(parents=True)
        marker = {
            "schema_version": 1,
            "kind": "stop",
            "marker_id": "test-marker",
            "payload": {
                "session_name": "deleted-session",
                "worktree_path": str(tmp_path),
            },
        }
        (queue_dir / "test-marker.json").write_text(json.dumps(marker))

        # No sessions in ref_set
        result = _detect_stale_work_queue(set(), {tmp_path})
        assert result.count == 1

    def test_skips_valid_marker(self, tmp_path: Path) -> None:
        queue_dir = _forge_home() / "pending-work"
        queue_dir.mkdir(parents=True)
        marker = {
            "schema_version": 1,
            "kind": "stop",
            "marker_id": "test-marker",
            "payload": {
                "session_name": "alive-session",
                "worktree_path": str(tmp_path),
            },
        }
        (queue_dir / "test-marker.json").write_text(json.dumps(marker))

        ref_set = {("alive-session", str(tmp_path))}
        result = _detect_stale_work_queue(ref_set, {tmp_path})
        assert result.count == 0

    def test_scopes_by_worktree_path(self, tmp_path: Path) -> None:
        queue_dir = _forge_home() / "pending-work"
        queue_dir.mkdir(parents=True)
        marker = {
            "schema_version": 1,
            "kind": "stop",
            "marker_id": "other-project",
            "payload": {
                "session_name": "deleted-session",
                "worktree_path": "/some/other/project",
            },
        }
        (queue_dir / "other-project.json").write_text(json.dumps(marker))

        # Scope roots don't include /some/other/project
        result = _detect_stale_work_queue(set(), {tmp_path})
        assert result.count == 0

    def test_valid_marker_survives_when_forge_root_differs_from_worktree(self, tmp_path: Path) -> None:
        queue_dir = _forge_home() / "pending-work"
        queue_dir.mkdir(parents=True)

        forge_root = tmp_path / "forge-project"
        worktree_path = tmp_path / "checkout"
        marker = {
            "schema_version": 1,
            "kind": "stop",
            "marker_id": "live-marker",
            "payload": {
                "session_name": "alive-session",
                "worktree_path": str(worktree_path),
            },
        }
        (queue_dir / "live-marker.json").write_text(json.dumps(marker))

        forge_ref_set = {("alive-session", str(forge_root))}
        assert _detect_stale_work_queue(forge_ref_set, {tmp_path}).count == 1

        worktree_ref_set = {("alive-session", str(worktree_path))}
        assert _detect_stale_work_queue(worktree_ref_set, {tmp_path}).count == 0


# ---------------------------------------------------------------------------
# _path_in_roots
# ---------------------------------------------------------------------------


class TestPathInRoots:
    def test_exact_match(self, tmp_path: Path) -> None:
        assert _path_in_roots(tmp_path, {tmp_path}) is True

    def test_child_match(self, tmp_path: Path) -> None:
        child = tmp_path / "sub" / "dir"
        child.mkdir(parents=True)
        assert _path_in_roots(child, {tmp_path}) is True

    def test_no_match(self, tmp_path: Path) -> None:
        other = tmp_path.parent / "other"
        assert _path_in_roots(other, {tmp_path}) is False

    def test_empty_roots_matches_nothing(self, tmp_path: Path) -> None:
        """Empty root set returns False to prevent scope widening (P1 fix)."""
        assert _path_in_roots(tmp_path, set()) is False


# ---------------------------------------------------------------------------
# collect_clean_report
# ---------------------------------------------------------------------------


class TestCollectCleanReport:
    def test_clean_repo(self, tmp_path: Path) -> None:

        fr = _seed_session(tmp_path, "alpha")
        ctx = _make_ctx(tmp_path, forge_root=fr)
        report = collect_clean_report(ctx=ctx, scope="workspace")
        assert isinstance(report, CleanReport)
        assert report.is_clean

    def test_invalid_scope_raises(self, tmp_path: Path) -> None:

        ctx = _make_ctx(tmp_path)
        with pytest.raises(CleanError, match="Invalid scope"):
            collect_clean_report(ctx=ctx, scope="invalid")

    def test_scope_project_no_forge_root_raises(self, tmp_path: Path) -> None:

        ctx = _make_ctx(tmp_path, forge_root=None)
        with pytest.raises(CleanError, match="Not inside a Forge project"):
            collect_clean_report(ctx=ctx, scope="project")

    def test_detects_orphan_session_dir(self, tmp_path: Path) -> None:

        fr = _seed_session(tmp_path, "alpha")

        # Create orphan
        orphan = fr / ".forge" / "sessions" / "ghost"
        orphan.mkdir(parents=True)
        (orphan / "forge.session.json").write_text("{}")

        ctx = _make_ctx(tmp_path, forge_root=fr)
        report = collect_clean_report(ctx=ctx, scope="workspace")
        session_cat = next(c for c in report.categories if c.category == "session_dirs")
        assert session_cat.count == 1

    def test_broken_skill_name_discovery_does_not_block_other_cleanup_categories(self, tmp_path: Path) -> None:
        fr = _seed_session(tmp_path, "alpha")
        orphan = fr / ".forge" / "sessions" / "ghost"
        orphan.mkdir(parents=True)
        (orphan / "forge.session.json").write_text("{}", encoding="utf-8")
        ctx = _make_ctx(tmp_path, forge_root=fr)

        with patch(
            "forge.install.skill_compiler.discover_skill_source_names",
            side_effect=OSError("broken source tree"),
        ):
            report = collect_clean_report(ctx=ctx, scope="workspace")

        session_cat = next(category for category in report.categories if category.category == "session_dirs")
        assert session_cat.items == [str(orphan)]


# ---------------------------------------------------------------------------
# run_clean
# ---------------------------------------------------------------------------


class TestRunClean:
    def test_cleans_orphan_session_dir(self, tmp_path: Path) -> None:

        fr = _seed_session(tmp_path, "alpha")

        orphan = fr / ".forge" / "sessions" / "ghost"
        orphan.mkdir(parents=True)
        (orphan / "forge.session.json").write_text("{}")
        assert orphan.exists()

        ctx = _make_ctx(tmp_path, forge_root=fr)
        result = run_clean(ctx=ctx, scope="workspace")

        assert result.deleted_count >= 1
        assert not orphan.exists()
        assert "session_dirs" in result.categories_cleaned

    def test_cleans_orphan_handoff_file(self, tmp_path: Path) -> None:
        # Orphan parent dir (parent not in index) -- whole dir is cleaned.
        fr = _seed_session(tmp_path, "alpha")

        orphan_parent = fr / ".forge" / "prev_sessions" / "deleted-parent"
        orphan_parent.mkdir(parents=True)
        (orphan_parent / "generated.md").write_text("# Stale cache")
        (orphan_parent / "children").mkdir()
        (orphan_parent / "children" / "deleted-child.md").write_text("# Stale child")
        assert orphan_parent.exists()

        ctx = _make_ctx(tmp_path, forge_root=fr)
        result = run_clean(ctx=ctx, scope="workspace")

        assert result.deleted_count >= 1
        assert not orphan_parent.exists()
        assert "transfer_files" in result.categories_cleaned

    def test_cleans_empty_dirs_after_child_unlink(self, tmp_path: Path) -> None:
        # Removing the last orphan child should also prune empty children/ and
        # the parent dir (which only has the generated.md cache left).
        fr = _seed_session(tmp_path, "alpha")

        parent_dir = fr / ".forge" / "prev_sessions" / "alpha"
        parent_dir.mkdir(parents=True)
        (parent_dir / "generated.md").write_text("# Cache")
        children_dir = parent_dir / "children"
        children_dir.mkdir()
        (children_dir / "deleted-child.md").write_text("# Orphan")

        ctx = _make_ctx(tmp_path, forge_root=fr)
        result = run_clean(ctx=ctx, scope="workspace")

        assert "transfer_files" in result.categories_cleaned
        # children/ removed; parent dir removed because only generated.md remained
        assert not children_dir.exists()
        assert not parent_dir.exists()

    def test_nothing_to_clean(self, tmp_path: Path) -> None:

        fr = _seed_session(tmp_path, "alpha")
        ctx = _make_ctx(tmp_path, forge_root=fr)
        result = run_clean(ctx=ctx, scope="workspace")
        assert result.deleted_count == 0
        assert not result.failed

    @staticmethod
    def _category(report: CleanReport) -> OrphanCategory:
        return next(category for category in report.categories if category.category == "unmanaged_skill_packages")

    def test_scope_mapping_deduplicates_project_targets_and_adds_user_only_for_all(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        (project / ".forge").mkdir(parents=True)
        project_codex = _write_marked_skill_package(project / ".agents" / "skills")
        project_claude = _write_marked_skill_package(
            project / ".claude" / "skills",
            runtime="claude_code",
        )
        user_codex = _write_marked_skill_package(Path.home() / ".agents" / "skills")
        user_claude = _write_marked_skill_package(
            Path(os.environ["CLAUDE_HOME"]) / "skills",
            runtime="claude_code",
        )
        ctx = _make_ctx(tmp_path, forge_root=project)

        project_report = collect_clean_report(ctx=ctx, scope="project")
        workspace_report = collect_clean_report(ctx=ctx, scope="workspace")
        all_report = collect_clean_report(ctx=ctx, scope="all")

        project_items = self._category(project_report).items
        assert project_items == sorted([str(project_claude), str(project_codex)])
        assert self._category(workspace_report).items == project_items
        assert self._category(all_report).items == sorted(
            [str(project_claude), str(project_codex), str(user_claude), str(user_codex)]
        )

        result = run_clean(ctx=ctx, scope="all")

        assert result.categories_cleaned["unmanaged_skill_packages"] == 4
        assert not any(path.exists() for path in (project_claude, project_codex, user_claude, user_codex))

    def test_all_scope_does_not_discover_project_root_after_every_reference_is_lost(self, tmp_path: Path) -> None:
        current_project = tmp_path / "current"
        lost_project = tmp_path / "lost"
        (current_project / ".forge").mkdir(parents=True)
        (lost_project / ".forge").mkdir(parents=True)
        current_package = _write_marked_skill_package(current_project / ".agents" / "skills")
        lost_package = _write_marked_skill_package(lost_project / ".agents" / "skills")
        ctx = _make_ctx(current_project, forge_root=current_project)

        report = collect_clean_report(ctx=ctx, scope="all")

        assert self._category(report).items == [str(current_package)]

        result = run_clean(ctx=ctx, scope="all")

        assert result.categories_cleaned["unmanaged_skill_packages"] == 1
        assert not current_package.exists()
        assert lost_package.is_dir()

    def test_unmarked_package_is_status_only_and_never_in_clean_report(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        package = project / ".agents" / "skills" / "understand"
        package.mkdir(parents=True)
        (package / "SKILL.md").write_text("pre-marker output\n", encoding="utf-8")
        (project / ".forge").mkdir()
        ctx = _make_ctx(tmp_path, forge_root=project)

        report = collect_clean_report(ctx=ctx, scope="project")
        result = run_clean(ctx=ctx, scope="project")

        assert self._category(report).items == []
        assert "unmanaged_skill_packages" not in result.categories_cleaned
        assert package.is_dir()

    def test_cache_reset_dangling_package_is_listed_and_removed_without_following_links(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        (project / ".forge").mkdir(parents=True)
        package = _write_marked_skill_package(project / ".agents" / "skills")
        payload = package / "SKILL.md"
        payload.unlink()
        missing_cache_payload = (
            _forge_home() / "cache" / "compiled-skills" / "v1" / "codex" / package.name / ("a" * 64) / "SKILL.md"
        )
        payload.symlink_to(missing_cache_payload)
        ctx = _make_ctx(tmp_path, forge_root=project)

        preview = collect_clean_report(ctx=ctx, scope="project")

        assert self._category(preview).items == [str(package)]
        assert len(preview._unmanaged_records) == 1
        assert preview._unmanaged_records[0].shape == "partial"
        assert payload.is_symlink() and not payload.exists()

        result = run_clean(ctx=ctx, scope="project")

        assert result.categories_cleaned["unmanaged_skill_packages"] == 1
        assert not package.exists()
        assert not missing_cache_payload.exists()

    def test_incompatible_project_stays_counted_and_global_user_package_cleans(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        (project / ".forge").mkdir(parents=True)
        (project / ".forge" / "project.toml").write_text(
            'schema_version = 1\nrequired_forge = ">=9999"\n',
            encoding="utf-8",
        )
        project_package = _write_marked_skill_package(project / ".agents" / "skills")
        user_package = _write_marked_skill_package(Path.home() / ".agents" / "skills")
        ctx = _make_ctx(tmp_path, forge_root=project)

        preview = collect_clean_report(ctx=ctx, scope="all")

        assert self._category(preview).count == 2
        assert [skip.target for skip in preview.skipped_project_compatibility] == [str(project_package)]

        result = run_clean(ctx=ctx, scope="all")

        assert project_package.is_dir()
        assert not user_package.exists()
        assert result.categories_cleaned["unmanaged_skill_packages"] == 1
        assert [skip.target for skip in result.skipped_project_compatibility] == [str(project_package)]
        assert result.should_exit_nonzero is True

    def test_pre_scan_ownership_change_is_omitted_without_failure(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        (project / ".forge").mkdir(parents=True)
        package = _write_marked_skill_package(project / ".agents" / "skills")
        ctx = _make_ctx(tmp_path, forge_root=project)
        preview = collect_clean_report(ctx=ctx, scope="project")
        assert self._category(preview).items == [str(package)]
        _claim_project_package(project, package)

        result = run_clean(ctx=ctx, scope="project")

        assert package.is_dir()
        assert "unmanaged_skill_packages" not in result.categories_cleaned
        assert result.failed == []

    def test_post_scan_ownership_drift_fails_and_preserves_package(self, tmp_path: Path) -> None:
        from forge.core.ops import gc as gc_module

        project = tmp_path / "project"
        (project / ".forge").mkdir(parents=True)
        package = _write_marked_skill_package(project / ".agents" / "skills")
        ctx = _make_ctx(tmp_path, forge_root=project)
        original = gc_module.revalidate_cleanup_candidate

        def claim_then_revalidate(*args: Any, **kwargs: Any):
            _claim_project_package(project, package)
            return original(*args, **kwargs)

        with patch(
            "forge.core.ops.gc.revalidate_cleanup_candidate",
            side_effect=claim_then_revalidate,
        ):
            result = run_clean(ctx=ctx, scope="project")

        assert package.is_dir()
        assert result.categories_cleaned.get("unmanaged_skill_packages", 0) == 0
        assert result.failed and result.failed[0][0] == str(package)
        assert result.should_exit_nonzero is True

    @pytest.mark.parametrize("drift", ["contents", "coherent-replacement", "path-type", "parent-path-type"])
    def test_post_scan_filesystem_drift_fails_and_preserves_replacement(
        self,
        tmp_path: Path,
        drift: str,
    ) -> None:
        from forge.core.ops import gc as gc_module

        project = tmp_path / "project"
        (project / ".forge").mkdir(parents=True)
        package = _write_marked_skill_package(project / ".agents" / "skills")
        ctx = _make_ctx(tmp_path, forge_root=project)
        original = gc_module.revalidate_cleanup_candidate
        external = tmp_path / "operator-owned"

        def drift_then_revalidate(*args: Any, **kwargs: Any):
            if drift == "contents":
                (package / "operator.txt").write_text("keep\n", encoding="utf-8")
            elif drift == "coherent-replacement":
                shutil.rmtree(package)
                replacement = _write_marked_skill_package(package.parent, content=b"replacement\n")
                assert replacement == package
            elif drift == "path-type":
                shutil.rmtree(package)
                external.mkdir()
                (external / "keep.txt").write_text("keep\n", encoding="utf-8")
                package.symlink_to(external, target_is_directory=True)
            else:
                skill_root = package.parent
                shutil.rmtree(skill_root)
                replacement = _write_marked_skill_package(external)
                skill_root.symlink_to(external, target_is_directory=True)
                assert replacement == external / package.name
            return original(*args, **kwargs)

        with patch(
            "forge.core.ops.gc.revalidate_cleanup_candidate",
            side_effect=drift_then_revalidate,
        ):
            result = run_clean(ctx=ctx, scope="project")

        assert package.exists()
        if drift == "contents":
            assert (package / "operator.txt").is_file()
        elif drift == "coherent-replacement":
            assert (package / "SKILL.md").read_text(encoding="utf-8") == "replacement\n"
        elif drift == "path-type":
            assert package.is_symlink()
            assert (external / "keep.txt").is_file()
        else:
            assert package.parent.is_symlink()
            assert (external / package.name / "SKILL.md").is_file()
        assert result.failed and result.failed[0][0] == str(package)
        assert result.should_exit_nonzero is True

    def test_compatibility_drift_after_scan_fails_before_revalidation(self, tmp_path: Path) -> None:
        from forge.core.ops import gc as gc_module
        from forge.install.project_compat import ProjectCompatibilityError

        project = tmp_path / "project"
        (project / ".forge").mkdir(parents=True)
        package = _write_marked_skill_package(project / ".agents" / "skills")
        ctx = _make_ctx(tmp_path, forge_root=project)
        original = gc_module.enforce_project_compatibility
        calls = 0

        def become_incompatible(root: Path) -> object:
            nonlocal calls
            calls += 1
            if calls == 1:
                original(root)
                return None
            raise ProjectCompatibilityError(str(root), "compatibility changed", state="incompatible")

        with patch(
            "forge.core.ops.gc.enforce_project_compatibility",
            side_effect=become_incompatible,
        ):
            result = run_clean(ctx=ctx, scope="project")

        assert package.is_dir()
        assert result.failed and "compatibility changed" in result.failed[0][1]
        assert result.should_exit_nonzero is True

    def test_runtime_root_swap_after_package_revalidation_preserves_replacement(self, tmp_path: Path) -> None:
        from forge.core.ops import gc as gc_module

        project = tmp_path / "project"
        (project / ".forge").mkdir(parents=True)
        package = _write_marked_skill_package(project / ".agents" / "skills")
        skill_root = package.parent
        external_root = tmp_path / "operator-skills"
        ctx = _make_ctx(tmp_path, forge_root=project)
        original = gc_module.cleanup_proof_fingerprint
        calls = 0

        def swap_root_after_fingerprint(path: Path) -> str | None:
            nonlocal calls
            token = original(path)
            calls += 1
            if calls == 2:
                shutil.rmtree(skill_root)
                _write_marked_skill_package(external_root)
                skill_root.symlink_to(external_root, target_is_directory=True)
            return token

        with patch("forge.core.ops.gc.cleanup_proof_fingerprint", side_effect=swap_root_after_fingerprint):
            result = run_clean(ctx=ctx, scope="project")

        assert calls == 2
        assert skill_root.is_symlink()
        assert (external_root / package.name / "SKILL.md").is_file()
        assert result.failed and "runtime skill root changed" in result.failed[0][1]
        assert result.should_exit_nonzero is True

    def test_corrupt_tracking_requires_a_second_pass_before_packages_are_visible(self, tmp_path: Path) -> None:
        package = _write_marked_skill_package(Path.home() / ".agents" / "skills")
        tracking_path = TrackingStore().path
        tracking_path.parent.mkdir(parents=True, exist_ok=True)
        tracking_path.write_text("{corrupt", encoding="utf-8")
        ctx = _make_ctx(tmp_path)

        first = collect_clean_report(ctx=ctx, scope="all")

        assert [category.category for category in first.categories] == ["corrupt_state"]
        assert str(tracking_path) in first.categories[0].items
        assert package.is_dir()

        first_apply = run_clean(ctx=ctx, scope="all")
        assert first_apply.categories_cleaned["corrupt_state"] == 1
        assert package.is_dir()

        second = collect_clean_report(ctx=ctx, scope="all")
        assert self._category(second).items == [str(package)]

    @pytest.mark.parametrize(
        ("project_toml", "expected_state"),
        [
            ('schema_version = 1\nrequired_forge = ">=9999"\n', "incompatible"),
            ('schema_version = 1\nrequired_forge = "not a spec"\n', "malformed"),
            ('schema_version = 999\nrequired_forge = ">=0"\n', "unsupported_schema"),
        ],
    )
    def test_mixed_roots_skip_refused_project_and_clean_eligible_global_state(
        self,
        tmp_path: Path,
        project_toml: str,
        expected_state: str,
    ) -> None:
        from forge.backend.registry import get_backend_registry_path

        compatible_root = _seed_session(tmp_path, "compatible", tmp_path / "compatible")
        refused_root = _seed_session(tmp_path, "refused", tmp_path / "refused")

        compatible_orphan = compatible_root / ".forge" / "sessions" / "compatible-orphan"
        compatible_orphan.mkdir(parents=True)
        (compatible_orphan / "artifact.txt").write_text("stale")

        refused_orphan = refused_root / ".forge" / "sessions" / "refused-orphan"
        refused_orphan.mkdir(parents=True)
        (refused_orphan / "artifact.txt").write_text("stale")
        (refused_root / ".forge" / "project.toml").write_text(project_toml)

        # Corrupt backend registry is global Forge state, so a refused project
        # must not prevent this independently eligible repair.
        backend_registry = get_backend_registry_path()
        backend_registry.parent.mkdir(parents=True, exist_ok=True)
        backend_registry.write_text("{")

        result = run_clean(
            ctx=_make_ctx(tmp_path, forge_root=compatible_root),
            scope="all",
        )

        assert not compatible_orphan.exists()
        assert refused_orphan.exists()
        assert not backend_registry.exists()
        assert result.categories_cleaned["session_dirs"] == 1
        assert result.categories_cleaned["corrupt_state"] == 1
        assert len(result.skipped_project_compatibility) == 1
        skip = result.skipped_project_compatibility[0]
        assert skip.target == str(refused_orphan)
        assert skip.forge_root == str(refused_root.resolve())
        assert skip.state == expected_state
        assert skip.reason
        assert skip.recovery
        assert result.should_exit_nonzero is True

    def test_preview_reports_refusal_without_mutating_project_item(self, tmp_path: Path) -> None:
        refused_root = _seed_session(tmp_path, "refused")
        refused_orphan = refused_root / ".forge" / "sessions" / "refused-orphan"
        refused_orphan.mkdir(parents=True)
        (refused_orphan / "artifact.txt").write_text("stale")
        (refused_root / ".forge" / "project.toml").write_text('schema_version = 1\nrequired_forge = ">=9999"\n')

        report = collect_clean_report(
            ctx=_make_ctx(tmp_path, forge_root=refused_root),
            scope="workspace",
        )

        assert refused_orphan.exists()
        assert len(report.skipped_project_compatibility) == 1
        skip = report.skipped_project_compatibility[0]
        assert skip.target == str(refused_orphan)
        assert skip.forge_root == str(refused_root.resolve())
        assert skip.state == "incompatible"

    def test_search_cleanup_uses_store_root_for_external_transcript_paths(self, tmp_path: Path) -> None:
        from forge.search.extractor import SearchDocumentMeta
        from forge.search.store import SearchDocumentStore

        compatible_root = _seed_session(tmp_path, "compatible", tmp_path / "compatible")
        refused_root = _seed_session(tmp_path, "refused", tmp_path / "refused")
        compatible_missing = tmp_path / "external" / "compatible.jsonl"
        refused_missing = tmp_path / "external" / "refused.jsonl"

        def _doc(path: Path, name: str) -> SearchDocumentMeta:
            return SearchDocumentMeta(
                transcript_path=str(path),
                session_name=name,
                session_id=f"{name}-id",
                extracted_at="2026-01-01T00:00:00+00:00",
            )

        compatible_store = SearchDocumentStore(forge_root=compatible_root)
        refused_store = SearchDocumentStore(forge_root=refused_root)
        compatible_store.write([_doc(compatible_missing, "compatible")])
        refused_store.write([_doc(refused_missing, "refused")])
        (refused_root / ".forge" / "project.toml").write_text('schema_version = 1\nrequired_forge = ">=9999"\n')

        result = run_clean(
            ctx=_make_ctx(tmp_path, forge_root=compatible_root),
            scope="all",
        )

        assert compatible_store.read() == []
        assert [doc.transcript_path for doc in refused_store.read()] == [str(refused_missing)]
        assert result.categories_cleaned["search_docs"] == 1
        assert [skip.target for skip in result.skipped_project_compatibility] == [str(refused_missing)]
        assert result.skipped_project_compatibility[0].forge_root == str(refused_root.resolve())

    def test_search_cleanup_distinguishes_duplicate_path_by_store_root(self, tmp_path: Path) -> None:
        from forge.search.extractor import SearchDocumentMeta
        from forge.search.store import SearchDocumentStore

        compatible_root = _seed_session(tmp_path, "compatible", tmp_path / "compatible")
        refused_root = _seed_session(tmp_path, "refused", tmp_path / "refused")
        shared_missing = tmp_path / "external" / "shared.jsonl"
        shared_doc = SearchDocumentMeta(
            transcript_path=str(shared_missing),
            session_name="shared",
            session_id="shared-id",
            extracted_at="2026-01-01T00:00:00+00:00",
        )
        compatible_store = SearchDocumentStore(forge_root=compatible_root)
        refused_store = SearchDocumentStore(forge_root=refused_root)
        compatible_store.write([shared_doc])
        refused_store.write([shared_doc])
        (refused_root / ".forge" / "project.toml").write_text('schema_version = 1\nrequired_forge = ">=9999"\n')

        result = run_clean(
            ctx=_make_ctx(tmp_path, forge_root=compatible_root),
            scope="all",
        )

        assert compatible_store.read() == []
        assert [doc.transcript_path for doc in refused_store.read()] == [str(shared_missing)]
        assert result.categories_cleaned["search_docs"] == 1
        assert len(result.skipped_project_compatibility) == 1
        skip = result.skipped_project_compatibility[0]
        assert skip.target == str(shared_missing)
        assert skip.forge_root == str(refused_root.resolve())

    def test_search_preview_records_each_refused_owner_for_shared_path(self, tmp_path: Path) -> None:
        from forge.search.extractor import SearchDocumentMeta
        from forge.search.store import SearchDocumentStore

        first_root = _seed_session(tmp_path, "first", tmp_path / "first")
        second_root = _seed_session(tmp_path, "second", tmp_path / "second")
        shared_missing = tmp_path / "external" / "shared.jsonl"
        shared_doc = SearchDocumentMeta(
            transcript_path=str(shared_missing),
            session_name="shared",
            session_id="shared-id",
            extracted_at="2026-01-01T00:00:00+00:00",
        )
        for forge_root in (first_root, second_root):
            SearchDocumentStore(forge_root=forge_root).write([shared_doc])
            (forge_root / ".forge" / "project.toml").write_text('schema_version = 1\nrequired_forge = ">=9999"\n')

        report = collect_clean_report(
            ctx=_make_ctx(tmp_path, forge_root=first_root),
            scope="all",
        )

        assert {
            (skip.target, skip.forge_root)
            for skip in report.skipped_project_compatibility
            if skip.target == str(shared_missing)
        } == {
            (str(shared_missing), str(first_root.resolve())),
            (str(shared_missing), str(second_root.resolve())),
        }

    def test_search_compatibility_reuses_owner_data_from_detection(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from forge.search.extractor import SearchDocumentMeta
        from forge.search.store import SearchDocumentStore

        compatible_root = _seed_session(tmp_path, "compatible", tmp_path / "compatible")
        refused_root = _seed_session(tmp_path, "refused", tmp_path / "refused")

        def _docs(root: Path) -> list[SearchDocumentMeta]:
            return [
                SearchDocumentMeta(
                    transcript_path=str(tmp_path / "external" / f"{root.name}-{index}.jsonl"),
                    session_name=f"{root.name}-{index}",
                    session_id=f"{root.name}-{index}-id",
                    extracted_at="2026-01-01T00:00:00+00:00",
                )
                for index in range(3)
            ]

        compatible_store = SearchDocumentStore(forge_root=compatible_root)
        refused_store = SearchDocumentStore(forge_root=refused_root)
        compatible_store.write(_docs(compatible_root))
        refused_store.write(_docs(refused_root))
        (refused_root / ".forge" / "project.toml").write_text('schema_version = 1\nrequired_forge = ">=9999"\n')

        real_read = SearchDocumentStore.read
        read_counts: dict[Path, int] = {}

        def _counted_read(store: SearchDocumentStore) -> list[SearchDocumentMeta]:
            read_counts[store.store_path] = read_counts.get(store.store_path, 0) + 1
            return real_read(store)

        monkeypatch.setattr(SearchDocumentStore, "read", _counted_read)

        report = collect_clean_report(
            ctx=_make_ctx(tmp_path, forge_root=compatible_root),
            scope="all",
        )

        assert report.total_count >= 6
        assert len(report.skipped_project_compatibility) == 3
        assert read_counts == {
            compatible_store.store_path: 1,
            refused_store.store_path: 1,
        }

    def test_unreadable_pin_is_a_structured_project_skip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        forge_root = tmp_path / "project"
        pin = forge_root / ".forge" / "project.toml"
        pin.parent.mkdir(parents=True)
        pin.write_text('schema_version = 1\nrequired_forge = ">=0"\n')
        target = forge_root / ".forge" / "sessions" / "ghost"
        real_open = Path.open

        def _open(path: Path, *args: Any, **kwargs: Any) -> Any:
            if path == pin:
                raise PermissionError("denied")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", _open)

        skips = _project_compatibility_skips(
            [OrphanCategory("session_dirs", "orphans", 1, [str(target)])],
            {forge_root},
        )

        assert len(skips) == 1
        assert skips[0].target == str(target)
        assert skips[0].forge_root == str(forge_root.resolve())
        assert skips[0].state == "unreadable"
        assert "read error" in skips[0].reason

    def test_unmanaged_user_owner_metadata_overrides_path_containment(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        package = project / "nested-home" / ".agents" / "skills" / "understand"
        category = OrphanCategory(
            "unmanaged_skill_packages",
            "verified packages",
            1,
            [str(package)],
        )

        with patch("forge.core.ops.gc.enforce_project_compatibility") as enforce:
            skips = _project_compatibility_skips(
                [category],
                {project},
                unmanaged_project_owners={str(package): None},
            )

        assert skips == []
        enforce.assert_not_called()

    def test_pending_work_marker_is_gated_by_payload_forge_root(self, tmp_path: Path) -> None:
        forge_root = _seed_session(tmp_path, "live")
        (forge_root / ".forge" / "project.toml").write_text('schema_version = 1\nrequired_forge = ">=9999"\n')
        queue_dir = _forge_home() / "pending-work"
        queue_dir.mkdir(parents=True)
        marker = queue_dir / "orphan.json"
        marker.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "index",
                    "marker_id": "orphan",
                    "payload": {
                        "session_name": "gone",
                        "worktree_path": str(forge_root),
                        "forge_root": str(forge_root),
                    },
                }
            )
        )

        result = run_clean(
            ctx=_make_ctx(tmp_path, forge_root=forge_root),
            scope="workspace",
        )

        assert marker.exists()
        assert [skip.target for skip in result.skipped_project_compatibility] == [str(marker)]
        assert result.skipped_project_compatibility[0].forge_root == str(forge_root.resolve())


# ---------------------------------------------------------------------------
# Edge case tests (P1-P3 fixes)
# ---------------------------------------------------------------------------


class TestEmptyRootRepoScope:
    """P1: repo scope with no tracked roots should not widen to global."""

    def test_empty_repo_no_active_cleanup(self, tmp_path: Path) -> None:
        """Active entries outside scope are untouched when no roots found."""
        from forge.session.active import ActiveSessionStore
        from forge.session.config import LAUNCH_MODE_HOST

        # Create a stale active entry pointing to some other project
        store = ActiveSessionStore()
        store.upsert_session(
            session_name="other-project-session",
            worktree_path="/some/other/project",
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=999999,
        )

        # Run clean from a repo with no forge roots
        ctx = _make_ctx(tmp_path, forge_root=None)
        report = collect_clean_report(ctx=ctx, scope="workspace")
        active_cat = next(c for c in report.categories if c.category == "active_entries")
        assert active_cat.count == 0, "should not detect entries outside scope"

    def test_empty_repo_no_workqueue_cleanup(self, tmp_path: Path) -> None:
        """Work queue markers outside scope are untouched when no roots found."""
        queue_dir = _forge_home() / "pending-work"
        queue_dir.mkdir(parents=True)

        marker = {
            "schema_version": 1,
            "kind": "stop",
            "marker_id": "foreign",
            "payload": {"session_name": "gone", "worktree_path": "/other/repo"},
        }
        (queue_dir / "foreign.json").write_text(json.dumps(marker))

        ctx = _make_ctx(tmp_path, forge_root=None)
        report = collect_clean_report(ctx=ctx, scope="workspace")
        wq_cat = next(c for c in report.categories if c.category == "work_queue")
        assert wq_cat.count == 0


class TestScopedActiveCleanup:
    """P1: active cleanup should only remove detected entries, not global."""

    def test_only_scoped_entries_removed(self, tmp_path: Path) -> None:
        from forge.session.active import ActiveSessionStore
        from forge.session.config import LAUNCH_MODE_HOST

        store = ActiveSessionStore()

        # Stale entry IN scope
        fr = _seed_session(tmp_path, "alpha")
        store.upsert_session(
            session_name="in-scope-dead",
            worktree_path=str(fr),
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=999999,
        )
        # Stale entry OUTSIDE scope
        store.upsert_session(
            session_name="out-of-scope-dead",
            worktree_path="/other/project",
            launch_mode=LAUNCH_MODE_HOST,
            launcher_pid=999998,
        )

        ctx = _make_ctx(tmp_path, forge_root=fr)
        run_clean(ctx=ctx, scope="workspace")

        # in-scope should be cleaned
        assert store.get_session("in-scope-dead") is None
        # out-of-scope should survive (keys are scoped compound keys)
        remaining = store.read()
        assert any(k.startswith("out-of-scope-dead|") for k in remaining.sessions)


class TestYesJsonMode:
    """P2: --yes --json should actually perform cleanup."""

    def test_yes_json_runs_clean(self) -> None:
        from forge.core.ops.gc import CleanResult

        report = _make_report_with_orphans(1)
        clean_result = CleanResult(categories_cleaned={"session_dirs": 1}, failed=[])

        with (
            patch("forge.cli.gc.ExecutionContext.from_cwd"),
            patch("forge.cli.gc.collect_clean_report", return_value=report),
            patch("forge.cli.gc.run_clean", return_value=clean_result) as mock_run,
        ):
            from click.testing import CliRunner

            from forge.cli.gc import clean_cmd

            runner = CliRunner()
            result = runner.invoke(clean_cmd, ["--yes", "--json"])
            assert result.exit_code == 0
            mock_run.assert_called_once()
            data = json.loads(result.output)
            assert data["dry_run"] is False
            assert data["deleted"] == 1

    def test_json_dryrun_does_not_clean(self) -> None:
        report = _make_report_with_orphans(1)

        with (
            patch("forge.cli.gc.ExecutionContext.from_cwd"),
            patch("forge.cli.gc.collect_clean_report", return_value=report),
            patch("forge.cli.gc.run_clean") as mock_run,
        ):
            from click.testing import CliRunner

            from forge.cli.gc import clean_cmd

            runner = CliRunner()
            result = runner.invoke(clean_cmd, ["--json"])
            assert result.exit_code == 0
            mock_run.assert_not_called()
            data = json.loads(result.output)
            assert data["dry_run"] is True


class TestCrossRootNameReuse:
    """P2: name reuse across forge_roots for handoff and work-queue."""

    def test_handoff_name_reuse_across_roots(self, tmp_path: Path) -> None:
        """alpha parent dir in proj-a should not mask orphan alpha parent dir in proj-b."""
        fr_a = _seed_session(tmp_path, "alpha", tmp_path / "proj-a")
        fr_b = tmp_path / "proj-b"
        orphan_dir = fr_b / ".forge" / "prev_sessions" / "alpha"
        orphan_dir.mkdir(parents=True)
        (orphan_dir / "generated.md").write_text("stale")

        ref_set = {("alpha", str(fr_a))}
        result = _detect_orphan_transfer_files(ref_set, {fr_a, fr_b})
        assert result.count == 1
        assert "proj-b" in result.items[0]

    def test_workqueue_name_reuse_across_roots(self, tmp_path: Path) -> None:
        """Marker for alpha in proj-b should be stale even if alpha exists in proj-a."""
        fr_a = _seed_session(tmp_path, "alpha", tmp_path / "proj-a")

        queue_dir = _forge_home() / "pending-work"
        queue_dir.mkdir(parents=True)
        marker = {
            "schema_version": 1,
            "kind": "stop",
            "marker_id": "cross-root",
            "payload": {
                "session_name": "alpha",
                "worktree_path": str(tmp_path / "proj-b"),
            },
        }
        (queue_dir / "cross-root.json").write_text(json.dumps(marker))

        ref_set = {("alpha", str(fr_a))}
        scope_roots = {fr_a, tmp_path / "proj-b"}
        result = _detect_stale_work_queue(ref_set, scope_roots)
        assert result.count == 1


# ---------------------------------------------------------------------------
# Helpers for CLI tests
# ---------------------------------------------------------------------------


class TestDetectDeadInstallations:
    """Dead installed-manifest entries for paths that no longer exist."""

    def test_no_dead_entries(self, tmp_path: Path) -> None:
        result = _detect_dead_installations()
        assert result.count == 0

    def test_detects_dead_entry(self, tmp_path: Path) -> None:
        from forge.install.models import Installation
        from forge.install.tracking import TrackingStore

        store = TrackingStore()
        store.set_installation(
            "local",
            Installation(
                scope="local",
                mode="copy",
                profile="standard",
                project_path="/nonexistent/dead-worktree",
            ),
            project_path="/nonexistent/dead-worktree",
        )

        result = _detect_dead_installations()
        assert result.count == 1
        assert "dead-worktree" in result.items[0]

    def test_skips_live_entry(self, tmp_path: Path) -> None:
        from forge.install.models import Installation
        from forge.install.tracking import TrackingStore

        live_path = tmp_path / "alive"
        live_path.mkdir()
        store = TrackingStore()
        store.set_installation(
            "local",
            Installation(
                scope="local",
                mode="copy",
                profile="standard",
                project_path=str(live_path),
            ),
            project_path=str(live_path),
        )

        result = _detect_dead_installations()
        assert result.count == 0

    def test_run_clean_removes_dead_installation(self, tmp_path: Path) -> None:
        from forge.install.models import Installation
        from forge.install.tracking import TrackingStore

        store = TrackingStore()
        store.set_installation(
            "local",
            Installation(
                scope="local",
                mode="copy",
                profile="standard",
                project_path="/nonexistent/dead",
            ),
            project_path="/nonexistent/dead",
        )

        # Also need a forge_root for the run_clean context
        fr = _seed_session(tmp_path, "alpha")
        ctx = _make_ctx(tmp_path, forge_root=fr)
        result = run_clean(ctx=ctx, scope="all")

        assert "dead_installations" in result.categories_cleaned
        # Verify it was removed from the manifest
        manifest = store.read()
        assert len([i for _k, i in manifest.installations.items() if i.project_path == "/nonexistent/dead"]) == 0


# ---------------------------------------------------------------------------
# Helpers for CLI tests
# ---------------------------------------------------------------------------


def _make_report_with_orphans(total: int) -> CleanReport:
    """Build a CleanReport with orphan session dirs."""
    from forge.core.ops.gc import OrphanCategory

    cats = [
        OrphanCategory("session_dirs", "Orphan session dirs", total, ["/fake"] * total),
        OrphanCategory("transfer_files", "Orphan transfer files", 0, []),
        OrphanCategory("active_entries", "Stale active entries", 0, []),
        OrphanCategory("work_queue", "Stale work queue", 0, []),
        OrphanCategory("proxies", "Stale proxy entries", 0, []),
        OrphanCategory("search_docs", "Orphan search docs", 0, []),
        OrphanCategory("dead_installations", "Dead installations", 0, []),
    ]
    return CleanReport(categories=cats, scope="workspace")


# ---------------------------------------------------------------------------
# Corrupt-state detection (forge clean removes corrupt Forge state)
# ---------------------------------------------------------------------------


def _category(report: CleanReport, name: str) -> OrphanCategory:
    match = next((c for c in report.categories if c.category == name), None)
    return match or OrphanCategory(name, "", 0, [])


def _manifest_path(forge_root: Path, name: str) -> Path:
    return forge_root / ".forge" / "sessions" / name / "forge.session.json"


class TestCorruptState:
    def test_corrupt_manifest_detected_and_cleaned(self, tmp_path: Path) -> None:
        """A corrupt session manifest is flagged and its file removed (any scope)."""
        fr = _seed_session(tmp_path, "alpha")
        manifest = _manifest_path(fr, "alpha")
        manifest.write_text("{not valid json")
        ctx = _make_ctx(tmp_path, forge_root=fr)

        report = collect_clean_report(ctx=ctx, scope="workspace")
        corrupt = _category(report, "corrupt_state")
        assert corrupt.count == 1
        assert str(manifest) in corrupt.items

        result = run_clean(ctx=ctx, scope="workspace")
        assert result.categories_cleaned.get("corrupt_state") == 1
        assert not manifest.exists()

    def test_cleaned_manifest_lets_index_entry_self_heal(self, tmp_path: Path) -> None:
        """After the corrupt manifest is removed, the dangling index entry self-heals."""
        fr = _seed_session(tmp_path, "alpha")
        _manifest_path(fr, "alpha").write_text("garbage")
        ctx = _make_ctx(tmp_path, forge_root=fr)

        run_clean(ctx=ctx, scope="workspace")

        # list_sessions() prunes the entry whose manifest is now missing.
        assert IndexStore().list_sessions() == []

    def test_corrupt_manifest_detected_project_scope(self, tmp_path: Path) -> None:
        fr = _seed_session(tmp_path, "alpha")
        _manifest_path(fr, "alpha").write_text("nope")
        ctx = _make_ctx(tmp_path, forge_root=fr)

        report = collect_clean_report(ctx=ctx, scope="project")
        assert _category(report, "corrupt_state").count == 1

    def test_global_registry_corruption_detected_at_any_scope(self, tmp_path: Path) -> None:
        """A corrupt global registry is detected at every scope so plain `forge clean` recovers it.

        The corrupt-state handler tells users to run `forge clean` regardless of scope, so a
        corrupt global registry (a system-wide blocker) must surface even at the default
        workspace scope, not only under --scope all.
        """
        from forge.proxy.proxies import get_proxy_registry_path

        fr = _seed_session(tmp_path, "alpha")
        reg = get_proxy_registry_path()
        reg.parent.mkdir(parents=True, exist_ok=True)
        reg.write_text("{bad json")
        ctx = _make_ctx(tmp_path, forge_root=fr)

        for scope in ("workspace", "project", "all"):
            report = collect_clean_report(ctx=ctx, scope=scope)
            assert str(reg) in _category(report, "corrupt_state").items, scope

    def test_corrupt_index_reports_corrupt_state_only(self, tmp_path: Path) -> None:
        """A corrupt global index degrades to corrupt-state-only -- never flags every session dir."""
        from forge.session.index import get_index_path

        fr = _seed_session(tmp_path, "alpha")
        _seed_session(tmp_path, "beta", forge_root=fr)
        index_path = get_index_path()
        index_path.write_text("{corrupt index")
        ctx = _make_ctx(tmp_path, forge_root=fr)

        report = collect_clean_report(ctx=ctx, scope="all")
        # Orphan detectors are skipped: only corrupt_state runs, so the two
        # healthy session dirs are NOT proposed for deletion.
        assert [c.category for c in report.categories] == ["corrupt_state"]
        assert str(index_path) in _category(report, "corrupt_state").items

        result = run_clean(ctx=ctx, scope="all")
        assert result.categories_cleaned.get("corrupt_state") == 1
        assert not index_path.exists()

    def test_user_proxy_yaml_never_flagged_or_removed(self, tmp_path: Path) -> None:
        """User config (proxy.yaml) is never probed, flagged, or deleted by forge clean."""
        from forge.config.loader import get_proxy_file_path

        fr = _seed_session(tmp_path, "alpha")
        proxy_yaml = get_proxy_file_path("myproxy")
        proxy_yaml.parent.mkdir(parents=True, exist_ok=True)
        proxy_yaml.write_text("tiers: [unclosed")  # malformed user config
        ctx = _make_ctx(tmp_path, forge_root=fr)

        report = collect_clean_report(ctx=ctx, scope="all")
        items = _category(report, "corrupt_state").items
        assert all("proxy.yaml" not in item for item in items)

        run_clean(ctx=ctx, scope="all")
        assert proxy_yaml.exists()  # untouched
