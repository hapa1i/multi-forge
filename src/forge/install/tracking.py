"""Tracking store for ~/.forge/installed.json.

Manages the persistent record of what Forge has installed, enabling
reversible update and uninstall operations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, NoReturn

import dacite

from forge.core.paths import get_forge_home
from forge.core.state import (
    atomic_write_json,
    file_lock_for_target,
)

from .exceptions import TrackingCorruptedError, TrackingUnreadableError
from .models import (
    TRACKING_VERSION,
    Installation,
    InstalledFile,
    InstalledManifest,
    InstalledSettingsEntry,
    make_installation_key,
    parse_installation_key,
)

# Constants
TRACKING_FILENAME = "installed.json"
LEGACY_TRACKING_VERSION = 1


@dataclass
class _LegacyInstallation:
    """Strict v1 installation shape used only for side-effect-free migration."""

    scope: str
    mode: str
    profile: str
    project_path: str | None = None
    modules_enabled: list[str] = field(default_factory=list)
    files: list[InstalledFile] = field(default_factory=list)
    settings_entries: list[InstalledSettingsEntry] = field(default_factory=list)
    settings_backup_path: str | None = None
    codex_config_path: str | None = None
    codex_commands: list[str] = field(default_factory=list)
    installed_at: str = ""
    updated_at: str = ""


@dataclass
class _LegacyInstalledManifest:
    """Released v1 root shape; unknown fields remain hard errors."""

    version: int = LEGACY_TRACKING_VERSION
    installations: dict[str, _LegacyInstallation] = field(default_factory=dict)


def get_tracking_path() -> Path:
    """Get path to tracking file (~/.forge/installed.json)."""
    return get_forge_home() / TRACKING_FILENAME


def compute_checksum(path: Path) -> str:
    """Compute SHA256 checksum of a file.

    Args:
        path: Path to the file to checksum.

    Returns:
        Hex-encoded SHA256 hash of file contents.
    """
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _handle_tracking_version_mismatch(path: Path, _data: dict[str, Any], version: Any) -> NoReturn:
    raise TrackingCorruptedError(
        str(path),
        f"incompatible version {version} (this Forge expects {TRACKING_VERSION}). "
        f"Delete this file and run 'forge extension enable' again.",
    )


def _read_tracking_object(path: Path) -> tuple[int, dict[str, Any]]:
    """Read the JSON object and accept only released v1 or current v2.

    The shared single-version helper cannot express an accepted legacy version.
    Keep the same domain error mapping here while preserving v1's historical
    missing-version default. Reading never rewrites the file.
    """

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise TrackingCorruptedError(str(path), f"invalid JSON: {e}") from e
    except OSError as e:
        raise TrackingUnreadableError(str(path), f"read error: {e}") from e

    if not isinstance(data, dict):
        raise TrackingCorruptedError(str(path), f"expected JSON object, got {type(data).__name__}")

    version = data.get("version", LEGACY_TRACKING_VERSION)
    if isinstance(version, bool) or not isinstance(version, int):
        _handle_tracking_version_mismatch(path, data, version)
    if version not in {LEGACY_TRACKING_VERSION, TRACKING_VERSION}:
        _handle_tracking_version_mismatch(path, data, version)
    return version, data


def _deserialize_manifest(path: Path, data_class: type[Any], data: dict[str, Any]) -> Any:
    try:
        return dacite.from_dict(
            data_class=data_class,
            data=data,
            config=dacite.Config(strict=True),
        )
    except (dacite.DaciteError, TypeError, KeyError) as e:
        raise TrackingCorruptedError(str(path), f"deserialization error: {e}") from e


def _validate_current_manifest(path: Path, manifest: InstalledManifest) -> None:
    """Validate cross-field ownership invariants that dacite cannot express."""

    for installation_key, installation in manifest.installations.items():
        tracked_file_paths = {record.target_path for record in installation.files}
        claimed_package_paths: set[str] = set()
        package_keys: set[tuple[str, str]] = set()

        for package in installation.skill_packages:
            label = f"installation {installation_key!r} package {package.runtime}/{package.skill}"
            package_key = (package.runtime, package.skill)
            if package_key in package_keys:
                raise TrackingCorruptedError(str(path), f"ownership invariant error: {label} is duplicated")
            package_keys.add(package_key)

            package_dir = Path(package.target_dir)
            if not package_dir.is_absolute():
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {label} target_dir must be absolute",
                )
            if not package.file_paths:
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {label} file_paths must not be empty",
                )
            if package.file_paths != sorted(set(package.file_paths)):
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {label} file_paths must be unique and sorted",
                )

            package_paths = set(package.file_paths)
            skill_document = str(package_dir / "SKILL.md")
            if skill_document not in package_paths:
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {label} must track {skill_document}",
                )

            for raw_file_path in package.file_paths:
                file_path = Path(raw_file_path)
                if not file_path.is_absolute():
                    raise TrackingCorruptedError(
                        str(path),
                        f"ownership invariant error: {label} contains non-absolute file path {raw_file_path!r}",
                    )
                try:
                    relative_path = file_path.relative_to(package_dir)
                except ValueError as e:
                    raise TrackingCorruptedError(
                        str(path),
                        f"ownership invariant error: {label} contains file outside target_dir: {raw_file_path}",
                    ) from e
                if not relative_path.parts or ".." in relative_path.parts:
                    raise TrackingCorruptedError(
                        str(path),
                        f"ownership invariant error: {label} contains invalid package file path {raw_file_path}",
                    )

            missing_ledger_paths = package_paths - tracked_file_paths
            if missing_ledger_paths:
                missing = ", ".join(sorted(missing_ledger_paths))
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {label} is not backed by files ledger: {missing}",
                )
            duplicate_claims = package_paths & claimed_package_paths
            if duplicate_claims:
                duplicate = ", ".join(sorted(duplicate_claims))
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {label} reuses package file paths: {duplicate}",
                )
            claimed_package_paths.update(package_paths)


def _upgrade_legacy_manifest(legacy: _LegacyInstalledManifest) -> InstalledManifest:
    """Normalize v1 to the current in-memory model without inventing packages."""

    installations = {
        key: Installation(
            scope=installation.scope,
            mode=installation.mode,
            profile=installation.profile,
            project_path=installation.project_path,
            modules_enabled=list(installation.modules_enabled),
            files=list(installation.files),
            # Runtime/package grouping is not provable from arbitrary legacy
            # paths. The first successful installer mutation may derive Claude
            # ownership from its reviewed target boundary.
            skill_packages=[],
            settings_entries=list(installation.settings_entries),
            settings_backup_path=installation.settings_backup_path,
            codex_config_path=installation.codex_config_path,
            codex_commands=list(installation.codex_commands),
            installed_at=installation.installed_at,
            updated_at=installation.updated_at,
        )
        for key, installation in legacy.installations.items()
    }
    return InstalledManifest(version=TRACKING_VERSION, installations=installations)


class TrackingStore:
    """Manage the tracking manifest at ~/.forge/installed.json.

    The tracking manifest records what Forge has installed so that:
    - `forge extension sync` updates only tracked items
    - `forge extension disable` removes only tracked files and settings entries

    Error handling:
    - Missing file: Return empty manifest (not an error)
    - Corrupted JSON: Raise TrackingCorruptedError (fail loudly to preserve safety)
    """

    def __init__(self, tracking_path: Path | None = None) -> None:
        """Initialize store.

        Args:
            tracking_path: Override path to tracking file (for testing).
        """
        self._path = tracking_path or get_tracking_path()

    @property
    def path(self) -> Path:
        """Return the full path to the tracking file."""
        return self._path

    def exists(self) -> bool:
        """Check if tracking file exists."""
        return self._path.is_file()

    def read(self) -> InstalledManifest:
        """Read tracking manifest.

        Returns empty manifest if file doesn't exist.
        Raises TrackingCorruptedError if file exists but is invalid.

        Returns:
            The tracking manifest.

        Raises:
            TrackingCorruptedError: If file is corrupted or has invalid schema.
        """
        if not self.exists():
            return InstalledManifest()

        version, data = _read_tracking_object(self._path)
        if version == LEGACY_TRACKING_VERSION:
            legacy = _deserialize_manifest(self._path, _LegacyInstalledManifest, data)
            return _upgrade_legacy_manifest(legacy)
        manifest = _deserialize_manifest(self._path, InstalledManifest, data)
        _validate_current_manifest(self._path, manifest)
        return manifest

    def write(self, manifest: InstalledManifest) -> None:
        """Write tracking manifest atomically.

        Uses core.state.atomic_write_json for atomic writes.
        Creates parent directory if needed.

        Args:
            manifest: The manifest to write.
        """
        _validate_current_manifest(self._path, manifest)
        data = asdict(manifest)
        # Writes are always current even when the caller is persisting an
        # in-memory normalization of a legacy manifest after a successful
        # mutation. Read-only previews never call this method.
        data["version"] = TRACKING_VERSION
        atomic_write_json(self._path, data)

    def get_installation(self, scope: str, project_path: str | None = None) -> Installation | None:
        """Get installation for a specific scope and project.

        Args:
            scope: The scope to look up ("user", "project", "local").
            project_path: Project path (required for project/local scope).

        Returns:
            The Installation record, or None if not installed.
        """
        key = make_installation_key(scope, project_path)
        manifest = self.read()
        return manifest.installations.get(key)

    def set_installation(self, scope: str, installation: Installation, project_path: str | None = None) -> None:
        """Set installation for a scope and project.

        Args:
            scope: The scope to set.
            installation: The installation record.
            project_path: Project path (required for project/local scope).
        """
        key = make_installation_key(scope, project_path)
        installation.project_path = project_path
        with file_lock_for_target(target_path=self._path, timeout_s=5.0):
            manifest = self.read()
            manifest.installations[key] = installation
            self.write(manifest)

    def remove_installation(self, scope: str, project_path: str | None = None) -> bool:
        """Remove installation for a scope and project.

        Args:
            scope: The scope to remove.
            project_path: Project path (required for project/local scope).

        Returns:
            True if removed, False if didn't exist.
        """
        key = make_installation_key(scope, project_path)
        with file_lock_for_target(target_path=self._path, timeout_s=5.0):
            manifest = self.read()
            if key not in manifest.installations:
                return False
            del manifest.installations[key]
            self.write(manifest)
            return True

    def list_installations(self) -> list[tuple[str, str | None, Installation]]:
        """List all tracked installations.

        Returns:
            List of (scope, project_path, installation) tuples.
        """
        manifest = self.read()
        result = []
        for key, installation in manifest.installations.items():
            scope, project_path = parse_installation_key(key)
            result.append((scope, project_path, installation))
        return result

    def has_installation(self, scope: str, project_path: str | None = None) -> bool:
        """Check if an installation exists for the given scope and project.

        Args:
            scope: The scope to check.
            project_path: Project path (required for project/local scope).

        Returns:
            True if installation exists.
        """
        return self.get_installation(scope, project_path) is not None

    def is_forge_managed(self, path: str, scope: str, project_path: str | None = None) -> bool:
        """Check if a path is managed by Forge in the given scope.

        Args:
            path: Absolute path to check.
            scope: Scope to check within.
            project_path: Project path (required for project/local scope).

        Returns:
            True if the path is a Forge-managed file.
        """
        installation = self.get_installation(scope, project_path)
        if installation is None:
            return False

        normalized = str(Path(path).resolve())
        return any(str(Path(f.target_path).resolve()) == normalized for f in installation.files)
