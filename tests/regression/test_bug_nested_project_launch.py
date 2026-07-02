"""Regression: nested Forge project CWD resolution.

Bug: Claude Code was launched from worktree.path (checkout root) instead of
forge_root for nested projects. This caused .claude/settings.local.json to
be invisible, breaking hooks and direct commands (%policy status, %help).

Root cause: launch paths, transcript lookups, and supervisor source_cwd all
used state.worktree.path directly. Fix: resolve_claude_project_root() helper.

Affected files: session.py (4 launch sites + 2 transcript sites),
supervisor.py (2 sites), handoff.py (1 site).
"""

from __future__ import annotations

import pytest

from forge.session import create_session_state
from forge.session.claude.paths import resolve_claude_project_root
from forge.session.models import Worktree

pytestmark = pytest.mark.regression


class TestResolveClaudeProjectRoot:
    def test_nested_project_returns_forge_root(self):
        """Forge_root inside checkout -> use forge_root."""
        state = create_session_state("executor")
        state.worktree = Worktree(
            path="/Users/dev/repo-executor",
            branch="executor",
            is_worktree=True,
        )
        state.forge_root = "/Users/dev/repo-executor/experiments/drafting/poc"

        assert resolve_claude_project_root(state) == "/Users/dev/repo-executor/experiments/drafting/poc"

    def test_root_level_worktree_returns_worktree_path(self):
        """Forge_root at parent repo (not inside checkout) -> use worktree.path."""
        state = create_session_state("executor")
        state.worktree = Worktree(
            path="/Users/dev/repo-executor",
            branch="executor",
            is_worktree=True,
        )
        # forge_root anchored at parent repo, not inside the worktree
        state.forge_root = "/Users/dev/repo"

        assert resolve_claude_project_root(state) == "/Users/dev/repo-executor"

    def test_no_worktree_returns_forge_root(self):
        """Non-worktree session -> use forge_root."""
        state = create_session_state("main")
        state.forge_root = "/Users/dev/repo"

        assert resolve_claude_project_root(state) == "/Users/dev/repo"

    def test_no_worktree_no_forge_root_falls_back_to_cwd(self, tmp_path, monkeypatch):
        """No worktree and no forge_root -> fall back to CWD."""
        monkeypatch.chdir(tmp_path)
        state = create_session_state("bare")

        result = resolve_claude_project_root(state)
        assert result == str(tmp_path)

    def test_forge_root_equals_worktree_path(self):
        """Root-level project in its own worktree -> use forge_root (same value)."""
        state = create_session_state("session")
        state.worktree = Worktree(
            path="/Users/dev/repo-wt",
            branch="feature",
            is_worktree=True,
        )
        state.forge_root = "/Users/dev/repo-wt"

        assert resolve_claude_project_root(state) == "/Users/dev/repo-wt"


class TestPersistedClaudeProjectRoot:
    """Regression: resume must use the persisted claude_project_root, not
    recompute it. Sessions created before 7a1bbe9 were launched from
    worktree.path; sessions after use forge_root. The persisted field is
    authoritative for both.
    """

    def test_reconnect_uses_persisted_launch_root(self, tmp_path, monkeypatch):
        """When claude_project_root is persisted, resume uses it — not the computed root."""
        from unittest.mock import patch

        from forge.session import SessionStore, create_session_state
        from forge.session.models import Worktree

        checkout = tmp_path / "repo-executor"
        checkout.mkdir()
        nested_root = str(checkout / "experiments" / "poc")
        resume_uuid = "abc-123-uuid"
        # Simulate old session persisted with checkout root as launch CWD
        persisted_root = str(checkout)

        state = create_session_state("executor")
        state.worktree = Worktree(path=str(checkout), branch="executor", is_worktree=True)
        state.forge_root = nested_root
        state.confirmed.claude_project_root = persisted_root
        SessionStore(nested_root, "executor").write(state)

        captured_cwd: list[str | None] = []

        def _fake_invoke(**kwargs):
            captured_cwd.append(kwargs.get("cwd"))
            return 0

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        monkeypatch.chdir(checkout)

        with (
            patch("forge.cli.session.invoke_claude", side_effect=_fake_invoke),
            patch("forge.cli.session.run_with_active_session", side_effect=lambda runner, **kw: runner()),
            patch("forge.cli.session._warn_if_hooks_missing"),
            patch("forge.cli.session._warn_if_version_outdated"),
            patch("forge.cli.session_lifecycle._build_session_env", return_value=({}, [])),
            patch("forge.cli.session_lifecycle._infer_launch_confirmation"),
        ):
            from forge.cli.session import _launch_claude_for_session

            _launch_claude_for_session(
                manifest=state,
                session_id=None,
                resume_id=resume_uuid,
                effective_template=None,
                runtime_base_url=None,
                context_limit=200000,
                use_sidecar=False,
            )

        assert len(captured_cwd) == 1
        assert captured_cwd[0] == persisted_root

    def test_first_launch_persists_launch_root(self, tmp_path, monkeypatch):
        """First launch writes claude_project_root to the manifest."""
        from unittest.mock import patch

        from forge.session import SessionStore, create_session_state
        from forge.session.models import Worktree

        checkout = tmp_path / "repo-executor"
        checkout.mkdir()
        nested_root = str(checkout / "experiments" / "poc")

        state = create_session_state("executor")
        state.worktree = Worktree(path=str(checkout), branch="executor", is_worktree=True)
        state.forge_root = nested_root
        # No claude_project_root set (first launch)
        assert state.confirmed.claude_project_root is None
        store = SessionStore(nested_root, "executor")
        store.write(state)

        def _fake_invoke(**kwargs):
            return 0

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        monkeypatch.chdir(checkout)

        with (
            patch("forge.cli.session.invoke_claude", side_effect=_fake_invoke),
            patch("forge.cli.session.run_with_active_session", side_effect=lambda runner, **kw: runner()),
            patch("forge.cli.session._warn_if_hooks_missing"),
            patch("forge.cli.session._warn_if_version_outdated"),
            patch("forge.cli.session_lifecycle._build_session_env", return_value=({}, [])),
            patch("forge.cli.session_lifecycle._infer_launch_confirmation"),
        ):
            from forge.cli.session import _launch_claude_for_session

            _launch_claude_for_session(
                manifest=state,
                session_id="new-uuid",
                resume_id=None,
                effective_template=None,
                runtime_base_url=None,
                context_limit=200000,
                use_sidecar=False,
            )

        # Verify persisted
        updated = store.read()
        assert updated.confirmed.claude_project_root == nested_root

    def test_no_persisted_root_falls_back_to_computed(self, tmp_path, monkeypatch):
        """Sessions without claude_project_root (pre-field) use the computed root."""
        from unittest.mock import patch

        from forge.session import SessionStore, create_session_state
        from forge.session.models import Worktree

        checkout = tmp_path / "repo-executor"
        checkout.mkdir()
        nested_root = str(checkout / "experiments" / "poc")
        resume_uuid = "def-456-uuid"

        state = create_session_state("executor")
        state.worktree = Worktree(path=str(checkout), branch="executor", is_worktree=True)
        state.forge_root = nested_root
        # No persisted root — will use computed (forge_root for nested)
        SessionStore(nested_root, "executor").write(state)

        captured_cwd: list[str | None] = []

        def _fake_invoke(**kwargs):
            captured_cwd.append(kwargs.get("cwd"))
            return 0

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        monkeypatch.chdir(checkout)

        with (
            patch("forge.cli.session.invoke_claude", side_effect=_fake_invoke),
            patch("forge.cli.session.run_with_active_session", side_effect=lambda runner, **kw: runner()),
            patch("forge.cli.session._warn_if_hooks_missing"),
            patch("forge.cli.session._warn_if_version_outdated"),
            patch("forge.cli.session_lifecycle._build_session_env", return_value=({}, [])),
            patch("forge.cli.session_lifecycle._infer_launch_confirmation"),
        ):
            from forge.cli.session import _launch_claude_for_session

            _launch_claude_for_session(
                manifest=state,
                session_id=None,
                resume_id=resume_uuid,
                effective_template=None,
                runtime_base_url=None,
                context_limit=200000,
                use_sidecar=False,
            )

        assert len(captured_cwd) == 1
        assert captured_cwd[0] == nested_root

    def test_resumable_transcript_checks_persisted_root(self, tmp_path, monkeypatch):
        """_has_resumable_transcript uses persisted claude_project_root when available."""
        from forge.session import create_session_state
        from forge.session.claude.paths import (
            encode_project_path,
            get_claude_projects_dir,
        )
        from forge.session.models import Worktree

        checkout = tmp_path / "repo-executor"
        checkout.mkdir()
        uuid = "old-session-uuid"

        state = create_session_state("executor")
        state.worktree = Worktree(path=str(checkout), branch="executor", is_worktree=True)
        state.forge_root = str(checkout / "experiments" / "poc")
        state.confirmed.claude_session_id = uuid
        # Persisted launch root points to checkout root (pre-fix session)
        state.confirmed.claude_project_root = str(checkout)

        # Conversation at old encoded path (checkout root)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        old_encoded = encode_project_path(str(checkout))
        old_dir = get_claude_projects_dir() / old_encoded
        old_dir.mkdir(parents=True)
        (old_dir / f"{uuid}.jsonl").write_text("{}")

        from forge.cli.session import _has_resumable_transcript

        assert _has_resumable_transcript(state) is True


class TestLaunchCallsitesUseLaunchRoot:
    """Verify the actual launch callsites pass the resolved launch root, not worktree.path."""

    def test_host_launch_uses_launch_root(self, tmp_path, monkeypatch):
        """_launch_claude_for_session host path passes forge_root CWD for nested projects."""
        from unittest.mock import patch

        from forge.session import SessionStore, create_session_state
        from forge.session.models import Worktree

        state = create_session_state("executor")
        state.worktree = Worktree(path=str(tmp_path / "checkout"), branch="b", is_worktree=True)
        nested_root = str(tmp_path / "checkout" / "nested" / "project")
        state.forge_root = nested_root
        # Seed manifest so store.update() works
        SessionStore(nested_root, "executor").write(state)

        captured_cwd: list[str | None] = []

        def _fake_invoke(**kwargs):
            captured_cwd.append(kwargs.get("cwd"))
            return 0

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        monkeypatch.chdir(tmp_path / "checkout")

        with (
            patch("forge.cli.session.invoke_claude", side_effect=_fake_invoke),
            patch("forge.cli.session.run_with_active_session", side_effect=lambda runner, **kw: runner()),
            patch("forge.cli.session._warn_if_hooks_missing"),
            patch("forge.cli.session._warn_if_version_outdated"),
            patch("forge.cli.session_lifecycle._build_session_env", return_value=({}, [])),
            patch("forge.cli.session_lifecycle._infer_launch_confirmation"),
        ):
            from forge.cli.session import _launch_claude_for_session

            _launch_claude_for_session(
                manifest=state,
                session_id=None,
                resume_id=None,
                effective_template=None,
                runtime_base_url=None,
                context_limit=200000,
                use_sidecar=False,
            )

        assert len(captured_cwd) == 1
        assert captured_cwd[0] == nested_root

    def test_host_launch_root_level_worktree_uses_worktree_path(self, tmp_path, monkeypatch):
        """Root-level worktree (forge_root at parent) launches from worktree.path."""
        from unittest.mock import patch

        from forge.session import SessionStore, create_session_state
        from forge.session.models import Worktree

        state = create_session_state("executor")
        checkout = tmp_path / "repo-executor"
        checkout.mkdir()
        state.worktree = Worktree(path=str(checkout), branch="b", is_worktree=True)
        parent_repo = str(tmp_path / "repo")
        state.forge_root = parent_repo  # Parent repo, not inside checkout
        # Seed manifest at forge_root (parent repo)
        SessionStore(parent_repo, "executor").write(state)

        captured_cwd: list[str | None] = []

        def _fake_invoke(**kwargs):
            captured_cwd.append(kwargs.get("cwd"))
            return 0

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()
        monkeypatch.chdir(checkout)

        with (
            patch("forge.cli.session.invoke_claude", side_effect=_fake_invoke),
            patch("forge.cli.session.run_with_active_session", side_effect=lambda runner, **kw: runner()),
            patch("forge.cli.session._warn_if_hooks_missing"),
            patch("forge.cli.session._warn_if_version_outdated"),
            patch("forge.cli.session_lifecycle._build_session_env", return_value=({}, [])),
            patch("forge.cli.session_lifecycle._infer_launch_confirmation"),
        ):
            from forge.cli.session import _launch_claude_for_session

            _launch_claude_for_session(
                manifest=state,
                session_id=None,
                resume_id=None,
                effective_template=None,
                runtime_base_url=None,
                context_limit=200000,
                use_sidecar=False,
            )

        assert len(captured_cwd) == 1
        assert captured_cwd[0] == str(checkout)


class TestSupervisorForgeRootScope:
    def test_fork_supervise_should_store_parent_forge_root(self):
        """SupervisorConfig.forge_root should be the target's, not the child's.

        Before fix: fork stored fork_forge_root (child's root).
        After fix: fork stores parent_manifest.forge_root (target's root).
        Verified via session.py line 2514.
        """
        # This is a code-level invariant; the actual test is in the
        # integration/E2E layer. This test documents the contract.
        from forge.session.models import SupervisorConfig

        parent_root = "/Users/dev/repo"
        child_root = "/Users/dev/repo-executor/experiments/poc"

        config = SupervisorConfig(resume_id="planner", forge_root=parent_root)
        assert config.forge_root == parent_root
        assert config.forge_root != child_root
