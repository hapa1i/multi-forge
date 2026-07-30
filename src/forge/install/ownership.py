"""Runtime ownership helpers shared by tracking and installer planning.

This module deliberately has no dependency on the installer or tracking store.
It is the neutral boundary for durable ownership queries and closed legacy
path/key classification.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from forge.session.claude.paths import get_claude_home

from .models import (
    Installation,
    InstallModule,
    InstallScope,
    ModuleOwner,
    SurfaceAttribution,
    UnattributedSurface,
)

CLAUDE_CODE_RUNTIME = "claude_code"
CODEX_RUNTIME = "codex"

LEGACY_UNATTRIBUTED_REASONS = frozenset(
    {
        "legacy_path_unmapped",
        "legacy_key_unmapped",
        "legacy_v1_unprovable",
    }
)


def attributed(module: InstallModule | str, runtime: str) -> ModuleOwner:
    """Build the attributed tagged form used by ledger rows."""

    module_value = module.value if isinstance(module, InstallModule) else module
    return ModuleOwner(module=module_value, runtime=runtime)


def unattributed(reason: str) -> UnattributedSurface:
    """Build the legacy-only unattributed tagged form."""

    if reason not in LEGACY_UNATTRIBUTED_REASONS:
        raise ValueError(f"unknown legacy unattributed reason: {reason}")
    return UnattributedSurface(unattributed_reason=reason)


def module_owner_set(installation: Installation) -> set[tuple[str, str]]:
    """Return the durable ownership relation as lookup tuples."""

    return {(owner.module, owner.runtime) for owner in installation.module_owners}


def module_values(installation: Installation) -> set[str]:
    """Return the unique module values represented by durable ownership."""

    return {owner.module for owner in installation.module_owners}


def managed_runtime_ids(installation: Installation) -> tuple[str, ...]:
    """Return sorted runtime ids represented by durable ownership."""

    return tuple(sorted({owner.runtime for owner in installation.module_owners}))


def has_module_owner(
    installation: Installation,
    module: InstallModule | str,
    runtime: str | None = None,
) -> bool:
    """Return whether an installation has a matching ownership pair."""

    module_value = module.value if isinstance(module, InstallModule) else module
    return any(
        owner.module == module_value and (runtime is None or owner.runtime == runtime)
        for owner in installation.module_owners
    )


def attribution_pair(attribution: SurfaceAttribution) -> tuple[str, str] | None:
    """Return the attributed pair, or ``None`` for a legacy-unattributed row."""

    if isinstance(attribution, ModuleOwner):
        return (attribution.module, attribution.runtime)
    return None


def legacy_claude_target_root(scope: InstallScope, project_root: Path | None) -> Path | None:
    """Return the historical Claude extension root when it is provable."""

    if scope == InstallScope.USER:
        return get_claude_home()
    if project_root is None:
        return None
    return project_root / ".claude"


def legacy_claude_skill_claims(
    target_paths: Iterable[str],
    scope: InstallScope,
    project_root: Path | None,
) -> dict[str, str]:
    """Map path-provable v1 Claude skill files to their neutral skill name."""

    target_root = legacy_claude_target_root(scope, project_root)
    if target_root is None:
        return {}
    skills_root = target_root / "skills"
    claims: dict[str, str] = {}
    for raw_path in target_paths:
        target = Path(raw_path)
        try:
            relative = target.relative_to(skills_root)
        except ValueError:
            continue
        if len(relative.parts) >= 2:
            claims[raw_path] = relative.parts[0]
    return claims


def legacy_claude_skill_packages(
    installation: Installation | None,
    scope: InstallScope,
    project_root: Path | None,
) -> set[tuple[str, str]]:
    """Derive only path-provable legacy Claude package identities."""

    if installation is None:
        return set()
    claims = legacy_claude_skill_claims(
        (tracked_file.target_path for tracked_file in installation.files),
        scope,
        project_root,
    )
    return {(CLAUDE_CODE_RUNTIME, skill) for skill in claims.values()}


def legacy_file_module(
    target_path: str,
    scope: InstallScope,
    project_root: Path | None,
) -> InstallModule | None:
    """Classify only the closed legacy Claude command/agent target roots."""

    target_root = legacy_claude_target_root(scope, project_root)
    if target_root is None:
        return None
    target = Path(target_path)
    for module in (InstallModule.COMMANDS, InstallModule.AGENTS):
        try:
            relative = target.relative_to(target_root / module.value)
        except ValueError:
            continue
        if relative.parts:
            return module
    return None


def legacy_settings_module(key_path: str) -> InstallModule | None:
    """Classify only the closed legacy Claude settings-key mapping."""

    if key_path.startswith("hooks."):
        return InstallModule.HOOKS
    if key_path == "statusLine":
        return InstallModule.STATUSLINE
    if key_path in {"permissions.allow", "permissions.deny"} or key_path.startswith("env."):
        return InstallModule.PERMISSIONS
    return None
