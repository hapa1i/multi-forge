"""Tests for session artifact helpers.

Covers: resolve_forge_root, get_artifact_paths, safe_copy_file,
make_timestamp_suffix, snapshot_plan_approved, ensure_dirs.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from forge.session.artifacts import (
    ensure_dirs,
    get_artifact_paths,
    make_content_hash,
    make_timestamp_suffix,
    resolve_artifact_path,
    resolve_forge_root,
    safe_copy_file,
    snapshot_plan_approved,
)


class TestResolveForgeRoot:
    """Test resolve_forge_root() with multiple fallback levels."""

    def test_git_repo_detected(self, tmp_path: Path) -> None:
        """When get_main_repo_root succeeds, its result is used."""
        with patch("forge.session.worktree.get_main_repo_root", return_value=tmp_path / "repo"):
            result = resolve_forge_root(tmp_path / "repo" / "subdir")
        assert result == tmp_path / "repo"

    def test_fallback_to_find_project_root(self, tmp_path: Path) -> None:
        """When get_main_repo_root fails, falls back to find_project_root."""
        expected = tmp_path / "fallback"
        with (
            patch("forge.session.worktree.get_main_repo_root", side_effect=RuntimeError("no git")),
            patch("forge.session.artifacts.find_project_root", return_value=expected),
        ):
            result = resolve_forge_root(tmp_path)
        assert result == expected

    def test_fallback_to_cwd(self, tmp_path: Path) -> None:
        """When both git detectors fail, returns cwd.resolve()."""
        with (
            patch("forge.session.worktree.get_main_repo_root", side_effect=RuntimeError("no git")),
            patch("forge.session.artifacts.find_project_root", side_effect=RuntimeError("no project")),
        ):
            result = resolve_forge_root(tmp_path)
        assert result == tmp_path.resolve()


class TestGetArtifactPaths:
    """Test get_artifact_paths() directory computation."""

    def test_returns_correct_structure(self, tmp_path: Path) -> None:
        paths = get_artifact_paths(tmp_path, "my-session")

        assert paths.forge_root == tmp_path.resolve()
        assert paths.artifacts_root_rel == Path(".forge/artifacts/my-session")
        assert paths.artifacts_root_abs == tmp_path.resolve() / ".forge" / "artifacts" / "my-session"

    def test_session_name_embedded_in_path(self, tmp_path: Path) -> None:
        paths = get_artifact_paths(tmp_path, "special-name")
        assert "special-name" in str(paths.plans_rel)
        assert "special-name" in str(paths.transcripts_rel)

    def test_plans_and_transcripts_subdirs(self, tmp_path: Path) -> None:
        paths = get_artifact_paths(tmp_path, "s1")
        assert paths.plans_rel == Path(".forge/artifacts/s1/plans")
        assert paths.transcripts_rel == Path(".forge/artifacts/s1/transcripts")


class TestResolveArtifactPath:
    """Test resolving stored artifact paths against forge_root."""

    def test_relative_path_uses_forge_root(self, tmp_path: Path) -> None:
        result = resolve_artifact_path(tmp_path / "packages" / "app", ".forge/artifacts/a/transcripts/t.jsonl")
        assert result == tmp_path / "packages" / "app" / ".forge" / "artifacts" / "a" / "transcripts" / "t.jsonl"

    def test_absolute_path_is_preserved(self, tmp_path: Path) -> None:
        absolute = tmp_path / "absolute.jsonl"
        result = resolve_artifact_path(tmp_path / "ignored", absolute)
        assert result == absolute

    def test_none_returns_none(self, tmp_path: Path) -> None:
        assert resolve_artifact_path(tmp_path, None) is None


class TestSafeCopyFile:
    """Test safe_copy_file() idempotent copy semantics."""

    def test_source_exists_copies(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst" / "dest.txt"
        src.write_text("content")

        result = safe_copy_file(src, dst)
        assert result is True
        assert dst.read_text() == "content"

    def test_dest_exists_no_overwrite_skips(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("new")
        dst.write_text("old")

        result = safe_copy_file(src, dst, overwrite=False)
        assert result is False
        assert dst.read_text() == "old"

    def test_dest_exists_with_overwrite(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("new")
        dst.write_text("old")

        result = safe_copy_file(src, dst, overwrite=True)
        assert result is True
        assert dst.read_text() == "new"

    def test_source_missing_raises(self, tmp_path: Path) -> None:
        src = tmp_path / "nonexistent.txt"
        dst = tmp_path / "dst.txt"
        with pytest.raises(FileNotFoundError):
            safe_copy_file(src, dst)

    def test_parent_dirs_created(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        dst = tmp_path / "a" / "b" / "c" / "dest.txt"
        src.write_text("deep")

        safe_copy_file(src, dst)
        assert dst.read_text() == "deep"


class TestMakeTimestampSuffix:
    """Test make_timestamp_suffix() formatting."""

    def test_no_colons_or_dashes(self) -> None:
        result = make_timestamp_suffix()
        assert ":" not in result
        assert "-" not in result

    def test_contains_underscore_separator(self) -> None:
        """T separator in ISO format becomes underscore."""
        result = make_timestamp_suffix()
        assert "_" in result


class TestEnsureDirs:
    """Test ensure_dirs() creates expected directories."""

    def test_creates_plan_and_transcript_dirs(self, tmp_path: Path) -> None:
        paths = get_artifact_paths(tmp_path, "test-session")
        ensure_dirs(paths)
        assert paths.plans_abs.is_dir()
        assert paths.transcripts_abs.is_dir()

    def test_idempotent(self, tmp_path: Path) -> None:
        paths = get_artifact_paths(tmp_path, "test-session")
        ensure_dirs(paths)
        ensure_dirs(paths)  # second call should not raise
        assert paths.plans_abs.is_dir()


class TestSnapshotPlanApproved:
    """Test snapshot_plan_approved() file snapshot."""

    def test_copies_plan_with_stem_and_hash_filename(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "my-plan.md"
        plan_file.write_text("# Plan content")

        paths = get_artifact_paths(tmp_path, "session-1")
        snapshot_abs, snapshot_rel = snapshot_plan_approved(paths=paths, source_plan_path=plan_file)

        assert snapshot_abs.exists()
        assert snapshot_abs.read_text() == "# Plan content"
        assert snapshot_abs.suffix == ".md"
        # Filename is "{stem}-{12-hex-chars}.md"
        assert snapshot_abs.name.startswith("my-plan-")
        hash_part = snapshot_abs.stem[len("my-plan-") :]
        assert len(hash_part) == 12
        assert all(c in "0123456789abcdef" for c in hash_part)

    def test_identical_content_produces_identical_filename(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "plan.md"
        plan_file.write_text("# Same content")

        paths = get_artifact_paths(tmp_path, "session-x")
        first_abs, first_rel = snapshot_plan_approved(paths=paths, source_plan_path=plan_file)
        second_abs, second_rel = snapshot_plan_approved(paths=paths, source_plan_path=plan_file)

        assert first_abs == second_abs
        assert first_rel == second_rel
        # Only one file exists on disk.
        assert len(list(paths.plans_abs.iterdir())) == 1

    def test_identical_content_different_source_names_different_snapshot(self, tmp_path: Path) -> None:
        """Stem-prefixed: different source filenames with identical bytes produce
        different snapshot paths. Accepted tradeoff for human-readable names."""
        paths = get_artifact_paths(tmp_path, "s")

        (tmp_path / "plan-a.md").write_text("# Same bytes")
        (tmp_path / "plan-b.md").write_text("# Same bytes")

        _, rel_a = snapshot_plan_approved(paths=paths, source_plan_path=tmp_path / "plan-a.md")
        _, rel_b = snapshot_plan_approved(paths=paths, source_plan_path=tmp_path / "plan-b.md")

        assert rel_a != rel_b
        assert "plan-a-" in str(rel_a)
        assert "plan-b-" in str(rel_b)
        assert len(list(paths.plans_abs.iterdir())) == 2

    def test_different_content_produces_different_filenames(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "plan.md"
        paths = get_artifact_paths(tmp_path, "session-y")

        plan_file.write_text("# Plan v1")
        first_abs, _ = snapshot_plan_approved(paths=paths, source_plan_path=plan_file)

        plan_file.write_text("# Plan v2 (revised)")
        second_abs, _ = snapshot_plan_approved(paths=paths, source_plan_path=plan_file)

        assert first_abs != second_abs
        assert len(list(paths.plans_abs.iterdir())) == 2

    def test_returns_abs_and_rel_paths(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "plan.md"
        plan_file.write_text("content")

        paths = get_artifact_paths(tmp_path, "s1")
        snapshot_abs, snapshot_rel = snapshot_plan_approved(paths=paths, source_plan_path=plan_file)

        assert snapshot_abs.is_absolute()
        assert not snapshot_rel.is_absolute()
        assert str(snapshot_rel).startswith(".forge/artifacts/s1/plans/")

    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        plan_file = tmp_path / "plan.md"
        plan_file.write_text("content")

        paths = get_artifact_paths(tmp_path, "new-session")
        assert not paths.plans_abs.exists()

        snapshot_plan_approved(paths=paths, source_plan_path=plan_file)
        assert paths.plans_abs.is_dir()


class TestMakeContentHash:
    """Test content-hash suffix generator."""

    def test_deterministic(self) -> None:
        assert make_content_hash(b"hello") == make_content_hash(b"hello")

    def test_different_input_different_output(self) -> None:
        assert make_content_hash(b"a") != make_content_hash(b"b")

    def test_default_length(self) -> None:
        assert len(make_content_hash(b"x")) == 12

    def test_custom_length(self) -> None:
        assert len(make_content_hash(b"x", length=8)) == 8
