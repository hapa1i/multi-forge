"""Regressions for O089/O090: config cleanup and traversal crossed file boundaries.

Root causes: ``config_copy.py`` treated exact allowlisted directories as one
unconditional copy/cleanup unit, and ``_resolve_glob`` did not filter nested
``.git`` or ``node_modules`` components. Cleanup could therefore remove tracked
descendants, while copy could import excluded vendored or Git-internal config.
The per-file fix also followed symlinked directory components while checking Git
against their lexical paths, allowing cleanup or copy to escape the worktree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.session.worktree import cleanup as cleanup_module
from forge.session.worktree.cleanup import _prune_empty_parents, remove_config_files
from forge.session.worktree.config_copy import copy_runtime_config

pytestmark = pytest.mark.regression


def test_bug_o089_cleanup_preserves_tracked_and_excluded_directory_descendants(git_repo: Path) -> None:
    certs = git_repo / "docker" / "certs"
    certs.mkdir(parents=True)
    tracked = certs / "tracked.pem"
    tracked.write_text("tracked")
    subprocess.run(["git", "add", "docker/certs/tracked.pem"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Track certificate"], cwd=git_repo, check=True, capture_output=True)

    removable = certs / "local.pem"
    removable.write_text("local")
    vendored = certs / "node_modules" / "vendor.pem"
    vendored.parent.mkdir()
    vendored.write_text("vendor")
    git_internal = certs / ".git" / "private.pem"
    git_internal.parent.mkdir()
    git_internal.write_text("private")

    removed = remove_config_files(git_repo)

    assert removed == ["docker/certs/local.pem"]
    assert tracked.read_text() == "tracked"
    assert vendored.read_text() == "vendor"
    assert git_internal.read_text() == "private"
    assert not removable.exists()


def test_bug_o089_cleanup_rechecks_tracking_immediately_before_unlink(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracked = git_repo / ".env"
    tracked.write_text("tracked")
    subprocess.run(["git", "add", ".env"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Track environment"], cwd=git_repo, check=True, capture_output=True)
    monkeypatch.setattr(cleanup_module, "get_copied_config_files", lambda _root: [tracked])

    removed = remove_config_files(git_repo)

    assert removed == []
    assert tracked.read_text() == "tracked"


def test_bug_o089_cleanup_rechecks_symlink_parent_immediately_before_unlink(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = git_repo.parent / "outside-late-symlink"
    outside.mkdir()
    private_key = outside / "private.key"
    private_key.write_text("private")
    docker = git_repo / "docker"
    docker.mkdir()
    lexical_path = docker / "private.key"
    monkeypatch.setattr(cleanup_module, "get_copied_config_files", lambda _root: [lexical_path])

    def _replace_parent_with_symlink(_path: Path, _root: Path) -> bool:
        docker.rmdir()
        docker.symlink_to(outside, target_is_directory=True)
        return False

    monkeypatch.setattr(cleanup_module, "is_file_tracked", _replace_parent_with_symlink)

    removed = remove_config_files(git_repo)

    assert removed == []
    assert private_key.read_text() == "private"


def test_bug_o089_cleanup_prunes_only_empty_config_directories(git_repo: Path) -> None:
    certs = git_repo / "docker" / "certs"
    certs.mkdir(parents=True)
    (certs / "local.pem").write_text("local")
    unrelated = git_repo / "docker" / "keep.txt"
    unrelated.write_text("keep")

    removed = remove_config_files(git_repo)

    assert removed == ["docker/certs/local.pem"]
    assert not certs.exists()
    assert unrelated.read_text() == "keep"


def test_bug_o089_cleanup_skips_symlinked_directory_outside_worktree(git_repo: Path) -> None:
    outside = git_repo.parent / "outside-certs"
    outside.mkdir()
    private_key = outside / "private.key"
    private_key.write_text("private")
    other = outside / "other.txt"
    other.write_text("other")
    (git_repo / "docker").mkdir()
    (git_repo / "docker" / "certs").symlink_to(outside, target_is_directory=True)

    removed = remove_config_files(git_repo)

    assert removed == []
    assert private_key.read_text() == "private"
    assert other.read_text() == "other"


def test_bug_o089_cleanup_skips_symlinked_directory_with_tracked_target(git_repo: Path) -> None:
    shared = git_repo / "shared"
    shared.mkdir()
    tracked = shared / "tracked.pem"
    tracked.write_text("tracked")
    subprocess.run(["git", "add", "shared/tracked.pem"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Track shared certificate"], cwd=git_repo, check=True, capture_output=True)
    (git_repo / "docker").mkdir()
    (git_repo / "docker" / "certs").symlink_to("../shared", target_is_directory=True)

    removed = remove_config_files(git_repo)

    assert removed == []
    assert tracked.read_text() == "tracked"


def test_bug_o089_cleanup_skips_symlinked_directory_ancestor(git_repo: Path) -> None:
    outside = git_repo.parent / "outside-docker"
    certs = outside / "certs"
    certs.mkdir(parents=True)
    private_key = certs / "private.key"
    private_key.write_text("private")
    (git_repo / "docker").symlink_to(outside, target_is_directory=True)

    removed = remove_config_files(git_repo)

    assert removed == []
    assert private_key.read_text() == "private"


def test_bug_o089_empty_parent_pruning_does_not_follow_symlinked_ancestor(git_repo: Path) -> None:
    outside = git_repo.parent / "outside-empty-parent"
    certs = outside / "certs"
    certs.mkdir(parents=True)
    (git_repo / "docker").symlink_to(outside, target_is_directory=True)

    _prune_empty_parents(git_repo / "docker" / "certs", git_repo)

    assert certs.is_dir()


def test_bug_o089_copy_skips_symlinked_destination_ancestor(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    outside = tmp_path / "outside"
    source_certs = source / "docker" / "certs"
    source_certs.mkdir(parents=True)
    (source_certs / "private.pem").write_text("private")
    target.mkdir()
    outside.mkdir()
    (target / "docker").symlink_to(outside, target_is_directory=True)

    result = copy_runtime_config(source, target, allowlist=("docker/certs",))

    assert result.copied == []
    assert result.skipped_exists == ["docker/certs"]
    assert not (outside / "certs").exists()


def test_bug_o089_copy_skips_symlinked_source_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    outside = tmp_path / "outside-source"
    source.mkdir()
    target.mkdir()
    outside.mkdir()
    (outside / "private.pem").write_text("private")
    (source / "docker").mkdir()
    (source / "docker" / "certs").symlink_to(outside, target_is_directory=True)

    result = copy_runtime_config(source, target, allowlist=("docker/certs",))

    assert result.copied == []
    assert result.skipped_not_found == ["docker/certs"]
    assert not (target / "docker").exists()


def test_bug_o090_glob_copy_excludes_git_and_node_modules_at_every_depth(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()

    included = source / "app" / ".mcp.json"
    included.parent.mkdir()
    included.write_text("included")
    excluded = (
        source / "node_modules" / "root-package" / ".mcp.json",
        source / "packages" / "ui" / "node_modules" / "nested-package" / ".mcp.json",
        source / ".git" / "scratch" / ".mcp.json",
        source / "packages" / "api" / ".git" / "scratch" / ".mcp.json",
    )
    for path in excluded:
        path.parent.mkdir(parents=True)
        path.write_text("excluded")

    result = copy_runtime_config(source, target, allowlist=("**/.mcp.json",))

    assert result.copied == ["app/.mcp.json"]
    assert (target / "app" / ".mcp.json").read_text() == "included"
    for path in excluded:
        assert not (target / path.relative_to(source)).exists()
