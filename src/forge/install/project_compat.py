"""Project-local Forge compatibility guardrail (``.forge/project.toml``)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from forge import __version__
from forge.install.exceptions import ForgeInstallError

PROJECT_COMPAT_FILENAME = "project.toml"
PROJECT_COMPAT_SCHEMA_VERSION = 1


class ProjectCompatibilityError(ForgeInstallError):
    """Raised when a project compatibility pin blocks a command path."""

    def __init__(self, path: str, reason: str, *, state: str = "invalid") -> None:
        self.path = path
        self.reason = reason
        self.state = state
        super().__init__(f"{path}: {reason}")


@dataclass(frozen=True)
class ProjectCompatibilityResult:
    path: str
    state: str
    compatible: bool
    required_forge: str | None
    running_forge: str
    reason: str | None = None
    degraded: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "state": self.state,
            "compatible": self.compatible,
            "required_forge": self.required_forge,
            "running_forge": self.running_forge,
            "reason": self.reason,
            "degraded": self.degraded,
        }


def get_project_compat_path(project_root: str | Path) -> Path:
    """Return the compatibility file path for *project_root*."""

    return Path(project_root) / ".forge" / PROJECT_COMPAT_FILENAME


def check_project_compatibility(
    project_root: str | Path,
    *,
    running_forge: str = __version__,
) -> ProjectCompatibilityResult:
    """Strict command-path compatibility check for a project root."""

    path = get_project_compat_path(project_root)
    path_str = str(path)
    if not path.exists():
        return ProjectCompatibilityResult(
            path=path_str,
            state="missing",
            compatible=True,
            required_forge=None,
            running_forge=running_forge,
        )

    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ProjectCompatibilityError(path_str, f"invalid TOML: {e}", state="malformed") from e
    except OSError as e:
        raise ProjectCompatibilityError(path_str, f"read error: {e}", state="unreadable") from e

    allowed = {"schema_version", "required_forge"}
    unknown = set(data) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ProjectCompatibilityError(path_str, f"unknown field(s): {names}", state="malformed")

    schema_version = data.get("schema_version")
    if schema_version != PROJECT_COMPAT_SCHEMA_VERSION:
        raise ProjectCompatibilityError(
            path_str,
            f"unsupported schema_version {schema_version!r} (this Forge expects {PROJECT_COMPAT_SCHEMA_VERSION})",
            state="unsupported_schema",
        )

    required = data.get("required_forge")
    if not isinstance(required, str) or not required.strip():
        raise ProjectCompatibilityError(path_str, "required_forge must be a non-empty string", state="malformed")

    try:
        specifier = SpecifierSet(required)
    except InvalidSpecifier as e:
        raise ProjectCompatibilityError(path_str, f"invalid required_forge specifier: {e}", state="malformed") from e

    try:
        running = Version(running_forge)
    except InvalidVersion as e:
        raise ProjectCompatibilityError(
            path_str,
            f"running Forge version {running_forge!r} is not parseable",
            state="malformed",
        ) from e

    if running not in specifier:
        reason = (
            f"project requires Forge {required}, but running Forge is {running_forge}. "
            "Upgrade the global Forge or reset project state."
        )
        return ProjectCompatibilityResult(
            path=path_str,
            state="incompatible",
            compatible=False,
            required_forge=required,
            running_forge=running_forge,
            reason=reason,
        )

    return ProjectCompatibilityResult(
        path=path_str,
        state="compatible",
        compatible=True,
        required_forge=required,
        running_forge=running_forge,
    )


def check_project_compatibility_for_hook(
    project_root: str | Path,
    *,
    running_forge: str = __version__,
) -> ProjectCompatibilityResult:
    """Lenient hook-path check: warn/degrade, never block a coding session."""

    try:
        result = check_project_compatibility(project_root, running_forge=running_forge)
    except ProjectCompatibilityError as e:
        return ProjectCompatibilityResult(
            path=e.path,
            state=e.state,
            compatible=True,
            required_forge=None,
            running_forge=running_forge,
            reason=e.reason,
            degraded=e.reason,
        )

    if result.compatible:
        return result

    return ProjectCompatibilityResult(
        path=result.path,
        state=result.state,
        compatible=True,
        required_forge=result.required_forge,
        running_forge=result.running_forge,
        reason=result.reason,
        degraded=result.reason,
    )


def enforce_project_compatibility(
    project_root: str | Path | None,
    *,
    running_forge: str = __version__,
) -> ProjectCompatibilityResult:
    """Raise when a project-local pin blocks command-path mutation."""

    if project_root is None:
        return ProjectCompatibilityResult(
            path="",
            state="no_project",
            compatible=True,
            required_forge=None,
            running_forge=running_forge,
        )

    result = check_project_compatibility(project_root, running_forge=running_forge)
    if not result.compatible:
        raise ProjectCompatibilityError(result.path, result.reason or "project is incompatible", state=result.state)
    return result


def diagnose_project_compatibility(project_root: str | Path | None) -> ProjectCompatibilityResult:
    """Return the doctor-facing compatibility status for the current project."""

    if project_root is None:
        return ProjectCompatibilityResult(
            path="",
            state="no_project",
            compatible=True,
            required_forge=None,
            running_forge=__version__,
        )

    try:
        return check_project_compatibility(project_root)
    except ProjectCompatibilityError as e:
        return ProjectCompatibilityResult(
            path=e.path,
            state=e.state,
            compatible=False,
            required_forge=None,
            running_forge=__version__,
            reason=e.reason,
        )
