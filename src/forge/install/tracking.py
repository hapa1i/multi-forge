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
    MODULE_RUNTIME_OWNERS,
    TRACKING_VERSION,
    Installation,
    InstalledFile,
    InstalledManifest,
    InstalledSettingsEntry,
    InstalledSkillPackage,
    InstallModule,
    InstallScope,
    ModuleOwner,
    SurfaceAttribution,
    UnattributedSurface,
    make_installation_key,
    parse_installation_key,
)
from .ownership import (
    CLAUDE_CODE_RUNTIME,
    CODEX_RUNTIME,
    LEGACY_UNATTRIBUTED_REASONS,
    attributed,
    legacy_claude_skill_claims,
    legacy_file_module,
    legacy_settings_module,
    unattributed,
)

# Constants
TRACKING_FILENAME = "installed.json"
LEGACY_TRACKING_VERSION = 1
V2_TRACKING_VERSION = 2
_LEGACY_MODULE_VALUES = frozenset(
    {
        "commands",
        "agents",
        "skills",
        "hooks",
        "status-line",
        "permissions",
        "codex-hooks",
    }
)


@dataclass
class _V1InstalledFile:
    """Frozen released-v1 file row."""

    target_path: str
    source_path: str
    checksum: str
    mode: str
    installed_at: str


@dataclass
class _V1InstalledSettingsEntry:
    """Frozen released-v1 settings row."""

    key_path: str
    value: Any
    merge_type: str
    stable_id: str


@dataclass
class _V1Installation:
    """Frozen released-v1 installation shape."""

    scope: str
    mode: str
    profile: str
    project_path: str | None = None
    modules_enabled: list[str] = field(default_factory=list)
    files: list[_V1InstalledFile] = field(default_factory=list)
    settings_entries: list[_V1InstalledSettingsEntry] = field(default_factory=list)
    settings_backup_path: str | None = None
    codex_config_path: str | None = None
    codex_commands: list[str] = field(default_factory=list)
    installed_at: str = ""
    updated_at: str = ""


@dataclass
class _V1InstalledManifest:
    """Frozen released-v1 root shape; unknown fields remain hard errors."""

    version: int = LEGACY_TRACKING_VERSION
    installations: dict[str, _V1Installation] = field(default_factory=dict)


@dataclass
class _V2InstalledFile:
    """Frozen released-v2 file row."""

    target_path: str
    source_path: str
    checksum: str
    mode: str
    installed_at: str


@dataclass
class _V2InstalledSettingsEntry:
    """Frozen released-v2 settings row."""

    key_path: str
    value: Any
    merge_type: str
    stable_id: str


@dataclass
class _V2InstalledSkillPackage:
    """Frozen released-v2 runtime skill package row."""

    runtime: str
    skill: str
    target_dir: str
    file_paths: list[str] = field(default_factory=list)


@dataclass
class _V2Installation:
    """Frozen released-v2 installation shape."""

    scope: str
    mode: str
    profile: str
    project_path: str | None = None
    modules_enabled: list[str] = field(default_factory=list)
    files: list[_V2InstalledFile] = field(default_factory=list)
    skill_packages: list[_V2InstalledSkillPackage] = field(default_factory=list)
    settings_entries: list[_V2InstalledSettingsEntry] = field(default_factory=list)
    settings_backup_path: str | None = None
    codex_config_path: str | None = None
    codex_commands: list[str] = field(default_factory=list)
    installed_at: str = ""
    updated_at: str = ""


@dataclass
class _V2InstalledManifest:
    """Frozen released-v2 root shape; unknown fields remain hard errors."""

    version: int = V2_TRACKING_VERSION
    installations: dict[str, _V2Installation] = field(default_factory=dict)


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
    if isinstance(version, int) and not isinstance(version, bool) and version > TRACKING_VERSION:
        detail = (
            f"incompatible version {version}; this file was written by newer Forge. "
            "Upgrade Forge before changing extension state."
        )
    else:
        detail = (
            f"incompatible version {version} (this Forge expects {TRACKING_VERSION}). "
            "Delete this file and run 'forge extension enable' again."
        )
    raise TrackingCorruptedError(
        str(path),
        detail,
    )


def _read_tracking_object(path: Path) -> tuple[int, dict[str, Any]]:
    """Read the JSON object and accept released v1/v2 or current v3.

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
    if version not in {LEGACY_TRACKING_VERSION, V2_TRACKING_VERSION, TRACKING_VERSION}:
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
        label = f"installation {installation_key!r}"
        if installation.module_owners != sorted(set(installation.module_owners)):
            raise TrackingCorruptedError(
                str(path),
                f"ownership invariant error: {label} module_owners must be unique and sorted",
            )

        owner_pairs: set[tuple[str, str]] = set()
        for owner in installation.module_owners:
            try:
                module = InstallModule(owner.module)
            except ValueError as e:
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {label} contains unknown module value {owner.module!r}",
                ) from e
            if owner.runtime not in MODULE_RUNTIME_OWNERS[module]:
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {label} module {owner.module!r} cannot be owned by "
                    f"runtime {owner.runtime!r}",
                )
            owner_pairs.add((owner.module, owner.runtime))

        file_identities: set[str] = set()
        for file_record in installation.files:
            if file_record.target_path in file_identities:
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {label} duplicates file row identity {file_record.target_path!r}",
                )
            file_identities.add(file_record.target_path)
            _validate_attribution(
                path,
                label,
                file_record.attribution,
                owner_pairs,
                f"file {file_record.target_path!r}",
            )

        settings_identities: set[tuple[str, str]] = set()
        for settings_record in installation.settings_entries:
            identity = (settings_record.key_path, settings_record.stable_id)
            if identity in settings_identities:
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {label} duplicates settings row identity {identity!r}",
                )
            settings_identities.add(identity)
            _validate_attribution(path, label, settings_record.attribution, owner_pairs, f"settings row {identity!r}")

        tracked_file_paths = {record.target_path for record in installation.files}
        claimed_package_paths: set[str] = set()
        package_keys: set[tuple[str, str]] = set()

        for package in installation.skill_packages:
            package_label = f"{label} package {package.runtime}/{package.skill}"
            package_key = (package.runtime, package.skill)
            if package_key in package_keys:
                raise TrackingCorruptedError(str(path), f"ownership invariant error: {package_label} is duplicated")
            package_keys.add(package_key)
            if (InstallModule.SKILLS.value, package.runtime) not in owner_pairs:
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {package_label} has no matching skills owner pair",
                )

            package_dir = Path(package.target_dir)
            if not package_dir.is_absolute():
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {package_label} target_dir must be absolute",
                )
            if not package.file_paths:
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {package_label} file_paths must not be empty",
                )
            if package.file_paths != sorted(set(package.file_paths)):
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {package_label} file_paths must be unique and sorted",
                )

            package_paths = set(package.file_paths)
            skill_document = str(package_dir / "SKILL.md")
            if skill_document not in package_paths:
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {package_label} must track {skill_document}",
                )

            for raw_file_path in package.file_paths:
                file_path = Path(raw_file_path)
                if not file_path.is_absolute():
                    raise TrackingCorruptedError(
                        str(path),
                        f"ownership invariant error: {package_label} contains non-absolute file path {raw_file_path!r}",
                    )
                try:
                    relative_path = file_path.relative_to(package_dir)
                except ValueError as e:
                    raise TrackingCorruptedError(
                        str(path),
                        f"ownership invariant error: {package_label} contains file outside target_dir: {raw_file_path}",
                    ) from e
                if not relative_path.parts or ".." in relative_path.parts:
                    raise TrackingCorruptedError(
                        str(path),
                        f"ownership invariant error: {package_label} contains invalid package file path {raw_file_path}",
                    )

            missing_ledger_paths = package_paths - tracked_file_paths
            if missing_ledger_paths:
                missing = ", ".join(sorted(missing_ledger_paths))
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {package_label} is not backed by files ledger: {missing}",
                )
            duplicate_claims = package_paths & claimed_package_paths
            if duplicate_claims:
                duplicate = ", ".join(sorted(duplicate_claims))
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: {package_label} reuses package file paths: {duplicate}",
                )
            claimed_package_paths.update(package_paths)

        has_codex_hook_owner = (InstallModule.HOOKS.value, CODEX_RUNTIME) in owner_pairs
        if has_codex_hook_owner != (installation.codex_config_path is not None):
            raise TrackingCorruptedError(
                str(path),
                f"ownership invariant error: {label} must own hooks/codex iff codex_config_path is set",
            )


def _validate_attribution(
    path: Path,
    installation_label: str,
    attribution_value: ModuleOwner | UnattributedSurface,
    owner_pairs: set[tuple[str, str]],
    row_label: str,
) -> None:
    """Validate one exact tagged attribution form."""

    if isinstance(attribution_value, ModuleOwner):
        pair = (attribution_value.module, attribution_value.runtime)
        if pair not in owner_pairs:
            raise TrackingCorruptedError(
                str(path),
                f"ownership invariant error: {installation_label} {row_label} attribution {pair!r} "
                "has no matching owner pair",
            )
        return
    if isinstance(attribution_value, UnattributedSurface):
        if attribution_value.unattributed_reason not in LEGACY_UNATTRIBUTED_REASONS:
            raise TrackingCorruptedError(
                str(path),
                f"ownership invariant error: {installation_label} {row_label} has unknown unattributed reason "
                f"{attribution_value.unattributed_reason!r}",
            )
        return
    raise TrackingCorruptedError(
        str(path),
        f"ownership invariant error: {installation_label} {row_label} has invalid attribution form",
    )


def _legacy_scope_and_root(
    installation_key: str,
    scope_value: str,
    project_path: str | None,
) -> tuple[InstallScope | None, Path | None]:
    """Resolve only path context provable from a legacy installation."""

    key_scope, key_project_path = parse_installation_key(installation_key)
    if key_scope != scope_value:
        return None, None
    try:
        scope = InstallScope(scope_value)
    except ValueError:
        return None, None
    raw_project_path = project_path or key_project_path
    if scope == InstallScope.USER:
        return scope, None
    if raw_project_path is None:
        return scope, None
    candidate = Path(raw_project_path)
    return scope, candidate if candidate.is_absolute() else None


def _validate_legacy_modules(path: Path, installation_key: str, modules: list[str]) -> None:
    unknown_modules = sorted(set(modules) - _LEGACY_MODULE_VALUES)
    if unknown_modules:
        names = ", ".join(repr(name) for name in unknown_modules)
        raise TrackingCorruptedError(
            str(path),
            f"ownership invariant error: installation {installation_key!r} contains unknown module value(s): {names}",
        )


def _upgrade_installation(
    path: Path,
    installation_key: str,
    installation: _V1Installation | _V2Installation,
    *,
    version: int,
) -> Installation:
    """Derive one legacy installation into the strict v3 ownership model."""

    _validate_legacy_modules(path, installation_key, installation.modules_enabled)
    scope, project_root = _legacy_scope_and_root(
        installation_key,
        installation.scope,
        installation.project_path,
    )

    owners: set[ModuleOwner] = set()
    for raw_module in installation.modules_enabled:
        if raw_module in {
            InstallModule.COMMANDS.value,
            InstallModule.AGENTS.value,
            InstallModule.HOOKS.value,
            InstallModule.STATUSLINE.value,
            InstallModule.PERMISSIONS.value,
        }:
            owners.add(attributed(raw_module, CLAUDE_CODE_RUNTIME))

    raw_packages = installation.skill_packages if isinstance(installation, _V2Installation) else []
    skill_path_claims: dict[str, str] = {}
    for package in raw_packages:
        for file_path in package.file_paths:
            prior_runtime = skill_path_claims.setdefault(file_path, package.runtime)
            if prior_runtime != package.runtime:
                raise TrackingCorruptedError(
                    str(path),
                    f"ownership invariant error: installation {installation_key!r} legacy skill path "
                    f"{file_path!r} is claimed by multiple runtimes",
                )
        owners.add(attributed(InstallModule.SKILLS, package.runtime))

    v1_skill_claims: dict[str, str] = {}
    if version == LEGACY_TRACKING_VERSION and scope is not None:
        v1_skill_claims = legacy_claude_skill_claims(
            (file_record.target_path for file_record in installation.files),
            scope,
            project_root,
        )
        if v1_skill_claims:
            owners.add(attributed(InstallModule.SKILLS, CLAUDE_CODE_RUNTIME))

    files: list[InstalledFile] = []
    for file_record in installation.files:
        row_attribution: SurfaceAttribution
        if file_record.target_path in skill_path_claims:
            row_attribution = attributed(InstallModule.SKILLS, skill_path_claims[file_record.target_path])
        elif file_record.target_path in v1_skill_claims:
            row_attribution = attributed(InstallModule.SKILLS, CLAUDE_CODE_RUNTIME)
        else:
            legacy_module = (
                legacy_file_module(file_record.target_path, scope, project_root) if scope is not None else None
            )
            row_attribution = (
                attributed(legacy_module, CLAUDE_CODE_RUNTIME)
                if legacy_module is not None
                else unattributed("legacy_path_unmapped")
            )
        if isinstance(row_attribution, ModuleOwner):
            owners.add(row_attribution)
        files.append(
            InstalledFile(
                target_path=file_record.target_path,
                source_path=file_record.source_path,
                checksum=file_record.checksum,
                mode=file_record.mode,
                installed_at=file_record.installed_at,
                attribution=row_attribution,
            )
        )

    settings_entries: list[InstalledSettingsEntry] = []
    for settings_record in installation.settings_entries:
        legacy_module = legacy_settings_module(settings_record.key_path)
        settings_attribution: SurfaceAttribution = (
            attributed(legacy_module, CLAUDE_CODE_RUNTIME)
            if legacy_module is not None
            else unattributed("legacy_key_unmapped")
        )
        if isinstance(settings_attribution, ModuleOwner):
            owners.add(settings_attribution)
        settings_entries.append(
            InstalledSettingsEntry(
                key_path=settings_record.key_path,
                value=settings_record.value,
                merge_type=settings_record.merge_type,
                stable_id=settings_record.stable_id,
                attribution=settings_attribution,
            )
        )

    if installation.codex_config_path is not None:
        owners.add(attributed(InstallModule.HOOKS, CODEX_RUNTIME))

    skill_packages = [
        InstalledSkillPackage(
            runtime=package.runtime,
            skill=package.skill,
            target_dir=package.target_dir,
            file_paths=list(package.file_paths),
        )
        for package in raw_packages
    ]
    if version == LEGACY_TRACKING_VERSION and scope is not None:
        files_by_skill: dict[str, list[str]] = {}
        for file_path, skill in v1_skill_claims.items():
            files_by_skill.setdefault(skill, []).append(file_path)
        for skill, file_paths in sorted(files_by_skill.items()):
            skill_document = next((file_path for file_path in file_paths if Path(file_path).name == "SKILL.md"), None)
            if skill_document is None:
                continue
            skill_packages.append(
                InstalledSkillPackage(
                    runtime=CLAUDE_CODE_RUNTIME,
                    skill=skill,
                    target_dir=str(Path(skill_document).parent),
                    file_paths=sorted(set(file_paths)),
                )
            )

    return Installation(
        scope=installation.scope,
        mode=installation.mode,
        profile=installation.profile,
        project_path=installation.project_path,
        module_owners=sorted(owners),
        files=files,
        skill_packages=skill_packages,
        settings_entries=settings_entries,
        settings_backup_path=installation.settings_backup_path,
        codex_config_path=installation.codex_config_path,
        codex_commands=list(installation.codex_commands),
        installed_at=installation.installed_at,
        updated_at=installation.updated_at,
    )


def _upgrade_v1_manifest(path: Path, legacy: _V1InstalledManifest) -> InstalledManifest:
    """Normalize frozen v1 state to v3 without rewriting on read."""

    return InstalledManifest(
        version=TRACKING_VERSION,
        installations={
            key: _upgrade_installation(path, key, installation, version=LEGACY_TRACKING_VERSION)
            for key, installation in legacy.installations.items()
        },
    )


def _upgrade_v2_manifest(path: Path, legacy: _V2InstalledManifest) -> InstalledManifest:
    """Normalize frozen v2 state to v3 without rewriting on read."""

    return InstalledManifest(
        version=TRACKING_VERSION,
        installations={
            key: _upgrade_installation(path, key, installation, version=V2_TRACKING_VERSION)
            for key, installation in legacy.installations.items()
        },
    )


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
            legacy_v1 = _deserialize_manifest(self._path, _V1InstalledManifest, data)
            manifest = _upgrade_v1_manifest(self._path, legacy_v1)
        elif version == V2_TRACKING_VERSION:
            legacy_v2 = _deserialize_manifest(self._path, _V2InstalledManifest, data)
            manifest = _upgrade_v2_manifest(self._path, legacy_v2)
        else:
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
