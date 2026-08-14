"""Install target mapping and fail-closed path ownership policy.

This module owns pure path decisions shared by install planning, installation,
unmanaged-package discovery, and runtime-scoped removal. It never mutates the
filesystem.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from forge.core.runtime import get_runtime
from forge.core.runtime_vocab import CLAUDE_CODE_RUNTIME, CODEX_RUNTIME
from forge.session.claude.paths import get_claude_home

from .codex_hooks import get_codex_config_path
from .exceptions import (
    CodexConfigScopeMismatchError,
    NestedClaudeDirectoryError,
    PathBoundaryViolationError,
)
from .models import Installation, InstalledSkillPackage, InstallScope


class UnsupportedRuntimeSkillScope(ValueError):
    """Raised when a direct target lookup has no safe runtime/scope mapping."""


def canonical_package_path(path: Path) -> Path:
    """Resolve parent components while preserving the final path entry."""

    absolute = Path(os.path.abspath(path.expanduser()))
    return absolute.parent.resolve() / absolute.name


def get_target_root(scope: InstallScope, project_root: Path | None = None) -> Path:
    """Return the Claude extension root for an installation scope."""

    if scope == InstallScope.USER:
        return get_claude_home()
    if project_root is None:
        raise ValueError("project_root required for PROJECT/LOCAL scope")

    resolved = project_root.resolve()
    if ".claude" in resolved.parts:
        raise NestedClaudeDirectoryError(str(project_root))
    return project_root / ".claude"


def runtime_skill_root(
    runtime: str,
    scope: InstallScope,
    *,
    user_home: Path,
    claude_home: Path,
    project_root: Path | None,
) -> Path:
    """Return the reviewed skill root for one runtime/scope pair.

    Paths are composed lexically and no directory is created. In particular,
    Codex skills never use ``CODEX_HOME`` and Codex local scope is rejected
    rather than mapped to the shared project directory.
    """

    spec = get_runtime(runtime)
    if scope.value not in spec.skill_scopes:
        raise UnsupportedRuntimeSkillScope(f"runtime '{runtime}' does not support {scope.value} skill scope")

    if runtime == CLAUDE_CODE_RUNTIME:
        root = claude_home if scope == InstallScope.USER else _require_project_root(scope, project_root) / ".claude"
        return root / "skills"
    if runtime == CODEX_RUNTIME:
        if scope == InstallScope.USER:
            return user_home / ".agents" / "skills"
        return _require_project_root(scope, project_root) / ".agents" / "skills"
    raise ValueError(f"runtime '{runtime}' declares skill scopes but has no Forge target mapping")


def get_runtime_skill_root(runtime: str, scope: InstallScope, project_root: Path | None = None) -> Path:
    """Return the environment-backed runtime skill root used by installation."""

    return runtime_skill_root(
        runtime,
        scope,
        user_home=Path.home(),
        claude_home=get_claude_home(),
        project_root=project_root,
    )


def validate_path_within_boundary(
    path: Path,
    boundary: Path,
    operation: str = "delete",
) -> None:
    """Require the path entry itself to remain within an expected boundary."""

    # Resolve the parent and append the leaf lexically so validation checks a
    # symlink's location rather than its target. The same expression works for
    # missing leaves while still canonicalizing symlinks in the parent chain.
    resolved_path = path.parent.resolve() / path.name
    resolved_boundary = boundary.resolve()
    if not resolved_path.is_relative_to(resolved_boundary):
        raise PathBoundaryViolationError(str(path), str(boundary), operation)


def tracked_skill_package_target(
    package: InstalledSkillPackage,
    scope: InstallScope,
    project_root: Path | None,
    operation: str,
) -> tuple[Path, Path]:
    """Validate one tracked package location and return target/expected paths."""

    runtime_root = get_runtime_skill_root(package.runtime, scope, project_root)
    expected_target = runtime_root / package.skill
    validate_path_within_boundary(expected_target, runtime_root, operation)
    target = Path(package.target_dir)
    if not target.is_absolute():
        raise PathBoundaryViolationError(str(target), str(expected_target), operation)
    expected_location = expected_target.parent.resolve() / expected_target.name
    target_location = target.parent.resolve() / target.name
    if target_location != expected_location:
        raise PathBoundaryViolationError(str(target), str(expected_target), operation)
    validate_real_skill_package_directory(target, expected_target, operation)
    return target, expected_target


def validate_tracked_skill_package_files(
    package: InstalledSkillPackage,
    package_dir: Path,
    expected_target: Path,
    operation: str,
) -> None:
    """Validate every tracked file without traversing substituted directories."""

    for tracked_file in package.file_paths:
        validate_skill_package_file_path(Path(tracked_file), package_dir, expected_target, operation)


def tracked_file_boundary(
    installation: Installation,
    target: Path,
    operation: str,
    *,
    scope: InstallScope,
    project_root: Path | None,
) -> Path:
    """Return a tracked file's reviewed runtime boundary.

    Legacy rows have no package grouping and remain constrained to the
    historical Claude target. A v2 package row narrows the file to the
    reviewed runtime root and its exact package directory.
    """

    target_key = str(target)
    package_matches = [package for package in installation.skill_packages if target_key in package.file_paths]
    if not package_matches:
        return get_target_root(scope, project_root)
    if len(package_matches) != 1:
        raise PathBoundaryViolationError(target_key, "one tracked skill package", operation)

    package = package_matches[0]
    try:
        runtime_root = get_runtime_skill_root(package.runtime, scope, project_root)
        tracked_package_dir, expected_package_dir = tracked_skill_package_target(
            package,
            scope,
            project_root,
            operation,
        )
    except (KeyError, ValueError) as e:
        raise PathBoundaryViolationError(target_key, f"known {scope.value} runtime skill root", operation) from e
    validate_skill_package_file_path(target, tracked_package_dir, expected_package_dir, operation)
    return runtime_root


def validate_codex_config_scope(
    existing: Installation,
    *,
    scope: InstallScope,
    project_root: Path | None,
) -> None:
    """Refuse a tracked Codex config outside the current scope mapping."""

    if not existing.codex_config_path:
        return
    tracked = Path(existing.codex_config_path)
    expected = get_codex_config_path(scope, project_root)
    if tracked.resolve() != expected.resolve():
        raise CodexConfigScopeMismatchError(str(tracked), str(expected))


def validate_real_skill_package_directory(path: Path, expected_target: Path, operation: str) -> None:
    """Require an existing package directory entry to be real, never a symlink."""

    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError as e:
        raise PathBoundaryViolationError(str(path), str(expected_target), operation) from e
    if not stat.S_ISDIR(mode):
        raise PathBoundaryViolationError(str(path), f"{expected_target} (real directory)", operation)


def validate_skill_package_file_path(
    tracked_file: Path,
    package_dir: Path,
    expected_target: Path,
    operation: str,
) -> None:
    """Validate one package file path without traversing substituted directories."""

    if not tracked_file.is_absolute():
        raise PathBoundaryViolationError(str(tracked_file), str(expected_target), operation)
    validate_path_within_boundary(tracked_file, expected_target, operation)
    try:
        relative = tracked_file.relative_to(package_dir)
    except ValueError as e:
        raise PathBoundaryViolationError(str(tracked_file), str(expected_target), operation) from e
    if not relative.parts or ".." in relative.parts:
        raise PathBoundaryViolationError(str(tracked_file), str(expected_target), operation)

    current = package_dir
    for component in relative.parts[:-1]:
        current /= component
        validate_real_skill_package_directory(current, expected_target, operation)


def _require_project_root(scope: InstallScope, project_root: Path | None) -> Path:
    if project_root is None:
        raise ValueError(f"project_root required for {scope.value} skill scope")
    return project_root
