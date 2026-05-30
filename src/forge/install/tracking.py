"""Tracking store for ~/.forge/installed.json.

Manages the persistent record of what Forge has installed, enabling
reversible update and uninstall operations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import dacite

from forge.core.paths import get_forge_home
from forge.core.state import atomic_write_json, file_lock_for_target

from .exceptions import TrackingCorruptedError
from .models import (
    TRACKING_VERSION,
    Installation,
    InstalledManifest,
    make_installation_key,
    parse_installation_key,
)

# Constants
TRACKING_FILENAME = "installed.json"


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

        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise TrackingCorruptedError(str(self._path), f"invalid JSON: {e}")
        except OSError as e:
            raise TrackingCorruptedError(str(self._path), f"read error: {e}")

        # Version check (no migration support)
        version = data.get("version", 1)
        if version != TRACKING_VERSION:
            raise TrackingCorruptedError(
                str(self._path),
                f"incompatible version {version} (this Forge expects {TRACKING_VERSION}). "
                f"Delete this file and run 'forge extension enable' again.",
            )

        # Guard: reject manifests from pre-OSS patching builds.
        # patched_files was removed from the Installation dataclass; dacite
        # strict=True rejects even "patched_files": []. Check raw JSON before
        # deserialization so the error message is actionable.
        installations = data.get("installations", {})
        for inst in installations.values():
            if isinstance(inst, dict) and "patched_files" in inst:
                raise TrackingCorruptedError(
                    str(self._path),
                    "This Forge install manifest was created by a pre-OSS patching build. "
                    f"Remove {self._path} and run `forge extension enable` again. "
                    "If Claude Code was patched, run `claude update` or reinstall Claude Code.",
                )

        try:
            return dacite.from_dict(
                data_class=InstalledManifest,
                data=data,
                config=dacite.Config(strict=True),
            )
        except (dacite.DaciteError, TypeError, KeyError) as e:
            raise TrackingCorruptedError(str(self._path), f"deserialization error: {e}")

    def write(self, manifest: InstalledManifest) -> None:
        """Write tracking manifest atomically.

        Uses core.state.atomic_write_json for atomic writes.
        Creates parent directory if needed.

        Args:
            manifest: The manifest to write.
        """
        data = asdict(manifest)
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
