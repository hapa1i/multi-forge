"""Data models for Forge Installer.

Defines enums for installation options and dataclasses for tracking
what Forge has installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# --- Enums ---


class InstallScope(str, Enum):
    """Installation scope (mirrors Claude Code's scope model).

    - USER: ~/.claude/... + ~/.claude/settings.json (default)
    - PROJECT: .claude/... + .claude/settings.json (checked in)
    - LOCAL: .claude/... + .claude/settings.local.json (personal per-project)
    """

    USER = "user"
    PROJECT = "project"
    LOCAL = "local"


class InstallMode(str, Enum):
    """Installation mode.

    - COPY: Copy files to target (stable install)
    - SYMLINK: Symlink files to source (development mode)
    """

    COPY = "copy"
    SYMLINK = "symlink"


class InstallProfile(str, Enum):
    """Predefined installation profiles.

    - MINIMAL: commands only
    - STANDARD: commands, agents, hooks, permissions (default)
    - FULL: all modules including status-line
    """

    MINIMAL = "minimal"
    STANDARD = "standard"
    FULL = "full"


class InstallModule(str, Enum):
    """Installable module types."""

    COMMANDS = "commands"
    AGENTS = "agents"
    SKILLS = "skills"
    HOOKS = "hooks"
    STATUSLINE = "status-line"
    PERMISSIONS = "permissions"
    CODEX_HOOKS = "codex-hooks"


# Profile -> modules mapping
PROFILE_MODULES: dict[InstallProfile, set[InstallModule]] = {
    InstallProfile.MINIMAL: {InstallModule.COMMANDS},
    InstallProfile.STANDARD: {
        InstallModule.COMMANDS,
        InstallModule.AGENTS,
        InstallModule.SKILLS,
        InstallModule.HOOKS,
        InstallModule.PERMISSIONS,
        InstallModule.STATUSLINE,
        InstallModule.CODEX_HOOKS,
    },
    InstallProfile.FULL: set(InstallModule),
}

# Profile ordering (for minimum-profile comparisons in skill filtering)
PROFILE_RANK: dict[InstallProfile, int] = {
    InstallProfile.MINIMAL: 0,
    InstallProfile.STANDARD: 1,
    InstallProfile.FULL: 2,
}

# Skills requiring a minimum install profile. Unlisted skills install with
# any profile that includes the SKILLS module.
SKILL_PROFILE_REQUIREMENTS: dict[str, InstallProfile] = {
    "qa": InstallProfile.FULL,
}


def get_gated_skills(profile: InstallProfile) -> list[tuple[str, InstallProfile]]:
    """Return skills excluded by the given profile, with their required profile.

    Only returns skills that need a higher profile than the one provided.
    """
    return sorted(
        (name, req) for name, req in SKILL_PROFILE_REQUIREMENTS.items() if PROFILE_RANK[profile] < PROFILE_RANK[req]
    )


# Module dependencies (installing X requires also installing Y's settings)
MODULE_DEPENDENCIES: dict[InstallModule, set[InstallModule]] = {}

# Modules that are file-based (vs settings-only)
FILE_MODULES: set[InstallModule] = {
    InstallModule.COMMANDS,
    InstallModule.AGENTS,
    InstallModule.SKILLS,
}

# Modules that are settings-only (no files to install)
# HOOKS: All hooks are dispatcher commands (`forge-hook X`) - no files to copy
# STATUSLINE: Now `forge status-line` command - no scripts to copy
# CODEX_HOOKS: managed block in Codex config.toml - no files to copy
SETTINGS_ONLY_MODULES: set[InstallModule] = {
    InstallModule.PERMISSIONS,
    InstallModule.HOOKS,
    InstallModule.STATUSLINE,
    InstallModule.CODEX_HOOKS,
}


# --- Tracking dataclasses ---


@dataclass
class InstalledFile:
    """A file installed by Forge.

    Attributes:
        target_path: Absolute path where the file was installed.
        source_path: Absolute path to the source file in forge repo.
        checksum: SHA256 hash of source content (used to detect source changes).
                  For copy mode: compare to target checksum to detect if update needed.
                  For symlink mode: verify symlink points to expected source.
        mode: "copy" or "symlink".
        installed_at: ISO8601 timestamp when file was installed.
    """

    target_path: str
    source_path: str
    checksum: str
    mode: str
    installed_at: str


@dataclass
class InstalledSettingsEntry:
    """A settings entry added by Forge.

    Attributes:
        key_path: Dot-notation path (e.g., "hooks.PreToolUse").
        value: The added value (for reference/display).
        merge_type: "append", "union", or "scalar".
        stable_id: Stable identifier for value-based unmerge:
                   - For hooks: command path string
                   - For permissions: the entry value itself
                   - For scalars: the key_path
    """

    key_path: str
    value: Any
    merge_type: str
    stable_id: str


@dataclass
class InstalledSkillPackage:
    """One runtime-specific skill package managed by Forge.

    ``Installation.files`` remains the canonical checksum and removal ledger.
    This record supplies the runtime/package grouping that cannot be recovered
    safely from arbitrary target paths after a runtime target changes.

    Attributes:
        runtime: Runtime registry id (for example, ``claude_code`` or ``codex``).
        skill: Neutral Forge skill name before runtime-specific name transforms.
        target_dir: Absolute installed package directory.
        file_paths: Stable, sorted absolute target paths belonging to the package.
    """

    runtime: str
    skill: str
    target_dir: str
    file_paths: list[str] = field(default_factory=list)


@dataclass
class Installation:
    """Installation record for a single scope.

    Attributes:
        scope: InstallScope value ("user", "project", "local").
        project_path: Absolute path to project root (None for user scope).
                     Used to track multiple local/project installations.
        mode: InstallMode value ("copy", "symlink").
        profile: InstallProfile value ("minimal", "standard", "full").
        modules_enabled: List of InstallModule values that were enabled.
        files: List of InstalledFile records.
        skill_packages: Runtime/package ownership records. InstalledFile remains
                        canonical for checksums and removal.
        settings_entries: List of InstalledSettingsEntry records.
        settings_backup_path: Path to settings backup file (if created).
        codex_config_path: Codex config.toml carrying the Forge-managed hook
                          block (None when codex-hooks was skipped/unmanaged).
        codex_commands: Forge hook commands registered in that block.
        installed_at: ISO8601 timestamp when first installed.
        updated_at: ISO8601 timestamp when last updated.
    """

    scope: str
    mode: str
    profile: str
    project_path: str | None = None
    modules_enabled: list[str] = field(default_factory=list)
    files: list[InstalledFile] = field(default_factory=list)
    skill_packages: list[InstalledSkillPackage] = field(default_factory=list)
    settings_entries: list[InstalledSettingsEntry] = field(default_factory=list)
    settings_backup_path: str | None = None
    codex_config_path: str | None = None
    codex_commands: list[str] = field(default_factory=list)
    installed_at: str = ""
    updated_at: str = ""


def make_installation_key(scope: str, project_path: str | None = None) -> str:
    """Create a unique key for an installation.

    Args:
        scope: The installation scope ("user", "project", "local").
        project_path: Absolute path to project root (required for project/local).

    Returns:
        Unique key: "user" for user scope, "{scope}:{path}" for project/local.

    Raises:
        ValueError: If project_path missing for project/local scope.
    """
    if scope == InstallScope.USER.value:
        return "user"
    if not project_path:
        raise ValueError(f"project_path required for {scope} scope")
    return f"{scope}:{project_path}"


def parse_installation_key(key: str) -> tuple[str, str | None]:
    """Parse an installation key back to scope and project_path.

    Args:
        key: Installation key from manifest.

    Returns:
        Tuple of (scope, project_path). project_path is None for user scope.
    """
    if key == "user":
        return (InstallScope.USER.value, None)
    if ":" in key:
        scope, path = key.split(":", 1)
        return (scope, path)
    # v1 format: bare scope name without path (e.g., "project", "local")
    return (key, None)


# Tracking manifest version
TRACKING_VERSION = 2


@dataclass
class InstalledManifest:
    """Root tracking manifest at ~/.forge/installed.json.

    Attributes:
        version: Schema version for the tracking manifest.
        installations: Dict mapping scope name to Installation record.
    """

    version: int = TRACKING_VERSION
    installations: dict[str, Installation] = field(default_factory=dict)


# --- Plan dataclasses (for --dry-run) ---


@dataclass
class FilePlan:
    """Plan for a single file operation.

    Attributes:
        action: "install", "update", "remove", or "skip".
        target_path: Where the file will be installed.
        effective_mode: Per-file copy or symlink behavior selected by planning.
        source_path: Where the file comes from (None for remove).
        reason: Explanation for skip/conflict actions.
    """

    action: str
    target_path: str
    effective_mode: InstallMode
    source_path: str | None = None
    reason: str | None = None


@dataclass
class SettingsPlan:
    """Plan for settings modifications.

    Attributes:
        action: "merge", "unmerge", or "conflict".
        key_path: Settings key being modified.
        value: Value to be set (for merge).
        current_value: Existing value (for conflict display).
        reason: Explanation for conflict.
    """

    action: str
    key_path: str
    value: Any = None
    current_value: Any = None
    reason: str | None = None


@dataclass
class CodexPlan:
    """Plan for the Codex hook registration (codex-hooks module).

    Codex registration is best-effort: an "unavailable" (no codex binary) or
    "conflict" outcome degrades to a visible skip and never sets
    InstallPlan.has_conflicts -- the Claude install must not fail because
    another tool's config could not be merged.

    Attributes:
        action: "install", "update", "skip", "conflict", or "unavailable".
        config_path: Target Codex config.toml (None when unavailable).
        reason: Explanation for skip/conflict/unavailable actions.
        commands: Hook commands the managed block registers.
    """

    action: str
    config_path: str | None = None
    reason: str | None = None
    commands: list[str] = field(default_factory=list)


@dataclass
class SkillPackagePlan:
    """Plan summary for one runtime-specific skill package."""

    runtime: str
    skill: str
    action: str
    target_dir: str | None = None
    cache_dir: str | None = None
    file_paths: list[str] = field(default_factory=list)
    reason: str | None = None
    duplicate_dirs: list[str] = field(default_factory=list)
    recovery: str | None = None


@dataclass(frozen=True)
class SkillPackageStatus:
    """Observed state for one tracked runtime-specific skill package."""

    runtime: str
    skill: str
    target_dir: str
    state: str
    target_present: bool
    file_paths: tuple[str, ...] = ()
    missing_file_paths: tuple[str, ...] = ()
    duplicate_dirs: tuple[str, ...] = ()
    recovery: str | None = None


@dataclass
class InstallPlan:
    """Complete installation plan.

    Attributes:
        scope: Target scope for installation.
        mode: Installation mode.
        profile: Installation profile.
        modules: List of modules being installed.
        files: List of file operations.
        settings: List of settings operations.
        skill_packages: Runtime-specific package planning outcomes.
        codex: Codex hook registration plan (None when module not selected).
        legacy_hook_cleanup_paths: User settings files whose legacy direct hooks
            were removed while executing this plan.
        has_conflicts: True if any conflicts were detected.
        conflicts: Human-readable conflict descriptions.
    """

    scope: str
    mode: str
    profile: str
    modules: list[str] = field(default_factory=list)
    files: list[FilePlan] = field(default_factory=list)
    settings: list[SettingsPlan] = field(default_factory=list)
    skill_packages: list[SkillPackagePlan] = field(default_factory=list)
    codex: CodexPlan | None = None
    legacy_hook_cleanup_paths: list[str] = field(default_factory=list)
    has_conflicts: bool = False
    conflicts: list[str] = field(default_factory=list)
    requires_claude_version: bool = False
