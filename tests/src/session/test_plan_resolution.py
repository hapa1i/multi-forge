"""Tests for forge.session.plan_resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.session import IndexStore
from forge.session.models import Derivation, create_session_state
from forge.session.plan_resolution import (
    DisplayedPath,
    PlanInfo,
    latest_snapshot_path,
    preferred_plan_path,
    resolve_displayed_plan_path,
    resolve_path_against,
    resolve_plan_info,
)
from forge.session.store import SessionStore


@pytest.fixture
def forge_root(tmp_path: Path) -> Path:
    """A directory that looks like a Forge project root."""
    root = tmp_path / "project"
    root.mkdir()
    return root


def _write_manifest(
    forge_root: Path,
    name: str,
    *,
    plan_path: str | None = None,
    plans: list[dict] | None = None,
    derivation: Derivation | None = None,
) -> None:
    state = create_session_state(name)
    if plan_path is not None:
        state.confirmed.latest_plan_path = plan_path
    if plans is not None:
        state.confirmed.artifacts["plans"] = plans
    if derivation is not None:
        state.confirmed.derivation = derivation
    SessionStore(str(forge_root), name).write(state)


class TestResolvePlanInfoSelf:
    def test_self_draft(self) -> None:
        state = create_session_state("child")
        state.confirmed.latest_plan_path = ".claude/plans/foo.md"

        info = resolve_plan_info(state, current_forge_root="/irrelevant")

        assert info.source == "self"
        assert info.draft_path == ".claude/plans/foo.md"
        assert info.approved_snapshots == []
        assert info.parent_session is None

    def test_self_with_snapshots(self) -> None:
        state = create_session_state("child")
        snap = {
            "kind": "approved",
            "captured_at": "2026-04-16T12:00:00Z",
            "source_path": ".claude/plans/foo.md",
            "snapshot_path": ".forge/artifacts/child/plans/2026-04-16T12-00-00.md",
        }
        state.confirmed.artifacts["plans"] = [snap]

        info = resolve_plan_info(state, current_forge_root="/irrelevant")

        assert info.source == "self"
        assert info.approved_snapshots == [snap]
        assert info.draft_path is None


class TestResolvePlanInfoParent:
    def test_parent_fallback_same_forge_root(self, forge_root: Path) -> None:
        _write_manifest(forge_root, "planner", plan_path=".claude/plans/p.md")

        child = create_session_state("executor")
        child.confirmed.derivation = Derivation(parent_session="planner")

        info = resolve_plan_info(child, current_forge_root=str(forge_root))

        assert info.source == "parent"
        assert info.parent_session == "planner"
        assert info.parent_forge_root == str(forge_root)
        assert info.draft_path == ".claude/plans/p.md"

    def test_parent_fallback_cross_forge_root(self, tmp_path: Path) -> None:
        parent_fr = tmp_path / "parent_project"
        parent_fr.mkdir()
        child_fr = tmp_path / "child_project"
        child_fr.mkdir()

        snap = {
            "kind": "approved",
            "captured_at": "2026-04-16T12:00:00Z",
            "source_path": ".claude/plans/p.md",
            "snapshot_path": ".forge/artifacts/planner/plans/x.md",
        }
        _write_manifest(parent_fr, "planner", plans=[snap])

        child = create_session_state("executor")
        child.confirmed.derivation = Derivation(
            parent_session="planner",
            parent_forge_root=str(parent_fr),
        )

        info = resolve_plan_info(child, current_forge_root=str(child_fr))

        assert info.source == "parent"
        assert info.parent_forge_root == str(parent_fr)
        assert info.approved_snapshots == [snap]

    def test_parent_manifest_missing(self, forge_root: Path) -> None:
        child = create_session_state("executor")
        child.confirmed.derivation = Derivation(parent_session="planner")

        info = resolve_plan_info(child, current_forge_root=str(forge_root))

        assert info.source is None
        assert info.draft_path is None
        assert info.parent_session is None

    def test_parent_exists_but_no_plan(self, forge_root: Path) -> None:
        _write_manifest(forge_root, "planner")

        child = create_session_state("executor")
        child.confirmed.derivation = Derivation(parent_session="planner")

        info = resolve_plan_info(child, current_forge_root=str(forge_root))

        assert info.source is None


class TestResolvePlanInfoLegacyForkFallback:
    """Legacy fork manifests may have only top-level parent_session.

    New derived sessions populate confirmed.derivation, but plan resolution still
    supports older fork manifests via the top-level fallback.
    """

    def test_fork_surfaces_parent_plan_via_index_lookup(self, forge_root: Path) -> None:
        parent = create_session_state("planner", worktree_path=str(forge_root))
        parent.forge_root = str(forge_root)
        parent.confirmed.latest_plan_path = ".claude/plans/p.md"
        SessionStore(str(forge_root), "planner").write(parent)
        IndexStore().add_session(
            name="planner",
            worktree_path=str(forge_root),
            project_root=str(forge_root),
            forge_root=str(forge_root),
            checkout_root=str(forge_root),
            relative_path=".",
        )

        child = create_session_state(
            "executor",
            parent_session="planner",
            is_fork=True,
            worktree_path=str(forge_root),
        )

        info = resolve_plan_info(child, current_forge_root=str(forge_root))

        assert info.source == "parent"
        assert info.parent_session == "planner"
        assert info.draft_path == ".claude/plans/p.md"

    def test_fork_falls_back_to_current_forge_root_when_index_missing(self, forge_root: Path) -> None:
        _write_manifest(forge_root, "planner", plan_path=".claude/plans/p.md")

        child = create_session_state("executor", parent_session="planner", is_fork=True)

        info = resolve_plan_info(child, current_forge_root=str(forge_root))

        assert info.source == "parent"
        assert info.parent_forge_root == str(forge_root)

    def test_fork_disambiguates_duplicate_parent_names_across_projects(self, tmp_path: Path) -> None:
        """Two projects each with a session named ``planner``: the child resolves to its own project's parent."""
        project_a_root = tmp_path / "project_a"
        project_a_root.mkdir()
        fr_a = project_a_root  # forge_root == project_root in this simple setup

        project_b_root = tmp_path / "project_b"
        project_b_root.mkdir()
        fr_b = project_b_root

        planner_a = create_session_state("planner", worktree_path=str(project_a_root))
        planner_a.forge_root = str(fr_a)
        planner_a.confirmed.latest_plan_path = ".claude/plans/plan-A.md"
        SessionStore(str(fr_a), "planner").write(planner_a)
        IndexStore().add_session(
            name="planner",
            worktree_path=str(project_a_root),
            project_root=str(project_a_root),
            forge_root=str(fr_a),
            checkout_root=str(project_a_root),
            relative_path=".",
        )

        planner_b = create_session_state("planner", worktree_path=str(project_b_root))
        planner_b.forge_root = str(fr_b)
        planner_b.confirmed.latest_plan_path = ".claude/plans/plan-B.md"
        SessionStore(str(fr_b), "planner").write(planner_b)
        IndexStore().add_session(
            name="planner",
            worktree_path=str(project_b_root),
            project_root=str(project_b_root),
            forge_root=str(fr_b),
            checkout_root=str(project_b_root),
            relative_path=".",
        )

        executor_in_a = create_session_state(
            "executor",
            parent_session="planner",
            is_fork=True,
            worktree_path=str(project_a_root),
        )
        executor_in_a.forge_root = str(fr_a)
        SessionStore(str(fr_a), "executor").write(executor_in_a)
        IndexStore().add_session(
            name="executor",
            worktree_path=str(project_a_root),
            project_root=str(project_a_root),
            forge_root=str(fr_a),
            checkout_root=str(project_a_root),
            relative_path=".",
        )

        info = resolve_plan_info(executor_in_a, current_forge_root=str(fr_a))

        assert info.source == "parent"
        assert info.parent_forge_root == str(fr_a)
        assert info.draft_path == ".claude/plans/plan-A.md"

    def test_fork_disambiguates_duplicate_parent_names_across_forge_projects_in_same_repo(self, tmp_path: Path) -> None:
        """Sibling Forge projects inside one logical repo are narrowed by relative_path."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        fr_a = repo_root / "proj-a"
        fr_b = repo_root / "proj-b"
        fr_a.mkdir()
        fr_b.mkdir()

        planner_a = create_session_state("planner", worktree_path=str(repo_root))
        planner_a.forge_root = str(fr_a)
        planner_a.confirmed.latest_plan_path = ".claude/plans/plan-A.md"
        SessionStore(str(fr_a), "planner").write(planner_a)
        IndexStore().add_session(
            name="planner",
            worktree_path=str(repo_root),
            project_root=str(repo_root),
            forge_root=str(fr_a),
            checkout_root=str(repo_root),
            relative_path="proj-a",
        )

        planner_b = create_session_state("planner", worktree_path=str(repo_root))
        planner_b.forge_root = str(fr_b)
        planner_b.confirmed.latest_plan_path = ".claude/plans/plan-B.md"
        SessionStore(str(fr_b), "planner").write(planner_b)
        IndexStore().add_session(
            name="planner",
            worktree_path=str(repo_root),
            project_root=str(repo_root),
            forge_root=str(fr_b),
            checkout_root=str(repo_root),
            relative_path="proj-b",
        )

        executor_in_b = create_session_state(
            "executor",
            parent_session="planner",
            is_fork=True,
            worktree_path=str(repo_root),
        )
        executor_in_b.forge_root = str(fr_b)
        SessionStore(str(fr_b), "executor").write(executor_in_b)
        IndexStore().add_session(
            name="executor",
            worktree_path=str(repo_root),
            project_root=str(repo_root),
            forge_root=str(fr_b),
            checkout_root=str(repo_root),
            relative_path="proj-b",
        )

        info = resolve_plan_info(executor_in_b, current_forge_root=str(fr_b))

        assert info.source == "parent"
        assert info.parent_forge_root == str(fr_b)
        assert info.draft_path == ".claude/plans/plan-B.md"

    def test_fork_in_worktree_resolves_to_parent_in_same_project(self, tmp_path: Path) -> None:
        """--worktree fork: child's forge_root != parent's forge_root, but both share project_root."""
        project_root = tmp_path / "repo"
        project_root.mkdir()

        parent_fr = project_root / "main-checkout"
        parent_fr.mkdir()
        planner = create_session_state("planner", worktree_path=str(parent_fr))
        planner.forge_root = str(parent_fr)
        planner.confirmed.artifacts["plans"] = [
            {"kind": "approved", "snapshot_path": ".forge/artifacts/planner/plans/real.md"}
        ]
        SessionStore(str(parent_fr), "planner").write(planner)
        IndexStore().add_session(
            name="planner",
            worktree_path=str(parent_fr),
            project_root=str(project_root),
            forge_root=str(parent_fr),
            checkout_root=str(parent_fr),
            relative_path=".",
        )

        # Unrelated planner in a different logical repo — must NOT be picked.
        other_repo = tmp_path / "other_repo"
        other_repo.mkdir()
        other_planner = create_session_state("planner", worktree_path=str(other_repo))
        other_planner.forge_root = str(other_repo)
        other_planner.confirmed.latest_plan_path = ".claude/plans/wrong.md"
        SessionStore(str(other_repo), "planner").write(other_planner)
        IndexStore().add_session(
            name="planner",
            worktree_path=str(other_repo),
            project_root=str(other_repo),
            forge_root=str(other_repo),
            checkout_root=str(other_repo),
            relative_path=".",
        )

        child_fr = project_root / "executor-worktree"
        child_fr.mkdir()
        executor = create_session_state(
            "executor",
            parent_session="planner",
            is_fork=True,
            worktree_path=str(child_fr),
        )
        executor.forge_root = str(child_fr)
        SessionStore(str(child_fr), "executor").write(executor)
        IndexStore().add_session(
            name="executor",
            worktree_path=str(child_fr),
            project_root=str(project_root),
            forge_root=str(child_fr),
            checkout_root=str(child_fr),
            relative_path=".",
        )

        info = resolve_plan_info(executor, current_forge_root=str(child_fr))

        assert info.source == "parent"
        assert info.parent_forge_root == str(parent_fr)
        assert "wrong.md" not in (info.draft_path or "")
        assert latest_snapshot_path(info.approved_snapshots) == ".forge/artifacts/planner/plans/real.md"


class TestResolvePlanInfoEmpty:
    def test_no_plan_no_derivation(self) -> None:
        state = create_session_state("solo")

        info = resolve_plan_info(state, current_forge_root="/irrelevant")

        assert info == PlanInfo()


class TestPreferredPlanPath:
    """Approved snapshot must win over draft (matches handoff._resolve_plan_content)."""

    def test_approved_snapshot_wins_over_draft(self) -> None:
        info = PlanInfo(
            draft_path=".claude/plans/stale-draft.md",
            approved_snapshots=[{"snapshot_path": ".forge/artifacts/planner/plans/real.md"}],
            source="self",
        )
        assert preferred_plan_path(info) == ".forge/artifacts/planner/plans/real.md"

    def test_draft_used_when_no_snapshots(self) -> None:
        info = PlanInfo(draft_path=".claude/plans/p.md", source="self")
        assert preferred_plan_path(info) == ".claude/plans/p.md"

    def test_none_when_neither(self) -> None:
        assert preferred_plan_path(PlanInfo()) is None


class TestResolvePathAgainst:
    def test_abs_path_returned_as_is(self, tmp_path: Path) -> None:
        f = tmp_path / "abs.md"
        f.write_text("x")
        result = resolve_path_against(str(f), base="/ignored")
        assert result.path == str(f.resolve())
        assert result.exists is True

    def test_rel_path_joined_with_base(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        target = tmp_path / "sub" / "plan.md"
        target.write_text("x")
        result = resolve_path_against("sub/plan.md", base=str(tmp_path))
        assert result.path == str(target.resolve())
        assert result.exists is True

    def test_missing_file_annotated(self, tmp_path: Path) -> None:
        result = resolve_path_against("missing.md", base=str(tmp_path))
        assert result.exists is False
        assert "missing.md" in result.path

    def test_rel_path_without_base_returns_undecidable(self) -> None:
        result = resolve_path_against("foo/bar.md", base=None)
        assert result == DisplayedPath(path="foo/bar.md", exists=False)


class TestResolveDisplayedPlanPath:
    def test_snapshot_preferred_and_resolved_for_self(self, tmp_path: Path) -> None:
        (tmp_path / ".forge" / "artifacts" / "x" / "plans").mkdir(parents=True)
        snap = tmp_path / ".forge" / "artifacts" / "x" / "plans" / "r.md"
        snap.write_text("x")

        info = PlanInfo(
            draft_path=".claude/plans/stale.md",
            approved_snapshots=[{"snapshot_path": ".forge/artifacts/x/plans/r.md"}],
            source="self",
        )

        result = resolve_displayed_plan_path(info, current_forge_root=str(tmp_path))
        assert result is not None
        assert result.path == str(snap.resolve())
        assert result.exists is True

    def test_parent_snapshot_resolves_against_parent_forge_root(self, tmp_path: Path) -> None:
        parent_fr = tmp_path / "parent"
        parent_fr.mkdir()
        (parent_fr / ".forge" / "artifacts" / "planner" / "plans").mkdir(parents=True)
        snap = parent_fr / ".forge" / "artifacts" / "planner" / "plans" / "r.md"
        snap.write_text("x")

        child_fr = tmp_path / "child"
        child_fr.mkdir()

        info = PlanInfo(
            approved_snapshots=[{"snapshot_path": ".forge/artifacts/planner/plans/r.md"}],
            source="parent",
            parent_session="planner",
            parent_forge_root=str(parent_fr),
        )

        result = resolve_displayed_plan_path(info, current_forge_root=str(child_fr))
        assert result is not None
        assert result.path == str(snap.resolve())
        assert result.exists is True

    def test_draft_resolved_against_worktree(self, tmp_path: Path) -> None:
        (tmp_path / ".claude" / "plans").mkdir(parents=True)
        draft = tmp_path / ".claude" / "plans" / "p.md"
        draft.write_text("x")

        info = PlanInfo(draft_path=".claude/plans/p.md", source="self")

        result = resolve_displayed_plan_path(info, current_forge_root="/irrelevant", current_worktree=str(tmp_path))
        assert result is not None
        assert result.path == str(draft.resolve())
        assert result.exists is True

    def test_draft_prefers_current_launch_root_over_worktree(self, tmp_path: Path) -> None:
        checkout = tmp_path / "checkout"
        launch_root = checkout / "nested"
        launch_root.mkdir(parents=True)
        (launch_root / ".claude" / "plans").mkdir(parents=True)
        draft = launch_root / ".claude" / "plans" / "p.md"
        draft.write_text("x")

        info = PlanInfo(draft_path=".claude/plans/p.md", source="self")

        result = resolve_displayed_plan_path(
            info,
            current_forge_root=str(launch_root),
            current_launch_root=str(launch_root),
            current_worktree=str(checkout),
        )
        assert result is not None
        assert result.path == str(draft.resolve())
        assert result.exists is True

    def test_missing_snapshot_annotated_as_not_existing(self, tmp_path: Path) -> None:
        info = PlanInfo(
            approved_snapshots=[{"snapshot_path": ".forge/artifacts/x/plans/gone.md"}],
            source="self",
        )
        result = resolve_displayed_plan_path(info, current_forge_root=str(tmp_path))
        assert result is not None
        assert result.exists is False
        assert "gone.md" in result.path

    def test_no_plan_returns_none(self) -> None:
        result = resolve_displayed_plan_path(PlanInfo(), current_forge_root="/any")
        assert result is None


class TestLatestSnapshotPath:
    def test_empty_list(self) -> None:
        assert latest_snapshot_path([]) is None

    def test_single_snapshot(self) -> None:
        snaps = [{"snapshot_path": ".forge/artifacts/a/plans/x.md"}]
        assert latest_snapshot_path(snaps) == ".forge/artifacts/a/plans/x.md"

    def test_returns_last_entry(self) -> None:
        snaps = [
            {"snapshot_path": "first.md"},
            {"snapshot_path": "second.md"},
        ]
        assert latest_snapshot_path(snaps) == "second.md"

    def test_missing_path_returns_none(self) -> None:
        snaps = [{"kind": "approved"}]
        assert latest_snapshot_path(snaps) is None
