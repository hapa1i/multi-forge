"""Tests for shared install path and ownership policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.core.runtime_vocab import CLAUDE_CODE_RUNTIME, CODEX_RUNTIME
from forge.install import installer as installer_module
from forge.install import path_policy as path_policy_module
from forge.install import runtime_removal as runtime_removal_module
from forge.install.exceptions import (
    NestedClaudeDirectoryError,
    PathBoundaryViolationError,
)
from forge.install.models import Installation, InstalledSkillPackage, InstallScope
from forge.install.path_policy import (
    UnsupportedRuntimeSkillScope,
    canonical_package_path,
    get_target_root,
    runtime_skill_root,
    tracked_file_boundary,
    validate_codex_config_scope,
    validate_path_within_boundary,
)


class TestCanonicalPackagePath:
    def test_resolves_parent_symlink_without_following_leaf(self, tmp_path: Path) -> None:
        real_parent = tmp_path / "real"
        real_parent.mkdir()
        linked_parent = tmp_path / "linked"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        leaf_target = tmp_path / "outside"
        leaf_target.mkdir()
        leaf = real_parent / "skill"
        leaf.symlink_to(leaf_target, target_is_directory=True)

        assert canonical_package_path(linked_parent / "skill") == real_parent / "skill"


class TestGetTargetRoot:
    def test_user_scope_respects_claude_home(self, isolate_claude_home: Path) -> None:
        assert get_target_root(InstallScope.USER) == isolate_claude_home

    def test_imported_bindings_share_environment_target(self, isolate_claude_home: Path) -> None:
        assert {
            installer_module.get_target_root(InstallScope.USER),
            path_policy_module.get_target_root(InstallScope.USER),
            runtime_removal_module.get_target_root(InstallScope.USER),
        } == {isolate_claude_home}

    @pytest.mark.parametrize("scope", [InstallScope.PROJECT, InstallScope.LOCAL])
    def test_project_scopes(self, scope: InstallScope, tmp_path: Path) -> None:
        assert get_target_root(scope, project_root=tmp_path) == tmp_path / ".claude"

    def test_project_requires_root(self) -> None:
        with pytest.raises(ValueError, match="project_root required"):
            get_target_root(InstallScope.PROJECT)

    @pytest.mark.parametrize("relative", [Path(".claude"), Path(".claude/commands")])
    def test_rejects_nested_claude_directory(self, relative: Path, tmp_path: Path) -> None:
        nested = tmp_path / "project" / relative
        nested.mkdir(parents=True)

        with pytest.raises(NestedClaudeDirectoryError) as exc_info:
            get_target_root(InstallScope.PROJECT, project_root=nested)

        assert ".claude" in str(exc_info.value)
        assert "nested" in str(exc_info.value).lower()

    def test_allows_normal_project_root(self, tmp_path: Path) -> None:
        project = tmp_path / "my-project"
        project.mkdir()

        assert get_target_root(InstallScope.PROJECT, project_root=project) == project / ".claude"


@pytest.mark.parametrize(
    ("scope", "runtime", "expected"),
    [
        (InstallScope.USER, CLAUDE_CODE_RUNTIME, Path("/claude/skills")),
        (InstallScope.PROJECT, CLAUDE_CODE_RUNTIME, Path("/project/.claude/skills")),
        (InstallScope.LOCAL, CLAUDE_CODE_RUNTIME, Path("/project/.claude/skills")),
        (InstallScope.USER, CODEX_RUNTIME, Path("/home/.agents/skills")),
        (InstallScope.PROJECT, CODEX_RUNTIME, Path("/project/.agents/skills")),
    ],
)
def test_runtime_skill_roots_match_reviewed_scope_contract(
    scope: InstallScope,
    runtime: str,
    expected: Path,
) -> None:
    assert (
        runtime_skill_root(
            runtime,
            scope,
            user_home=Path("/home"),
            claude_home=Path("/claude"),
            project_root=Path("/project"),
        )
        == expected
    )


def test_codex_local_scope_has_no_target() -> None:
    with pytest.raises(UnsupportedRuntimeSkillScope, match="does not support local"):
        runtime_skill_root(
            CODEX_RUNTIME,
            InstallScope.LOCAL,
            user_home=Path("/home"),
            claude_home=Path("/claude"),
            project_root=Path("/project"),
        )


class TestValidatePathWithinBoundary:
    @pytest.mark.parametrize("relative", [Path("commands/test.md"), Path("a/b/c/d/file.txt")])
    def test_accepts_nested_path(self, relative: Path, tmp_path: Path) -> None:
        boundary = tmp_path / ".claude"
        boundary.mkdir()

        validate_path_within_boundary(boundary / relative, boundary)

    @pytest.mark.parametrize("target", [Path("other/malicious.txt"), Path(".claude/../escaped.txt")])
    def test_rejects_path_outside_boundary(self, target: Path, tmp_path: Path) -> None:
        boundary = tmp_path / ".claude"
        boundary.mkdir()

        with pytest.raises(PathBoundaryViolationError) as exc_info:
            validate_path_within_boundary(tmp_path / target, boundary, "delete")

        assert "security violation" in str(exc_info.value)
        assert "delete" in str(exc_info.value)

    def test_rejects_system_path(self, tmp_path: Path) -> None:
        boundary = tmp_path / ".claude"
        boundary.mkdir()

        with pytest.raises(PathBoundaryViolationError):
            validate_path_within_boundary(Path("/etc/passwd"), boundary)

    def test_accepts_leaf_symlink_inside_boundary(self, tmp_path: Path) -> None:
        boundary = tmp_path / ".claude"
        boundary.mkdir()
        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("outside")
        symlink = boundary / "sneaky_link"
        symlink.symlink_to(outside_file)

        validate_path_within_boundary(symlink, boundary)

    def test_rejects_leaf_symlink_outside_boundary(self, tmp_path: Path) -> None:
        boundary = tmp_path / ".claude"
        boundary.mkdir()
        inside_file = boundary / "inside.txt"
        inside_file.write_text("inside")
        symlink = tmp_path / "outside_link"
        symlink.symlink_to(inside_file)

        with pytest.raises(PathBoundaryViolationError):
            validate_path_within_boundary(symlink, boundary)

    def test_error_includes_operation(self, tmp_path: Path) -> None:
        boundary = tmp_path / ".claude"
        boundary.mkdir()

        with pytest.raises(PathBoundaryViolationError, match="remove backup file"):
            validate_path_within_boundary(Path("/some/other/path"), boundary, "remove backup file")


def test_tracked_file_boundary_rejects_duplicate_package_claims(tmp_path: Path) -> None:
    target = tmp_path / ".agents" / "skills" / "understand" / "SKILL.md"
    package = InstalledSkillPackage(
        runtime=CODEX_RUNTIME,
        skill="understand",
        target_dir=str(target.parent),
        file_paths=[str(target)],
    )
    installation = Installation(
        scope="project",
        mode="copy",
        profile="standard",
        skill_packages=[package, package],
    )

    with pytest.raises(PathBoundaryViolationError, match="one tracked skill package"):
        tracked_file_boundary(
            installation,
            target,
            "delete file",
            scope=InstallScope.PROJECT,
            project_root=tmp_path,
        )


def test_legacy_tracked_file_boundary_uses_environment_target(isolate_claude_home: Path) -> None:
    installation = Installation(scope="user", mode="copy", profile="standard")
    target = isolate_claude_home / "commands" / "legacy.md"

    assert (
        tracked_file_boundary(
            installation,
            target,
            "delete file",
            scope=InstallScope.USER,
            project_root=None,
        )
        == isolate_claude_home
    )


def test_codex_scope_validator_preserves_project_root_error(tmp_path: Path) -> None:
    installation = Installation(
        scope="project",
        mode="copy",
        profile="standard",
        codex_config_path=str(tmp_path / "config.toml"),
    )

    with pytest.raises(ValueError, match="project_root required for project scope"):
        validate_codex_config_scope(installation, scope=InstallScope.PROJECT, project_root=None)
