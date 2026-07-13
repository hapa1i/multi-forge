"""Project-local Forge compatibility guardrail (``.forge/project.toml``)."""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from forge import __version__
from forge.install.exceptions import ForgeInstallError

PROJECT_COMPAT_FILENAME = "project.toml"
PROJECT_COMPAT_SCHEMA_VERSION = 1
_FORGE_DEV_VAR = "FORGE_DEV"
_FORGE_SIDECAR_VAR = "FORGE_SIDECAR"

logger = logging.getLogger(__name__)


def format_project_compatibility_recovery(
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    """Return a provenance-neutral recovery hint for compatibility refusals."""

    env = os.environ if environment is None else environment
    parts = ["Run a Forge version satisfying required_forge, or edit/reset project state."]
    if env.get(_FORGE_DEV_VAR):
        parts.append("Changes to FORGE_DEV take effect only after relaunching the managed session.")
    if env.get(_FORGE_SIDECAR_VAR) == "1":
        parts.append("For a sidecar session, use an image containing a satisfying Forge version.")
    return " ".join(parts)


class ProjectCompatibilityError(ForgeInstallError):
    """Raised when a project compatibility pin blocks a command path."""

    def __init__(self, path: str, reason: str, *, state: str = "invalid") -> None:
        self.path = path
        self.reason = reason
        self.state = state
        self.recovery = format_project_compatibility_recovery()
        super().__init__(f"{path}: {reason}. {self.recovery}")


@dataclass(frozen=True)
class ProjectCompatibilitySkip:
    """Structured refusal for a target in a multi-project mutation."""

    target: str
    forge_root: str
    state: str
    reason: str
    recovery: str

    @classmethod
    def from_error(
        cls,
        *,
        target: str,
        forge_root: str | Path,
        error: ProjectCompatibilityError,
    ) -> ProjectCompatibilitySkip:
        """Build a stable per-target refusal from the strict enforcer error."""

        return cls(
            target=target,
            forge_root=str(Path(forge_root).resolve()),
            state=error.state,
            reason=error.reason,
            recovery=error.recovery,
        )

    def to_dict(self) -> dict[str, str]:
        """Return the existing target/root/state refusal wire shape."""

        return {
            "target": self.target,
            "root": self.forge_root,
            "state": self.state,
            "reason": self.reason,
            "recovery": self.recovery,
        }


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

    return _evaluate_project_compatibility(data, path=path_str, running_forge=running_forge)


def check_project_compatibility_toml(
    content: bytes,
    *,
    path: str | Path,
    running_forge: str = __version__,
) -> ProjectCompatibilityResult:
    """Check compatibility from prospective tracked TOML bytes."""

    path_str = str(path)
    try:
        data = tomllib.load(BytesIO(content))
    except tomllib.TOMLDecodeError as e:
        raise ProjectCompatibilityError(path_str, f"invalid TOML: {e}", state="malformed") from e
    return _evaluate_project_compatibility(data, path=path_str, running_forge=running_forge)


def _evaluate_project_compatibility(
    data: Mapping[str, object],
    *,
    path: str,
    running_forge: str,
) -> ProjectCompatibilityResult:
    """Validate parsed project compatibility data against one Forge version."""

    allowed = {"schema_version", "required_forge"}
    unknown = set(data) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ProjectCompatibilityError(path, f"unknown field(s): {names}", state="malformed")

    schema_version = data.get("schema_version")
    if schema_version != PROJECT_COMPAT_SCHEMA_VERSION:
        raise ProjectCompatibilityError(
            path,
            f"unsupported schema_version {schema_version!r} (this Forge expects {PROJECT_COMPAT_SCHEMA_VERSION})",
            state="unsupported_schema",
        )

    required = data.get("required_forge")
    if not isinstance(required, str) or not required.strip():
        raise ProjectCompatibilityError(path, "required_forge must be a non-empty string", state="malformed")

    try:
        specifier = SpecifierSet(required)
    except InvalidSpecifier as e:
        raise ProjectCompatibilityError(path, f"invalid required_forge specifier: {e}", state="malformed") from e

    try:
        running = Version(running_forge)
    except InvalidVersion as e:
        raise ProjectCompatibilityError(
            path,
            f"running Forge version {running_forge!r} is not parseable",
            state="malformed",
        ) from e

    if not specifier.contains(running, prereleases=True):
        reason = f"project requires Forge {required}, but running Forge is {running_forge}"
        return ProjectCompatibilityResult(
            path=path,
            state="incompatible",
            compatible=False,
            required_forge=required,
            running_forge=running_forge,
            reason=reason,
        )

    return ProjectCompatibilityResult(
        path=path,
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


def diagnose_project_compatibility_for_hook(
    *project_roots: str | Path | None,
    operation: str,
    running_forge: str = __version__,
) -> tuple[ProjectCompatibilityResult, ...]:
    """Diagnose all project roots touched by one hook invocation without blocking it."""

    results: list[ProjectCompatibilityResult] = []
    degraded: list[str] = []
    seen: set[str] = set()
    for project_root in project_roots:
        if project_root is None:
            continue
        try:
            root_key = str(Path(project_root).resolve())
        except Exception:
            root_key = str(project_root)
        if root_key in seen:
            continue
        seen.add(root_key)
        try:
            result = check_project_compatibility_for_hook(project_root, running_forge=running_forge)
        except Exception as e:
            degraded.append(f"{root_key}: unexpected read failure: {e}")
            continue
        results.append(result)
        if result.degraded:
            degraded.append(f"{result.state} at {result.path}: {result.degraded}")

    if degraded:
        logger.debug(
            "Project compatibility degraded for hook %s: %s",
            operation,
            "; ".join(degraded),
        )
    return tuple(results)


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


def enforce_project_compatibility_toml(
    content: bytes,
    *,
    path: str | Path,
    running_forge: str = __version__,
) -> ProjectCompatibilityResult:
    """Raise when prospective tracked TOML bytes block a mutation."""

    result = check_project_compatibility_toml(content, path=path, running_forge=running_forge)
    if not result.compatible:
        raise ProjectCompatibilityError(result.path, result.reason or "project is incompatible", state=result.state)
    return result


def diagnose_project_compatibility(
    project_root: str | Path | None,
) -> ProjectCompatibilityResult:
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
        result = check_project_compatibility(project_root)
    except ProjectCompatibilityError as e:
        return ProjectCompatibilityResult(
            path=e.path,
            state=e.state,
            compatible=False,
            required_forge=None,
            running_forge=__version__,
            reason=f"{e.reason}. {e.recovery}",
        )

    if result.compatible:
        return result
    reason = result.reason or "project is incompatible"
    return replace(result, reason=f"{reason}. {format_project_compatibility_recovery()}")
