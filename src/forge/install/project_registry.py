"""Trusted Forge project registry (``~/.forge/projects.json``)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, NoReturn, cast

from forge.core.paths import get_forge_home
from forge.core.state import (
    atomic_write_json,
    file_lock_for_target,
    now_iso,
    read_versioned_json_object,
)
from forge.core.state.exceptions import StateCorruptedError, StateUnreadableError
from forge.install.exceptions import ForgeInstallError

PROJECT_REGISTRY_FILENAME = "projects.json"
PROJECT_REGISTRY_VERSION = 1
PROJECT_REGISTRY_SOURCES = frozenset({"manual", "enable", "worktree", "backfill"})
PROJECTS_KEY = "projects"

EnrollmentSource = Literal["manual", "enable", "worktree", "backfill"]


class ProjectRegistryCorruptedError(ForgeInstallError, StateCorruptedError):
    """Raised when ``projects.json`` exists but is invalid."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        Exception.__init__(self, f"project registry at '{path}': {reason}")


class ProjectRegistryUnreadableError(ForgeInstallError, StateUnreadableError):
    """Raised when ``projects.json`` cannot be read for environmental reasons."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        Exception.__init__(self, f"project registry at '{path}': {reason}")


@dataclass(frozen=True)
class EnrolledProject:
    canonical_path: str
    enrolled_at: str
    enrollment_source: EnrollmentSource


@dataclass(frozen=True)
class ProjectRegistry:
    schema_version: int
    projects: tuple[EnrolledProject, ...]

    @classmethod
    def empty(cls) -> "ProjectRegistry":
        return cls(schema_version=PROJECT_REGISTRY_VERSION, projects=())


@dataclass(frozen=True)
class ProjectRegistryReadResult:
    registry: ProjectRegistry
    degraded: str | None = None

    @property
    def enrolled_roots(self) -> tuple[EnrolledProject, ...]:
        return self.registry.projects


@dataclass(frozen=True)
class EnrollmentResult:
    entry: EnrolledProject
    created: bool


@dataclass(frozen=True)
class EnrolledRootLookup:
    enrolled: bool
    enrolled_root: str | None
    degraded: str | None = None


@dataclass(frozen=True)
class ProjectRegistryDiagnosis:
    path: str
    status: str
    enrolled_count: int
    stale_roots: tuple[str, ...]
    error: str | None
    advice: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "status": self.status,
            "enrolled_count": self.enrolled_count,
            "stale_roots": list(self.stale_roots),
            "error": self.error,
            "advice": self.advice,
        }


def get_project_registry_path() -> Path:
    """Return the user-global trusted-project registry path."""

    return get_forge_home() / PROJECT_REGISTRY_FILENAME


def canonicalize_project_path(path: str | Path) -> str:
    """Return the stored path form: absolute, symlink-resolved, spelling-preserving."""

    return str(Path(path).expanduser().resolve(strict=False))


def project_path_lookup_key(path: str | Path) -> str:
    """Return the exact canonical comparison key shared by registry writes and reads."""

    return canonicalize_project_path(path)


def _same_existing_path(left: str | Path, right: str | Path) -> bool:
    try:
        return Path(left).samefile(Path(right))
    except OSError:
        return False


def project_paths_match(enrolled_path: str | Path, candidate_path: str | Path) -> bool:
    """Return whether two project roots refer to the same trusted root."""

    enrolled_key = project_path_lookup_key(enrolled_path)
    candidate_key = project_path_lookup_key(candidate_path)
    if enrolled_key == candidate_key:
        return True
    if _same_existing_path(enrolled_key, candidate_key):
        return True
    return False


def _handle_registry_version_mismatch(path: Path, _data: dict[str, Any], version: Any) -> NoReturn:
    raise ProjectRegistryCorruptedError(
        str(path),
        f"incompatible schema_version {version} (this Forge expects {PROJECT_REGISTRY_VERSION}). "
        f"Delete {path} and run 'forge extension enable' again in trusted projects.",
    )


def _registry_from_data(path: Path, data: dict[str, Any]) -> ProjectRegistry:
    allowed_top = {"schema_version", PROJECTS_KEY}
    unknown = set(data) - allowed_top
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ProjectRegistryCorruptedError(str(path), f"unknown field(s): {names}")

    projects_raw = data.get(PROJECTS_KEY, [])
    if not isinstance(projects_raw, list):
        raise ProjectRegistryCorruptedError(str(path), f"{PROJECTS_KEY} must be a list")

    projects: list[EnrolledProject] = []
    for index, item in enumerate(projects_raw):
        if not isinstance(item, dict):
            raise ProjectRegistryCorruptedError(str(path), f"{PROJECTS_KEY}[{index}] must be an object")
        allowed_project = {"canonical_path", "enrolled_at", "enrollment_source"}
        unknown_project = set(item) - allowed_project
        if unknown_project:
            names = ", ".join(sorted(unknown_project))
            raise ProjectRegistryCorruptedError(str(path), f"{PROJECTS_KEY}[{index}] unknown field(s): {names}")

        canonical_path = item.get("canonical_path")
        enrolled_at = item.get("enrolled_at")
        source = item.get("enrollment_source")
        if not isinstance(canonical_path, str) or not canonical_path:
            raise ProjectRegistryCorruptedError(str(path), f"{PROJECTS_KEY}[{index}].canonical_path must be a string")
        if not isinstance(enrolled_at, str) or not enrolled_at:
            raise ProjectRegistryCorruptedError(str(path), f"{PROJECTS_KEY}[{index}].enrolled_at must be a string")
        if source not in PROJECT_REGISTRY_SOURCES:
            raise ProjectRegistryCorruptedError(
                str(path),
                f"{PROJECTS_KEY}[{index}].enrollment_source must be one of {sorted(PROJECT_REGISTRY_SOURCES)}",
            )
        projects.append(
            EnrolledProject(
                canonical_path=canonicalize_project_path(canonical_path),
                enrolled_at=enrolled_at,
                enrollment_source=cast(EnrollmentSource, source),
            )
        )

    return ProjectRegistry(schema_version=PROJECT_REGISTRY_VERSION, projects=tuple(projects))


class ProjectRegistryStore:
    """Read and mutate the trusted-project registry."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_project_registry_path()

    def read_strict(self) -> ProjectRegistry:
        """Read the registry strictly; missing file means no enrolled projects."""

        if not self.path.exists():
            return ProjectRegistry.empty()

        data = read_versioned_json_object(
            self.path,
            version_key="schema_version",
            expected_version=PROJECT_REGISTRY_VERSION,
            corrupted_error=ProjectRegistryCorruptedError,
            unreadable_error=ProjectRegistryUnreadableError,
            on_version_mismatch=_handle_registry_version_mismatch,
        )
        return _registry_from_data(self.path, data)

    def read_for_hook(self) -> ProjectRegistryReadResult:
        """Read for hook/dispatcher use: fail open but surface a degraded reason."""

        try:
            return ProjectRegistryReadResult(registry=self.read_strict())
        except (ProjectRegistryCorruptedError, ProjectRegistryUnreadableError, OSError) as e:
            return ProjectRegistryReadResult(registry=ProjectRegistry.empty(), degraded=str(e))

    def enroll(self, root: str | Path, source: EnrollmentSource) -> EnrollmentResult:
        """Enroll *root* idempotently under the registry lock."""

        if source not in PROJECT_REGISTRY_SOURCES:
            raise ValueError(f"unsupported enrollment source: {source}")

        canonical_path = canonicalize_project_path(root)
        with file_lock_for_target(target_path=self.path, timeout_s=5.0):
            registry = self.read_strict()
            for entry in registry.projects:
                if project_paths_match(entry.canonical_path, canonical_path):
                    return EnrollmentResult(entry=entry, created=False)

            entry = EnrolledProject(
                canonical_path=canonical_path,
                enrolled_at=now_iso(),
                enrollment_source=source,
            )
            self._write(ProjectRegistry(schema_version=PROJECT_REGISTRY_VERSION, projects=(*registry.projects, entry)))
            return EnrollmentResult(entry=entry, created=True)

    def contains_root(self, root: str | Path) -> bool:
        """Return True when *root* is an enrolled canonical root."""

        registry = self.read_strict()
        return any(project_paths_match(entry.canonical_path, root) for entry in registry.projects)

    def lookup_enrolled_root(self, start: str | Path) -> EnrolledRootLookup:
        """Return whether *start* is inside an enrolled Forge project root."""

        from forge.core.ops.context import find_forge_root

        root = find_forge_root(Path(start).expanduser().resolve(strict=False))
        if root is None:
            return EnrolledRootLookup(enrolled=False, enrolled_root=None)

        read = self.read_for_hook()
        if read.degraded is not None:
            return EnrolledRootLookup(enrolled=False, enrolled_root=None, degraded=read.degraded)

        for entry in read.registry.projects:
            if project_paths_match(entry.canonical_path, root):
                return EnrolledRootLookup(enrolled=True, enrolled_root=entry.canonical_path)
        return EnrolledRootLookup(enrolled=False, enrolled_root=None)

    def stale_roots(self) -> tuple[str, ...]:
        """Return enrolled roots whose path no longer exists."""

        registry = self.read_strict()
        return tuple(entry.canonical_path for entry in registry.projects if not Path(entry.canonical_path).exists())

    def _write(self, registry: ProjectRegistry) -> None:
        data = {
            "schema_version": registry.schema_version,
            PROJECTS_KEY: [asdict(entry) for entry in registry.projects],
        }
        atomic_write_json(self.path, data)


def diagnose_project_registry(path: Path | None = None) -> ProjectRegistryDiagnosis:
    """Return the doctor-facing registry status."""

    store = ProjectRegistryStore(path)
    display = str(store.path)
    if not store.path.exists():
        return ProjectRegistryDiagnosis(
            path=display,
            status="missing",
            enrolled_count=0,
            stale_roots=(),
            error=None,
            advice=None,
        )

    try:
        registry = store.read_strict()
        stale = store.stale_roots()
    except ProjectRegistryCorruptedError as e:
        return ProjectRegistryDiagnosis(
            path=display,
            status="corrupt",
            enrolled_count=0,
            stale_roots=(),
            error=e.reason,
            advice=f"Delete {display} and run 'forge extension enable' again in trusted projects.",
        )
    except ProjectRegistryUnreadableError as e:
        return ProjectRegistryDiagnosis(
            path=display,
            status="unreadable",
            enrolled_count=0,
            stale_roots=(),
            error=e.reason,
            advice="Fix file permissions or the underlying filesystem error, then retry.",
        )

    return ProjectRegistryDiagnosis(
        path=display,
        status="stale_roots" if stale else "ok",
        enrolled_count=len(registry.projects),
        stale_roots=stale,
        error=None,
        advice=(
            "Stale roots are report-only here; reconcile/prune is handled by the cleanup tickets." if stale else None
        ),
    )
