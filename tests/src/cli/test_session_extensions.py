"""Tests for worktree extension auto-install and fork handoff flags.

Covers _detect_parent_extensions(), _auto_install_extensions(),
and _generate_parent_handoff_context() from forge.cli.session.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from forge.cli.session import (
    _auto_install_extensions,
    _detect_parent_extensions,
    _generate_parent_handoff_context,
    _resolve_worktree_extension_root,
)
from forge.install.models import Installation
from forge.session.models import SessionState, create_session_state


@pytest.fixture
def parent_root(tmp_path: Path) -> Path:
    """Simulated parent project root."""
    root = tmp_path / "parent"
    root.mkdir()
    (root / ".git").mkdir()
    return root


@pytest.fixture
def worktree_root(tmp_path: Path) -> Path:
    """Simulated worktree path."""
    wt = tmp_path / "worktree"
    wt.mkdir()
    return wt


def _make_installation(profile: str = "standard", mode: str = "copy") -> Installation:
    """Create a minimal Installation record for testing."""
    return Installation(
        scope="local",
        mode=mode,
        profile=profile,
        modules_enabled=["commands", "agents", "skills", "hooks", "status-line", "permissions"],
    )


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------


class TestDetectParentExtensions:
    """Test _detect_parent_extensions 3-tier detection strategy."""

    def test_detect_local_install(self, parent_root: Path) -> None:
        """LOCAL installation at parent root returns its (profile, mode)."""
        install = _make_installation(profile="full", mode="symlink")
        with patch("forge.install.tracking.TrackingStore") as mock_cls:
            store = mock_cls.return_value
            store.get_installation.side_effect = lambda scope, path=None: (install if scope == "local" else None)
            result = _detect_parent_extensions(parent_root)

        assert result == ("full", "symlink")

    def test_detect_user_fallback(self, parent_root: Path) -> None:
        """No LOCAL install; falls back to USER-scope installation."""
        user_install = _make_installation(profile="standard", mode="copy")
        with patch("forge.install.tracking.TrackingStore") as mock_cls:
            store = mock_cls.return_value
            store.get_installation.side_effect = lambda scope, path=None: (user_install if scope == "user" else None)
            result = _detect_parent_extensions(parent_root)

        assert result == ("standard", "copy")

    def test_detect_hooks_fallback(self, parent_root: Path) -> None:
        """No tracking records; has_forge_hooks returns True -> defaults."""
        with (
            patch("forge.install.tracking.TrackingStore") as mock_cls,
            patch("forge.install.hooks.has_forge_hooks", return_value=True),
        ):
            store = mock_cls.return_value
            store.get_installation.return_value = None
            result = _detect_parent_extensions(parent_root)

        assert result == ("standard", "copy")

    def test_detect_nothing(self, parent_root: Path) -> None:
        """No tracking records, no hooks -> None."""
        with (
            patch("forge.install.tracking.TrackingStore") as mock_cls,
            patch("forge.install.hooks.has_forge_hooks", return_value=False),
        ):
            store = mock_cls.return_value
            store.get_installation.return_value = None
            result = _detect_parent_extensions(parent_root)

        assert result is None

    def test_detect_hooks_fallback_survives_tracking_failure(self, parent_root: Path) -> None:
        """Corrupt tracking store doesn't prevent hook-based fallback."""
        with (
            patch("forge.install.tracking.TrackingStore") as mock_cls,
            patch("forge.install.hooks.has_forge_hooks", return_value=True),
        ):
            mock_cls.return_value.get_installation.side_effect = RuntimeError("corrupt JSON")
            result = _detect_parent_extensions(parent_root)

        assert result == ("standard", "copy")

    def test_detect_inherits_profile(self, parent_root: Path) -> None:
        """Profile is inherited from the actual parent installation."""
        for profile in ("minimal", "standard", "full"):
            install = _make_installation(profile=profile, mode="copy")
            with patch("forge.install.tracking.TrackingStore") as mock_cls:
                store = mock_cls.return_value
                store.get_installation.side_effect = lambda scope, path=None, _i=install: (
                    _i if scope == "local" else None
                )
                result = _detect_parent_extensions(parent_root)

            assert result is not None
            assert result[0] == profile


# ---------------------------------------------------------------------------
# Auto-install tests
# ---------------------------------------------------------------------------


class TestAutoInstallExtensions:
    """Test _auto_install_extensions with various flag/detection combos."""

    def test_inherits_from_parent(self, worktree_root: Path, parent_root: Path) -> None:
        """Detected parent extensions triggers Installer.init() with inherited profile."""
        mock_plan = MagicMock()
        mock_plan.modules = ["commands", "agents", "skills", "hooks", "status-line", "permissions"]
        mock_plan.has_conflicts = False

        with (
            patch(
                "forge.cli.session._detect_parent_extensions",
                return_value=("full", "symlink"),
            ),
            patch("forge.install.installer.Installer") as mock_installer_cls,
        ):
            installer = mock_installer_cls.return_value
            installer.init.return_value = mock_plan

            result = _auto_install_extensions(
                install_root=worktree_root,
                parent_project_root=parent_root,
            )

        assert result is True
        mock_installer_cls.assert_called_once()
        assert mock_installer_cls.call_args.kwargs["project_root"] == worktree_root
        call_kwargs = installer.init.call_args
        assert call_kwargs[1]["profile"].value == "full"
        assert call_kwargs[1]["mode"].value == "symlink"
        # force=False (default) to avoid clobbering checked-in .claude/* files
        assert call_kwargs[1].get("force", False) is False

    def test_conflicts_reports_false(self, worktree_root: Path, parent_root: Path) -> None:
        """Installer returning conflicts should report failure, not false success."""
        mock_plan = MagicMock()
        mock_plan.has_conflicts = True

        with (
            patch(
                "forge.cli.session._detect_parent_extensions",
                return_value=("standard", "copy"),
            ),
            patch("forge.install.installer.Installer") as mock_installer_cls,
        ):
            installer = mock_installer_cls.return_value
            installer.init.return_value = mock_plan

            result = _auto_install_extensions(
                install_root=worktree_root,
                parent_project_root=parent_root,
            )

        assert result is False

    def test_skips_when_no_parent(self, worktree_root: Path, parent_root: Path) -> None:
        """No parent extensions detected -> Installer not called."""
        with (
            patch("forge.cli.session._detect_parent_extensions", return_value=None),
            patch("forge.install.installer.Installer") as mock_installer_cls,
        ):
            result = _auto_install_extensions(
                install_root=worktree_root,
                parent_project_root=parent_root,
            )

        assert result is False
        mock_installer_cls.assert_not_called()

    def test_no_extensions_flag_skips(self, worktree_root: Path, parent_root: Path) -> None:
        """force_extensions=False skips even when parent has extensions."""
        with patch("forge.install.installer.Installer") as mock_installer_cls:
            result = _auto_install_extensions(
                install_root=worktree_root,
                parent_project_root=parent_root,
                force_extensions=False,
            )

        assert result is False
        mock_installer_cls.assert_not_called()

    def test_extensions_flag_forces(self, worktree_root: Path, parent_root: Path) -> None:
        """force_extensions=True installs even when no parent detected."""
        mock_plan = MagicMock()
        mock_plan.modules = ["commands", "hooks"]
        mock_plan.has_conflicts = False

        with patch("forge.install.installer.Installer") as mock_installer_cls:
            installer = mock_installer_cls.return_value
            installer.init.return_value = mock_plan

            result = _auto_install_extensions(
                install_root=worktree_root,
                parent_project_root=parent_root,
                force_extensions=True,
            )

        assert result is True
        call_kwargs = installer.init.call_args
        assert call_kwargs[1]["profile"].value == "standard"
        assert call_kwargs[1]["mode"].value == "copy"

    def test_install_failure_is_non_blocking(self, worktree_root: Path, parent_root: Path) -> None:
        """Installer failure returns False without raising."""
        with (
            patch(
                "forge.cli.session._detect_parent_extensions",
                return_value=("standard", "copy"),
            ),
            patch("forge.install.installer.Installer") as mock_installer_cls,
        ):
            installer = mock_installer_cls.return_value
            installer.init.side_effect = RuntimeError("install failed")

            result = _auto_install_extensions(
                install_root=worktree_root,
                parent_project_root=parent_root,
            )

        assert result is False


class TestResolveWorktreeExtensionRoot:
    """Test extension target root selection for worktree sessions."""

    def test_prefers_nested_forge_root_inside_worktree(self, tmp_path: Path) -> None:
        worktree_root = tmp_path / "wt"
        nested_root = worktree_root / "packages" / "app"
        nested_root.mkdir(parents=True)

        manifest = create_session_state(
            name="child",
            worktree_path=str(worktree_root),
            worktree_branch="child",
        )
        assert manifest.worktree is not None
        manifest.worktree.is_worktree = True
        manifest.forge_root = str(nested_root)

        assert _resolve_worktree_extension_root(manifest) == nested_root

    def test_falls_back_to_checkout_root_for_root_scoped_worktree(self, tmp_path: Path) -> None:
        parent_root = tmp_path / "repo"
        worktree_root = tmp_path / "repo-child"
        parent_root.mkdir()
        worktree_root.mkdir()

        manifest = create_session_state(
            name="child",
            worktree_path=str(worktree_root),
            worktree_branch="child",
        )
        assert manifest.worktree is not None
        manifest.worktree.is_worktree = True
        manifest.forge_root = str(parent_root)

        assert _resolve_worktree_extension_root(manifest) == worktree_root


# ---------------------------------------------------------------------------
# Handoff strategy/inline-plan threading tests (WI-2)
# ---------------------------------------------------------------------------


class TestGenerateParentHandoffContext:
    """Test _generate_parent_handoff_context strategy and inline_plan threading."""

    def _make_fork_state(self, tmp_path: Path, parent_name: str = "planner") -> SessionState:
        """Create a fork manifest pointing at a parent session."""
        state = create_session_state(
            name="fork-child",
            parent_session=parent_name,
            is_fork=True,
            worktree_path=str(tmp_path / "fork-wt"),
        )
        (tmp_path / "fork-wt").mkdir(exist_ok=True)
        return state

    def _make_parent_state(self, tmp_path: Path) -> SessionState:
        """Create a parent session state."""
        parent_dir = tmp_path / "parent-wt"
        parent_dir.mkdir(exist_ok=True)
        (parent_dir / ".git").mkdir(exist_ok=True)

        state = create_session_state(
            name="planner",
            worktree_path=str(parent_dir),
        )
        state.confirmed.claude_session_id = "parent-uuid"
        return state

    def test_strategy_threads_to_process_handoff(self, tmp_path: Path) -> None:
        """Strategy parameter reaches process_handoff."""
        fork_state = self._make_fork_state(tmp_path)
        parent_state = self._make_parent_state(tmp_path)

        mock_manager = MagicMock()
        mock_manager.get_session.return_value = parent_state
        mock_manager.resolve_project_root.return_value = str(tmp_path / "parent-wt")

        with patch("forge.session.handoff.process_handoff") as mock_handoff:
            mock_handoff.return_value = MagicMock(context_file=None, warnings=[])

            _generate_parent_handoff_context(
                manager=mock_manager,
                manifest=fork_state,
                strategy="full",
                inline_plan=True,
            )

        call_kwargs = mock_handoff.call_args[1]
        assert call_kwargs["strategy"].value == "full"
        assert call_kwargs["inline_plan"] is True

    def test_default_strategy_is_structured(self, tmp_path: Path) -> None:
        """Default strategy should be structured."""
        fork_state = self._make_fork_state(tmp_path)
        parent_state = self._make_parent_state(tmp_path)

        mock_manager = MagicMock()
        mock_manager.get_session.return_value = parent_state
        mock_manager.resolve_project_root.return_value = str(tmp_path / "parent-wt")

        with patch("forge.session.handoff.process_handoff") as mock_handoff:
            mock_handoff.return_value = MagicMock(context_file=None, warnings=[])
            _generate_parent_handoff_context(manager=mock_manager, manifest=fork_state)

        call_kwargs = mock_handoff.call_args[1]
        assert call_kwargs["strategy"].value == "structured"
        assert call_kwargs["inline_plan"] is False

    def test_invalid_strategy_falls_back_to_structured(self, tmp_path: Path) -> None:
        """Unknown strategy string falls back to structured."""
        fork_state = self._make_fork_state(tmp_path)
        parent_state = self._make_parent_state(tmp_path)

        mock_manager = MagicMock()
        mock_manager.get_session.return_value = parent_state
        mock_manager.resolve_project_root.return_value = str(tmp_path / "parent-wt")

        with patch("forge.session.handoff.process_handoff") as mock_handoff:
            mock_handoff.return_value = MagicMock(context_file=None, warnings=[])
            _generate_parent_handoff_context(manager=mock_manager, manifest=fork_state, strategy="nonexistent")

        call_kwargs = mock_handoff.call_args[1]
        assert call_kwargs["strategy"].value == "structured"

    def test_project_root_is_main_repo_not_worktree(self, tmp_path: Path) -> None:
        """project_root must be the main repo root, not the parent worktree."""
        fork_state = self._make_fork_state(tmp_path)
        parent_state = self._make_parent_state(tmp_path)

        mock_manager = MagicMock()
        mock_manager.get_session.return_value = parent_state
        mock_manager.resolve_project_root.return_value = str(tmp_path / "main-repo")

        with patch("forge.session.handoff.process_handoff") as mock_handoff:
            mock_handoff.return_value = MagicMock(context_file=None, warnings=[])
            _generate_parent_handoff_context(manager=mock_manager, manifest=fork_state)

        call_kwargs = mock_handoff.call_args[1]
        assert str(call_kwargs["forge_root"]) == str(tmp_path / "main-repo")
        parent_wt = Path(parent_state.worktree.path) if parent_state.worktree else None
        assert call_kwargs["parent_worktree_root"] == parent_wt

    def test_nested_forge_root_preferred_over_checkout_root(self, tmp_path: Path) -> None:
        """Nested forge_root should win over checkout-root fallback for artifact lookups."""
        fork_state = self._make_fork_state(tmp_path)
        parent_state = self._make_parent_state(tmp_path)
        nested_root = tmp_path / "main-repo" / "packages" / "app"
        parent_state.forge_root = str(nested_root)

        mock_manager = MagicMock()
        mock_manager.get_session.return_value = parent_state
        mock_manager.resolve_project_root.return_value = str(tmp_path / "main-repo")

        with patch("forge.session.handoff.process_handoff") as mock_handoff:
            mock_handoff.return_value = MagicMock(context_file=None, warnings=[])
            _generate_parent_handoff_context(manager=mock_manager, manifest=fork_state)

        call_kwargs = mock_handoff.call_args[1]
        assert call_kwargs["forge_root"] == nested_root


# ---------------------------------------------------------------------------
# Schema + --into model tests (WI-3)
# ---------------------------------------------------------------------------


class TestWorktreeOwnership:
    """Test Worktree.owns_worktree field and schema v7."""

    def test_worktree_owns_by_default(self) -> None:
        """New Worktree instances default to owns_worktree=True."""
        from forge.session.models import Worktree

        wt = Worktree(path="/tmp/wt", branch="main", is_worktree=True)
        assert wt.owns_worktree is True

    def test_into_worktree_does_not_own(self) -> None:
        """--into sessions set owns_worktree=False."""
        from forge.session.models import Worktree

        wt = Worktree(path="/tmp/wt", branch="feat", is_worktree=True, owns_worktree=False)
        assert wt.owns_worktree is False

    def test_fork_session_into_sets_owns_false(self, tmp_path: Path) -> None:
        """Manager.fork_session(into_path=...) sets owns_worktree=False."""
        parent_state = create_session_state(
            name="planner",
            worktree_path=str(tmp_path),
        )
        parent_state.confirmed.claude_session_id = "uuid-123"

        into_dir = tmp_path / "executor-wt"
        into_dir.mkdir()
        (into_dir / ".git").mkdir()
        (into_dir / ".forge").mkdir()

        from forge.session.exceptions import SessionNotFoundError
        from forge.session.manager import SessionManager
        from forge.session.models import SessionIndexEntry

        parent_entry = SessionIndexEntry(
            worktree_path=str(tmp_path),
            project_root=str(tmp_path),
            last_accessed_at="2026-01-01T00:00:00Z",
            forge_root=str(tmp_path),
            checkout_root=str(tmp_path),
            relative_path=".",
        )

        real_mgr = SessionManager()
        real_mgr.index_store = MagicMock()
        real_mgr.index_store.session_exists.return_value = False
        real_mgr.index_store.add_from_state = MagicMock()

        def _get_session(name: str, forge_root: str | None = None) -> SessionIndexEntry:
            if name == "planner" and forge_root is None:
                return parent_entry
            raise SessionNotFoundError(name)

        real_mgr.index_store.get_session.side_effect = _get_session

        with (
            patch.object(real_mgr, "get_session", return_value=parent_state),
            patch("forge.session.worktree.get_main_repo_root", return_value=tmp_path),
            patch("forge.session.store.SessionStore.write"),
        ):
            _, fork_state = real_mgr.fork_session(
                "planner",
                fork_name="reviewer",
                into_path=str(into_dir),
                branch="executor-branch",
            )

        assert fork_state.worktree is not None
        assert fork_state.worktree.is_worktree is True
        assert fork_state.worktree.owns_worktree is False
        assert fork_state.worktree.path == str(into_dir)


# ---------------------------------------------------------------------------
# Ref-count worktree delete guard tests (WI-4)
# ---------------------------------------------------------------------------


class TestWorktreeDeleteGuard:
    """Test that delete_session skips worktree removal when co-resident sessions exist."""

    def test_find_co_resident_sessions(self, tmp_path: Path) -> None:
        """_find_co_resident_sessions returns other sessions in the same worktree."""
        from forge.session.index import SessionIndexEntry
        from forge.session.manager import SessionManager

        wt_path = str(tmp_path / "shared-wt")
        other_path = str(tmp_path / "other-wt")

        mgr = SessionManager()
        mgr.index_store = MagicMock()
        mgr.index_store.list_sessions.return_value = [
            ("session-a", SessionIndexEntry(worktree_path=wt_path, project_root=str(tmp_path), last_accessed_at="")),
            ("session-b", SessionIndexEntry(worktree_path=wt_path, project_root=str(tmp_path), last_accessed_at="")),
            ("session-c", SessionIndexEntry(worktree_path=other_path, project_root=str(tmp_path), last_accessed_at="")),
        ]

        result = mgr._find_co_resident_sessions(wt_path, exclude="session-a")
        assert result == ["session-b"]

    def test_find_co_resident_empty_when_alone(self, tmp_path: Path) -> None:
        """No co-residents when session is the only one in its worktree."""
        from forge.session.index import SessionIndexEntry
        from forge.session.manager import SessionManager

        wt_path = str(tmp_path / "solo-wt")

        mgr = SessionManager()
        mgr.index_store = MagicMock()
        mgr.index_store.list_sessions.return_value = [
            ("solo", SessionIndexEntry(worktree_path=wt_path, project_root=str(tmp_path), last_accessed_at="")),
        ]

        result = mgr._find_co_resident_sessions(wt_path, exclude="solo")
        assert result == []

    def test_delete_skips_worktree_when_co_residents_exist(self, tmp_path: Path) -> None:
        """delete_session should not call cleanup_worktree when other sessions share the worktree."""
        from forge.session.index import SessionIndexEntry
        from forge.session.manager import SessionManager

        wt_path = str(tmp_path / "shared-wt")
        (tmp_path / "shared-wt").mkdir()

        state = create_session_state(name="doomed", worktree_path=wt_path, worktree_branch="feat")
        assert state.worktree is not None
        state.worktree.is_worktree = True

        mgr = SessionManager()
        mgr.index_store = MagicMock()
        mgr.index_store.get_session.return_value = SessionIndexEntry(
            worktree_path=wt_path, project_root=str(tmp_path), last_accessed_at=""
        )
        mgr.index_store.list_sessions.return_value = [
            ("doomed", SessionIndexEntry(worktree_path=wt_path, project_root=str(tmp_path), last_accessed_at="")),
            ("survivor", SessionIndexEntry(worktree_path=wt_path, project_root=str(tmp_path), last_accessed_at="")),
        ]

        with (
            patch("forge.session.store.SessionStore.exists", return_value=True),
            patch("forge.session.store.SessionStore.read", return_value=state),
            patch("forge.session.store.SessionStore.delete"),
            patch("forge.session.claude.cleanup.cleanup_session"),
            patch("forge.session.worktree.cleanup.cleanup_worktree") as mock_cleanup,
        ):
            mgr.delete_session("doomed", force=True)

        mock_cleanup.assert_not_called()

    def test_delete_into_session_never_removes_worktree(self, tmp_path: Path) -> None:
        """--into session (owns_worktree=False) never removes worktree even if last."""
        from forge.session.index import SessionIndexEntry
        from forge.session.manager import SessionManager

        wt_path = str(tmp_path / "executor-wt")
        (tmp_path / "executor-wt").mkdir()

        state = create_session_state(name="reviewer", worktree_path=wt_path, worktree_branch="feat")
        assert state.worktree is not None
        state.worktree.is_worktree = True
        state.worktree.owns_worktree = False

        mgr = SessionManager()
        mgr.index_store = MagicMock()
        mgr.index_store.get_session.return_value = SessionIndexEntry(
            worktree_path=wt_path, project_root=str(tmp_path), last_accessed_at=""
        )
        mgr.index_store.list_sessions.return_value = [
            ("reviewer", SessionIndexEntry(worktree_path=wt_path, project_root=str(tmp_path), last_accessed_at="")),
        ]

        with (
            patch("forge.session.store.SessionStore.exists", return_value=True),
            patch("forge.session.store.SessionStore.read", return_value=state),
            patch("forge.session.store.SessionStore.delete"),
            patch("forge.session.claude.cleanup.cleanup_session"),
            patch("forge.session.worktree.cleanup.cleanup_worktree") as mock_cleanup,
        ):
            mgr.delete_session("reviewer", force=True)

        mock_cleanup.assert_not_called()

    def test_delete_shared_worktree_no_dirty_error(self, tmp_path: Path) -> None:
        """Deleting from a shared dirty worktree should NOT raise DirtyWorktreeError."""
        from forge.session.index import SessionIndexEntry
        from forge.session.manager import SessionManager

        wt_path = str(tmp_path / "dirty-shared-wt")
        (tmp_path / "dirty-shared-wt").mkdir()

        state = create_session_state(name="session-a", worktree_path=wt_path, worktree_branch="feat")
        assert state.worktree is not None
        state.worktree.is_worktree = True

        mgr = SessionManager()
        mgr.index_store = MagicMock()
        mgr.index_store.get_session.return_value = SessionIndexEntry(
            worktree_path=wt_path, project_root=str(tmp_path), last_accessed_at=""
        )
        # Two sessions share the worktree
        mgr.index_store.list_sessions.return_value = [
            ("session-a", SessionIndexEntry(worktree_path=wt_path, project_root=str(tmp_path), last_accessed_at="")),
            ("session-b", SessionIndexEntry(worktree_path=wt_path, project_root=str(tmp_path), last_accessed_at="")),
        ]

        with (
            patch("forge.session.store.SessionStore.exists", return_value=True),
            patch("forge.session.store.SessionStore.read", return_value=state),
            patch("forge.session.store.SessionStore.delete"),
            patch("forge.session.claude.cleanup.cleanup_session"),
            patch("forge.session.worktree.cleanup.is_worktree_dirty", return_value=True) as mock_dirty,
            patch("forge.session.worktree.cleanup.cleanup_worktree") as mock_cleanup,
        ):
            # Should NOT raise DirtyWorktreeError even though worktree is dirty
            mgr.delete_session("session-a")  # no --force needed

        mock_dirty.assert_not_called()  # Dirty check should be skipped entirely
        mock_cleanup.assert_not_called()

    def test_owner_first_guest_last_cleans_up(self, tmp_path: Path) -> None:
        """Deleting owner first, then guest last: guest should NOT clean up (it doesn't own)."""
        from forge.session.index import SessionIndexEntry
        from forge.session.manager import SessionManager

        wt_path = str(tmp_path / "shared-wt")
        (tmp_path / "shared-wt").mkdir()

        # Guest session (--into, owns_worktree=False) is the last one
        guest_state = create_session_state(name="reviewer", worktree_path=wt_path, worktree_branch="feat")
        assert guest_state.worktree is not None
        guest_state.worktree.is_worktree = True
        guest_state.worktree.owns_worktree = False

        mgr = SessionManager()
        mgr.index_store = MagicMock()
        mgr.index_store.get_session.return_value = SessionIndexEntry(
            worktree_path=wt_path, project_root=str(tmp_path), last_accessed_at=""
        )
        # Owner already deleted — guest is the only one left
        mgr.index_store.list_sessions.return_value = [
            ("reviewer", SessionIndexEntry(worktree_path=wt_path, project_root=str(tmp_path), last_accessed_at="")),
        ]

        with (
            patch("forge.session.store.SessionStore.exists", return_value=True),
            patch("forge.session.store.SessionStore.read", return_value=guest_state),
            patch("forge.session.store.SessionStore.delete"),
            patch("forge.session.claude.cleanup.cleanup_session"),
            patch("forge.session.worktree.cleanup.cleanup_worktree") as mock_cleanup,
        ):
            mgr.delete_session("reviewer", force=True)

        # Guest never removes worktree — it's orphaned (expected, documented behavior)
        mock_cleanup.assert_not_called()
