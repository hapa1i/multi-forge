"""Tests for SessionManager-generated session names."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import forge.session.manager as manager_module
from forge.session import IndexStore, SessionManager


def _init_project(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / ".forge").mkdir()


def test_relaunch_name_generation_scopes_existing_names_by_forge_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    other_root = tmp_path / "other"
    target_root = tmp_path / "target"
    _init_project(other_root)
    _init_project(target_root)

    manager = SessionManager(index_store=IndexStore())
    manager.start_session("other-root-name", worktree_path=str(other_root), direct=True)
    manager.start_session("target-root-name", worktree_path=str(target_root), direct=True)

    existing_sets: list[set[str]] = []

    def _capture_existing(existing: set[str]) -> str:
        existing_sets.append(existing)
        return "fresh-name"

    monkeypatch.setattr(manager_module, "generate_unique_name", _capture_existing)

    assert manager._generate_relaunch_name(forge_root=str(target_root)) == "fresh-name"
    assert existing_sets == [{"target-root-name"}]
