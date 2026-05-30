"""Forge installer for Claude Code extensions.

Provides `forge extension enable` / `forge extension sync` /
`forge extension disable` / `forge extension status` commands to manage
installation of commands, agents, hooks, skills, and settings.
"""

from __future__ import annotations

from .exceptions import (
    ConflictError,
    FileConflictError,
    ForgeInstallError,
    NotInstalledError,
    SettingsConflictError,
    SourceNotFoundError,
    TrackingCorruptedError,
)
from .models import (
    FilePlan,
    Installation,
    InstalledFile,
    InstalledManifest,
    InstalledSettingsEntry,
    InstallMode,
    InstallModule,
    InstallPlan,
    InstallProfile,
    InstallScope,
    SettingsPlan,
)

__all__ = [
    # Enums
    "InstallScope",
    "InstallMode",
    "InstallProfile",
    "InstallModule",
    # Tracking dataclasses
    "InstalledFile",
    "InstalledSettingsEntry",
    "Installation",
    "InstalledManifest",
    # Plan dataclasses
    "FilePlan",
    "SettingsPlan",
    "InstallPlan",
    # Exceptions
    "ForgeInstallError",
    "ConflictError",
    "FileConflictError",
    "SettingsConflictError",
    "TrackingCorruptedError",
    "NotInstalledError",
    "SourceNotFoundError",
]
