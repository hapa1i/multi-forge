"""Tests for workspace-wide session resolution (core.ops.resolution)."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.core.ops.resolution import ResolvedSession, resolve_session_repo_wide
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.exceptions import AmbiguousSessionError, SessionNotFoundError


def _seed_session(
    forge_root: Path,
    name: str,
    project_root: Path,
) -> None:
    """Seed a session in a forge_root with index entry."""
    (forge_root / ".forge" / "sessions" / name).mkdir(parents=True, exist_ok=True)
    manifest = create_session_state(
        name,
        proxy_template="t",
        proxy_base_url="http://localhost:9999",
        worktree_path=str(forge_root),
    )
    manifest.forge_root = str(forge_root)
    SessionStore(str(forge_root), name).write(manifest)
    IndexStore().add_session(
        name=name,
        worktree_path=str(forge_root),
        project_root=str(project_root),
        forge_root=str(forge_root),
    )


class TestResolveSessionRepoWide:
    """Two-tier resolver: current-project preference with workspace-wide fallback."""

    def test_same_forge_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Session in current forge_root resolves as Tier 1 (not cross-project)."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        fr = tmp_path / "project"
        fr.mkdir()
        (fr / ".git").mkdir()
        (fr / ".forge").mkdir()
        _seed_session(fr, "alpha", project_root=fr)

        resolved = resolve_session_repo_wide("alpha", str(fr))

        assert isinstance(resolved, ResolvedSession)
        assert resolved.name == "alpha"
        assert resolved.forge_root == str(fr)
        assert resolved.is_cross_project is False

    def test_cross_project_within_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Session in sibling forge_root resolves as Tier 2 (cross-project)."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        fr_a = repo
        (fr_a / ".forge").mkdir()

        fr_b = repo / "nested"
        fr_b.mkdir()
        (fr_b / ".forge").mkdir()

        _seed_session(fr_b, "beta", project_root=repo)

        # CWD is fr_a, session lives in fr_b
        monkeypatch.chdir(repo)
        resolved = resolve_session_repo_wide("beta", str(fr_a))

        assert resolved.name == "beta"
        assert resolved.forge_root == str(fr_b)
        assert resolved.is_cross_project is True

    def test_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Session that doesn't exist anywhere raises SessionNotFoundError."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        fr = tmp_path / "project"
        fr.mkdir()
        (fr / ".git").mkdir()
        (fr / ".forge").mkdir()

        monkeypatch.chdir(fr)

        with pytest.raises(SessionNotFoundError):
            resolve_session_repo_wide("ghost", str(fr))

    def test_different_repo_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Session in a different project_root is not found from another repo."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        repo_a = tmp_path / "repo-a"
        repo_a.mkdir()
        (repo_a / ".git").mkdir()
        (repo_a / ".forge").mkdir()

        repo_b = tmp_path / "repo-b"
        repo_b.mkdir()
        (repo_b / ".git").mkdir()
        (repo_b / ".forge").mkdir()

        _seed_session(repo_b, "gamma", project_root=repo_b)

        monkeypatch.chdir(repo_a)

        with pytest.raises(SessionNotFoundError):
            resolve_session_repo_wide("gamma", str(repo_a))

    def test_ambiguous_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Same name in two forge_roots, user in neither, raises AmbiguousSessionError."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        fr_a = repo / "sub-a"
        fr_a.mkdir()
        (fr_a / ".forge").mkdir()

        fr_b = repo / "sub-b"
        fr_b.mkdir()
        (fr_b / ".forge").mkdir()

        fr_c = repo / "sub-c"
        fr_c.mkdir()
        (fr_c / ".forge").mkdir()

        _seed_session(fr_a, "shared", project_root=repo)
        _seed_session(fr_b, "shared", project_root=repo)

        monkeypatch.chdir(repo)

        with pytest.raises(AmbiguousSessionError):
            resolve_session_repo_wide("shared", str(fr_c))

    def test_tiebreaker_prefers_current(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Same name in two forge_roots, user in one: resolves to user's project."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        fr_a = repo
        (fr_a / ".forge").mkdir()

        fr_b = repo / "nested"
        fr_b.mkdir()
        (fr_b / ".forge").mkdir()

        _seed_session(fr_a, "shared", project_root=repo)
        _seed_session(fr_b, "shared", project_root=repo)

        resolved = resolve_session_repo_wide("shared", str(fr_a))

        assert resolved.forge_root == str(fr_a)
        assert resolved.is_cross_project is False

    def test_no_forge_root_uses_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When cwd_forge_root is None, derives project_root from CWD."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        fr = repo / "sub"
        fr.mkdir()
        (fr / ".forge").mkdir()

        _seed_session(fr, "delta", project_root=repo)

        monkeypatch.chdir(repo)
        resolved = resolve_session_repo_wide("delta", None)

        assert resolved.name == "delta"
        assert resolved.forge_root == str(fr)
        assert resolved.is_cross_project is True
