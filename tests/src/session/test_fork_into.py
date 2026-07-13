"""Tests for fork --into relative_path preservation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.install.project_compat import ProjectCompatibilityError
from forge.session.exceptions import (
    BranchExistsError,
    BranchNotMergedError,
    ForgeSessionError,
    SessionExistsError,
)
from forge.session.identity import session_name_from_key
from forge.session.manager import SessionManager
from forge.session.models import Derivation
from forge.session.prev_sessions import child_path
from forge.session.store import SessionStore
from forge.session.worktree import resolve_worktree_path


def _init_git_repo(path: Path) -> None:
    """Create a minimal git repo at *path*."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        capture_output=True,
        check=True,
        cwd=str(path),
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        capture_output=True,
        check=True,
        cwd=str(path),
    )
    (path / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], capture_output=True, check=True, cwd=str(path))
    subprocess.run(["git", "commit", "-m", "init"], capture_output=True, check=True, cwd=str(path))


def _enable_forge(path: Path) -> None:
    """Create .claude/ and .forge/ at *path*."""
    (path / ".claude").mkdir(exist_ok=True)
    (path / ".forge").mkdir(exist_ok=True)


class TestForkIntoRelativePath:
    """tests --into targets worktree; child at equivalent forge_root."""

    def test_into_root_forge_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fork --into with forge_root at checkout root (relative_path='.')."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        # Parent repo
        parent_repo = tmp_path / "repo-a"
        _init_git_repo(parent_repo)
        _enable_forge(parent_repo)

        # Target repo (same logical repo root in reality, simulated as separate checkout)
        target_repo = tmp_path / "repo-a-feat"
        _init_git_repo(target_repo)
        _enable_forge(target_repo)

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(parent_repo))

        _, fork = manager.fork_session("parent", "child", into_path=str(target_repo))

        assert fork.forge_root == str(target_repo)
        assert fork.worktree is not None
        assert fork.worktree.path == str(target_repo)
        assert fork.worktree.owns_worktree is False
        assert fork.confirmed.derivation is not None
        assert fork.confirmed.derivation.parent_session == "parent"
        assert fork.confirmed.derivation.resume_mode == "transfer"
        assert fork.confirmed.derivation.strategy is None
        assert fork.confirmed.derivation.depth == 1
        assert fork.confirmed.derivation.lineage == ["parent"]
        assert fork.confirmed.derivation.parent_forge_root == str(parent_repo)
        assert fork.confirmed.derivation.parent_project_root == str(parent_repo)

        # Verify index entry has correct identity
        entry = manager.index_store.get_session("child")
        assert entry.forge_root == str(target_repo)
        assert entry.relative_path == "."

    def test_into_nested_forge_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fork --into with forge_root in a subdirectory (relative_path != '.')."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        # Parent: monorepo with forge project in packages/app
        parent_repo = tmp_path / "monorepo"
        _init_git_repo(parent_repo)
        nested = parent_repo / "packages" / "app"
        nested.mkdir(parents=True)
        _enable_forge(nested)

        # Target: different checkout of same monorepo
        target_repo = tmp_path / "monorepo-feat"
        _init_git_repo(target_repo)
        target_nested = target_repo / "packages" / "app"
        target_nested.mkdir(parents=True)
        _enable_forge(target_nested)

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(nested))

        _, fork = manager.fork_session("parent", "child", into_path=str(target_repo))

        # Child should land at target_repo/packages/app (equivalent position)
        assert fork.forge_root == str(target_nested)

        entry = manager.index_store.get_session("child")
        assert entry.forge_root == str(target_nested)
        assert entry.relative_path == "packages/app"

    def test_into_force_replaces_stale_target_session_without_touching_checkout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Force retry for --into should replace target session state, not the checkout."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        parent_repo = tmp_path / "repo-a"
        _init_git_repo(parent_repo)
        _enable_forge(parent_repo)

        target_repo = tmp_path / "repo-a-feat"
        _init_git_repo(target_repo)
        _enable_forge(target_repo)

        marker = target_repo / "keep-me.txt"
        marker.write_text("safe\n")

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(parent_repo))
        _, stale = manager.fork_session("parent", "child", into_path=str(target_repo))

        assert stale.is_fork is True
        assert stale.parent_session == "parent"

        _, fork = manager.fork_session("parent", "child", into_path=str(target_repo), force=True)

        replaced = manager.get_session("child", forge_root=str(target_repo))
        entry = manager.index_store.get_session("child", forge_root=str(target_repo))

        assert marker.read_text() == "safe\n"
        assert (target_repo / ".git").exists()
        assert fork.worktree is not None
        assert fork.worktree.path == str(target_repo)
        assert fork.worktree.is_worktree is True
        assert fork.worktree.owns_worktree is False
        assert replaced.is_fork is True
        assert replaced.parent_session == "parent"
        assert entry.forge_root == str(target_repo)
        assert entry.parent_session == "parent"

    def test_into_force_rejects_unrelated_target_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Force retry for --into must not delete an unrelated same-name session."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        parent_repo = tmp_path / "repo-a"
        _init_git_repo(parent_repo)
        _enable_forge(parent_repo)

        target_repo = tmp_path / "repo-a-feat"
        _init_git_repo(target_repo)
        _enable_forge(target_repo)

        marker = target_repo / "keep-me.txt"
        marker.write_text("safe\n")

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(parent_repo))
        manager.start_session(name="child", worktree_path=str(target_repo))

        with pytest.raises(SessionExistsError):
            manager.fork_session("parent", "child", into_path=str(target_repo), force=True)

        existing = manager.get_session("child", forge_root=str(target_repo))
        entry = manager.index_store.get_session("child", forge_root=str(target_repo))

        assert marker.read_text() == "safe\n"
        assert existing.is_fork is False
        assert existing.parent_session is None
        assert entry.parent_session is None

    def test_into_missing_forge_at_target_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fork --into fails when target doesn't have .forge/ at the right position."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        parent_repo = tmp_path / "repo-a"
        _init_git_repo(parent_repo)
        _enable_forge(parent_repo)

        target_repo = tmp_path / "repo-a-feat"
        _init_git_repo(target_repo)
        # NO _enable_forge(target_repo)

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(parent_repo))

        with pytest.raises(ForgeSessionError, match="No Forge project"):
            manager.fork_session("parent", "child", into_path=str(target_repo))

    def test_into_nested_missing_forge_at_target_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fork --into fails when nested target path doesn't have .forge/."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        parent_repo = tmp_path / "monorepo"
        _init_git_repo(parent_repo)
        nested = parent_repo / "packages" / "app"
        nested.mkdir(parents=True)
        _enable_forge(nested)

        target_repo = tmp_path / "monorepo-feat"
        _init_git_repo(target_repo)
        # Create the directory but NOT .forge/
        target_nested = target_repo / "packages" / "app"
        target_nested.mkdir(parents=True)

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(nested))

        with pytest.raises(ForgeSessionError, match="No Forge project"):
            manager.fork_session("parent", "child", into_path=str(target_repo))

    def test_into_incompatible_nested_target_refuses_before_child_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        parent_repo = tmp_path / "monorepo"
        _init_git_repo(parent_repo)
        parent_nested = parent_repo / "packages" / "app"
        parent_nested.mkdir(parents=True)
        _enable_forge(parent_nested)

        target_repo = tmp_path / "monorepo-feat"
        _init_git_repo(target_repo)
        target_nested = target_repo / "packages" / "app"
        target_nested.mkdir(parents=True)
        _enable_forge(target_nested)
        pin = target_nested / ".forge" / "project.toml"
        pin.write_text('schema_version = 1\nrequired_forge = ">=999"\n')

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(parent_nested))

        with pytest.raises(ProjectCompatibilityError) as exc_info:
            manager.fork_session("parent", "child", into_path=str(target_repo))

        assert exc_info.value.path == str(pin)
        assert exc_info.value.state == "incompatible"
        assert not (target_nested / ".forge" / "sessions" / "child").exists()
        assert all(session_name_from_key(key) != "child" for key in manager.index_store.read().sessions)

    def test_into_force_refusal_preserves_stale_target_manifest_index_and_transfer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        parent_repo = tmp_path / "monorepo"
        _init_git_repo(parent_repo)
        parent_nested = parent_repo / "packages" / "app"
        parent_nested.mkdir(parents=True)
        _enable_forge(parent_nested)

        target_repo = tmp_path / "monorepo-feat"
        _init_git_repo(target_repo)
        target_nested = target_repo / "packages" / "app"
        target_nested.mkdir(parents=True)
        _enable_forge(target_nested)

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(parent_nested))
        manager.fork_session("parent", "child", into_path=str(target_repo))

        child_store = SessionStore(str(target_nested), "child")
        transfer = child_path(target_nested, "parent", "child")
        transfer.parent.mkdir(parents=True, exist_ok=True)
        transfer.write_text("stale transfer must survive\n", encoding="utf-8")
        manifest_before = child_store.manifest_path.read_bytes()
        index_before = manager.index_store.index_path.read_bytes()
        transfer_before = transfer.read_bytes()

        pin = target_nested / ".forge" / "project.toml"
        pin.write_text('schema_version = 1\nrequired_forge = ">=999"\n')

        with pytest.raises(ProjectCompatibilityError):
            manager.fork_session("parent", "child", into_path=str(target_repo), force=True)

        assert child_store.manifest_path.read_bytes() == manifest_before
        assert manager.index_store.index_path.read_bytes() == index_before
        assert transfer.read_bytes() == transfer_before

    def test_worktree_fork_nested_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fork --worktree propagates parent's relative_path to new checkout."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        # Monorepo with nested Forge project
        repo = tmp_path / "monorepo"
        _init_git_repo(repo)
        nested = repo / "packages" / "app"
        nested.mkdir(parents=True)
        _enable_forge(nested)

        monkeypatch.chdir(nested)
        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(nested))

        _, fork = manager.fork_session("parent", "child", create_worktree=True)

        # Child should be in a new worktree at the equivalent nested position
        assert fork.forge_root is not None
        assert fork.forge_root.endswith("packages/app")
        assert "child" in fork.forge_root  # in the new worktree

        entry = manager.index_store.get_session("child")
        assert entry.relative_path == "packages/app"

    def test_worktree_fork_rolls_back_checkout_and_branch_on_target_refusal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        repo = tmp_path / "repo"
        _init_git_repo(repo)
        _enable_forge(repo)
        pin = repo / ".forge" / "project.toml"
        pin.write_text('schema_version = 1\nrequired_forge = ">=999"\n')
        subprocess.run(["git", "add", "-f", ".forge/project.toml"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "track incompatible pin"], cwd=repo, check=True)
        pin.write_text('schema_version = 1\nrequired_forge = ">=0"\n')

        monkeypatch.chdir(repo)
        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(repo))
        expected_worktree = resolve_worktree_path(repo, "child")

        with pytest.raises(ProjectCompatibilityError):
            manager.fork_session("parent", "child", create_worktree=True)

        branches = subprocess.run(
            ["git", "branch", "--list", "child"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert not expected_worktree.exists()
        assert branches.strip() == ""
        assert all(session_name_from_key(key) != "child" for key in manager.index_store.read().sessions)

    def test_worktree_fork_surfaces_incomplete_target_refusal_rollback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import forge.session.worktree as worktree_module

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        repo = tmp_path / "repo"
        _init_git_repo(repo)
        _enable_forge(repo)
        pin = repo / ".forge" / "project.toml"
        pin.write_text('schema_version = 1\nrequired_forge = ">=999"\n')
        subprocess.run(["git", "add", "-f", ".forge/project.toml"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "track incompatible pin"], cwd=repo, check=True)
        pin.write_text('schema_version = 1\nrequired_forge = ">=0"\n')

        real_cleanup = worktree_module.cleanup_worktree

        def _cleanup_with_error(**kwargs):
            result = real_cleanup(**kwargs)
            result.errors.append("simulated branch cleanup failure")
            return result

        monkeypatch.setattr(worktree_module, "cleanup_worktree", _cleanup_with_error)
        monkeypatch.chdir(repo)
        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(repo))

        with pytest.raises(
            ForgeSessionError, match="Rollback incomplete.*simulated branch cleanup failure"
        ) as exc_info:
            manager.fork_session("parent", "child", create_worktree=True)

        assert isinstance(exc_info.value.__cause__, ProjectCompatibilityError)
        assert not resolve_worktree_path(repo, "child").exists()

    def test_worktree_force_refusal_preserves_stale_checkout_branch_and_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        repo = tmp_path / "repo"
        _init_git_repo(repo)
        _enable_forge(repo)
        monkeypatch.chdir(repo)

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(repo))
        _, stale = manager.fork_session("parent", "child", create_worktree=True)
        assert stale.worktree is not None

        stale_checkout = Path(stale.worktree.path)
        dirty_file = stale_checkout / "uncommitted.txt"
        dirty_file.write_text("must survive refusal\n", encoding="utf-8")
        pin = stale_checkout / ".forge" / "project.toml"
        pin.parent.mkdir(parents=True, exist_ok=True)
        pin.write_text('schema_version = 1\nrequired_forge = ">=999"\n', encoding="utf-8")
        transfer = child_path(stale_checkout, "parent", "child")
        transfer.parent.mkdir(parents=True, exist_ok=True)
        transfer.write_text("stale transfer must survive\n", encoding="utf-8")

        stale_store = SessionStore(str(stale_checkout), "child")
        manifest_before = stale_store.manifest_path.read_bytes()
        index_before = manager.index_store.index_path.read_bytes()
        transfer_before = transfer.read_bytes()
        branch_before = subprocess.run(
            ["git", "rev-parse", "child"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        with pytest.raises(ProjectCompatibilityError):
            manager.fork_session("parent", "child", create_worktree=True, force=True)

        branch_after = subprocess.run(
            ["git", "rev-parse", "child"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        worktrees = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

        assert stale_checkout.is_dir()
        assert dirty_file.read_text(encoding="utf-8") == "must survive refusal\n"
        assert pin.is_file()
        assert branch_after == branch_before
        assert f"worktree {stale_checkout}" in worktrees
        assert stale_store.manifest_path.read_bytes() == manifest_before
        assert manager.index_store.index_path.read_bytes() == index_before
        assert transfer.read_bytes() == transfer_before

    def test_worktree_force_refusal_preflights_incompatible_replacement_head(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        repo = tmp_path / "repo"
        _init_git_repo(repo)
        _enable_forge(repo)
        monkeypatch.chdir(repo)

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(repo))
        _, stale = manager.fork_session("parent", "child", create_worktree=True)
        assert stale.worktree is not None

        stale_checkout = Path(stale.worktree.path)
        dirty_file = stale_checkout / "uncommitted.txt"
        dirty_file.write_text("must survive prospective refusal\n", encoding="utf-8")
        transfer = child_path(stale_checkout, "parent", "child")
        transfer.parent.mkdir(parents=True, exist_ok=True)
        transfer.write_text("stale transfer must survive\n", encoding="utf-8")
        stale_store = SessionStore(str(stale_checkout), "child")
        manifest_before = stale_store.manifest_path.read_bytes()
        index_before = manager.index_store.index_path.read_bytes()
        transfer_before = transfer.read_bytes()
        branch_before = subprocess.run(
            ["git", "rev-parse", "child"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        # The stale checkout predates this tracked pin, so its own precheck is
        # compatible while the exact HEAD used for replacement is not.
        pin = repo / ".forge" / "project.toml"
        pin.write_text('schema_version = 1\nrequired_forge = ">=999"\n', encoding="utf-8")
        subprocess.run(["git", "add", "-f", ".forge/project.toml"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "require future Forge"], cwd=repo, check=True)
        assert not (stale_checkout / ".forge" / "project.toml").exists()

        with pytest.raises(ProjectCompatibilityError) as exc_info:
            manager.fork_session("parent", "child", create_worktree=True, force=True)

        branch_after = subprocess.run(
            ["git", "rev-parse", "child"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        worktrees = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

        assert exc_info.value.path == str(stale_checkout / ".forge" / "project.toml")
        assert stale_checkout.is_dir()
        assert dirty_file.read_text(encoding="utf-8") == "must survive prospective refusal\n"
        assert branch_after == branch_before
        assert f"worktree {stale_checkout}" in worktrees
        assert stale_store.manifest_path.read_bytes() == manifest_before
        assert manager.index_store.index_path.read_bytes() == index_before
        assert transfer.read_bytes() == transfer_before

    def test_worktree_force_unmerged_branch_refusal_preserves_stale_checkout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        repo = tmp_path / "repo"
        _init_git_repo(repo)
        _enable_forge(repo)
        monkeypatch.chdir(repo)

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(repo))
        _, stale = manager.fork_session("parent", "child", create_worktree=True)
        assert stale.worktree is not None
        stale_checkout = Path(stale.worktree.path)
        committed = stale_checkout / "child-only.txt"
        committed.write_text("unmerged child commit\n", encoding="utf-8")
        subprocess.run(["git", "add", "child-only.txt"], cwd=stale_checkout, check=True)
        subprocess.run(["git", "commit", "-m", "child-only commit"], cwd=stale_checkout, check=True)
        dirty = stale_checkout / "dirty.txt"
        dirty.write_text("must survive\n", encoding="utf-8")
        manifest_before = SessionStore(str(stale_checkout), "child").manifest_path.read_bytes()
        index_before = manager.index_store.index_path.read_bytes()

        with pytest.raises(BranchNotMergedError):
            manager.fork_session("parent", "child", create_worktree=True, force=True)

        assert stale_checkout.is_dir()
        assert committed.read_text(encoding="utf-8") == "unmerged child commit\n"
        assert dirty.read_text(encoding="utf-8") == "must survive\n"
        assert SessionStore(str(stale_checkout), "child").manifest_path.read_bytes() == manifest_before
        assert manager.index_store.index_path.read_bytes() == index_before

    def test_worktree_force_explicit_branch_refusal_preserves_stale_checkout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        repo = tmp_path / "repo"
        _init_git_repo(repo)
        _enable_forge(repo)
        monkeypatch.chdir(repo)

        manager = SessionManager()
        manager.start_session(name="parent", worktree_path=str(repo))
        _, stale = manager.fork_session("parent", "child", create_worktree=True, branch="custom-child")
        assert stale.worktree is not None
        stale_checkout = Path(stale.worktree.path)
        dirty = stale_checkout / "dirty.txt"
        dirty.write_text("must survive\n", encoding="utf-8")

        with pytest.raises(BranchExistsError):
            manager.fork_session(
                "parent",
                "child",
                create_worktree=True,
                branch="custom-child",
                force=True,
            )

        assert stale_checkout.is_dir()
        assert dirty.read_text(encoding="utf-8") == "must survive\n"


class TestForkNativeRelocate:
    """fork_session derivation + cleanup for the opt-in native-relocate resume mode."""

    def _parent_with_uuid(self, manager: SessionManager, repo: Path, uuid: str) -> None:
        """Start a parent session and assign it a Claude UUID (normally hook-set)."""
        manager.start_session(name="parent", worktree_path=str(repo))
        pstore = manager.get_session_store("parent")
        pstate = pstore.read()
        pstate.confirmed.claude_session_id = uuid
        pstore.write(pstate)

    def test_native_relocate_records_derivation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A worktree fork with resume_mode=native-relocate records it honestly."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        parent_repo = tmp_path / "repo"
        _init_git_repo(parent_repo)
        _enable_forge(parent_repo)

        manager = SessionManager()
        self._parent_with_uuid(manager, parent_repo, "parent-uuid-abc")

        _, fork = manager.fork_session("parent", "child", create_worktree=True, resume_mode="native-relocate")

        assert fork.confirmed.derivation is not None
        assert fork.confirmed.derivation.resume_mode == "native-relocate"
        assert fork.confirmed.derivation.relocated_parent_session_id == "parent-uuid-abc"
        # native-relocate carries the full transcript, not an assembled context file
        assert fork.confirmed.derivation.context_file is None
        assert fork.confirmed.derivation.strategy is None

    def test_native_relocate_ignored_for_same_directory_fork(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without a worktree the mode is inapplicable; the fork stays plain native."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        parent_repo = tmp_path / "repo"
        _init_git_repo(parent_repo)
        _enable_forge(parent_repo)

        manager = SessionManager()
        self._parent_with_uuid(manager, parent_repo, "parent-uuid-abc")

        _, fork = manager.fork_session("parent", "child", resume_mode="native-relocate")

        assert fork.confirmed.derivation is not None
        assert fork.confirmed.derivation.resume_mode == "native"
        assert fork.confirmed.derivation.relocated_parent_session_id is None

    def test_fork_session_samedir_transfer_derivation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A same-directory fork with resume_mode='transfer' records the transfer baseline.

        The CLI's _persist_fork_transfer_derivation refinement is best-effort, so the manager
        must write the authoritative 'transfer' baseline (with a pre-recorded context_file for GC)
        even if that later refinement fails. resume_mode=None stays plain native.
        """
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        parent_repo = tmp_path / "repo"
        _init_git_repo(parent_repo)
        _enable_forge(parent_repo)

        manager = SessionManager()
        self._parent_with_uuid(manager, parent_repo, "parent-uuid-abc")

        _, transfer_fork = manager.fork_session("parent", "child-t", resume_mode="transfer")
        assert transfer_fork.confirmed.derivation is not None
        assert transfer_fork.confirmed.derivation.resume_mode == "transfer"
        # Per-child context file is pre-recorded so GC knows it belongs to this fork.
        assert transfer_fork.confirmed.derivation.context_file is not None
        # Transfer is not a transcript relocation.
        assert transfer_fork.confirmed.derivation.relocated_parent_session_id is None

        _, native_fork = manager.fork_session("parent", "child-n")
        assert native_fork.confirmed.derivation is not None
        assert native_fork.confirmed.derivation.resume_mode == "native"
        assert native_fork.confirmed.derivation.context_file is None

    def test_delete_removes_relocated_copy_without_child_uuid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deleting a native-relocate fork removes the relocated parent copy (dir-scoped),
        preserves the parent's original, and runs even when the child never got a UUID."""
        from forge.session.claude.paths import get_transcript_path

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        parent_repo = tmp_path / "repo"
        _init_git_repo(parent_repo)
        _enable_forge(parent_repo)

        manager = SessionManager()
        self._parent_with_uuid(manager, parent_repo, "parent-uuid-xyz")
        _, fork = manager.fork_session("parent", "child", create_worktree=True, resume_mode="native-relocate")

        assert fork.worktree is not None
        child_cwd = fork.worktree.path

        # Simulate the CLI launch step: pre-seed claude_project_root; the child has NO
        # claude_session_id (failed/partial launch) so cleanup must not depend on it.
        fstore = manager.get_session_store("child")
        fchild = fstore.read()
        fchild.confirmed.claude_project_root = child_cwd
        fchild.confirmed.claude_session_id = None
        fstore.write(fchild)

        # The relocated copy lives in the child's encoded dir; the parent original in the parent's.
        parent_original = get_transcript_path(str(parent_repo), "parent-uuid-xyz")
        parent_original.parent.mkdir(parents=True, exist_ok=True)
        parent_original.write_text("PARENT\n")
        relocated = get_transcript_path(child_cwd, "parent-uuid-xyz")
        relocated.parent.mkdir(parents=True, exist_ok=True)
        relocated.write_text("PARENT\n")

        manager.delete_session("child", delete_transcripts=True, delete_worktree=False, force=True)

        assert not relocated.exists(), "relocated parent copy should be removed from the child's dir"
        assert parent_original.exists(), "parent's original transcript must be preserved"

    def test_delete_removes_rewind_copy_by_fresh_uuid_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deleting a rewind child unlinks only its fresh truncated transcript UUID."""
        from forge.session.claude.paths import get_transcript_path

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        parent_repo = tmp_path / "repo"
        _init_git_repo(parent_repo)
        _enable_forge(parent_repo)

        manager = SessionManager()
        self._parent_with_uuid(manager, parent_repo, "parent-uuid-rewind")
        manager.fork_session("parent", "rewind-child")

        cstore = manager.get_session_store("rewind-child")
        child_state = cstore.read()
        child_state.confirmed.claude_session_id = None
        child_state.confirmed.claude_project_root = str(parent_repo)
        child_state.confirmed.derivation = Derivation(
            parent_session="parent",
            resume_mode="native-relocate",
            strategy="rewind",
            relocated_parent_session_id=None,
            dropped_turns=1,
            rewind_relocated_session_id="rewind-fresh-uuid",
        )
        cstore.write(child_state)

        manager.fork_session("parent", "sibling")
        sstore = manager.get_session_store("sibling")
        sibling_state = sstore.read()
        sibling_state.confirmed.claude_session_id = "sibling-uuid-rewind"
        sibling_state.confirmed.claude_project_root = str(parent_repo)
        sstore.write(sibling_state)

        parent_original = get_transcript_path(str(parent_repo), "parent-uuid-rewind")
        sibling_original = get_transcript_path(str(parent_repo), "sibling-uuid-rewind")
        rewind_copy = get_transcript_path(str(parent_repo), "rewind-fresh-uuid")
        for path, text in [
            (parent_original, "PARENT\n"),
            (sibling_original, "SIBLING\n"),
            (rewind_copy, "TRUNCATED\n"),
        ]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

        manager.delete_session("rewind-child", delete_transcripts=True, delete_worktree=False, force=True)

        assert not rewind_copy.exists(), "rewind fresh transcript copy should be removed"
        assert parent_original.exists(), "parent's original transcript must be preserved"
        assert sibling_original.exists(), "sibling transcript in the same encoded dir must be preserved"
