"""Forge extensions commands (extensions lifecycle).

Commands:
- forge extension enable  - Enable Forge extensions
- forge extension sync    - Sync existing extensions
- forge extension disable - Disable extensions
- forge extension status  - Show extensions status
- forge extension doctor  - Report install kind + PATH reachability
"""

from __future__ import annotations

import logging
import shlex
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from forge.cli.output import print_error, print_tip
from forge.core.paths import display_path, find_git_root
from forge.core.state.exceptions import StateCorruptedError, StateUnreadableError
from forge.install.exceptions import (
    ForgeInstallError,
    NoClaudeDirectoryError,
    NoForgeInstallationError,
    NotInstalledError,
    SettingsConflictError,
)
from forge.install.hook_migration import (
    HookMigrationError,
    ProjectHookMigrationPlan,
    apply_project_hook_migration,
    cleanup_user_legacy_hook_files,
    list_hook_migration_candidates,
    plan_project_hook_migration,
)
from forge.install.hooks import diagnose_forge_hook_runtime
from forge.install.installer import (
    Installer,
    find_claude_root,
    find_forge_installation,
    inspect_skill_package_status,
)
from forge.install.models import (
    FILE_MODULES,
    PROFILE_RANK,
    InstallMode,
    InstallModule,
    InstallPlan,
    InstallProfile,
    InstallScope,
    get_gated_skills,
)
from forge.install.project_compat import (
    ProjectCompatibilityError,
    enforce_project_compatibility,
    format_project_compatibility_recovery,
)
from forge.install.project_registry import EnrollmentSource, ProjectRegistryStore
from forge.install.tracking import TrackingStore

console = Console()
_log = logging.getLogger(__name__)
_INSTALL_SCOPE_HELP = "Installation scope: local (gitignored), project (committed), user (global)"
_SKILL_RUNTIME_IDS = {"claude": "claude_code", "codex": "codex"}
_NON_FORCEABLE_SKILL_CONFLICT_REASONS = {
    "duplicate_scan_chain",
    "forge_managed_scope_duplicate",
    "runtime_unavailable",
    "scope_unsupported",
}


def _detect_git_project_root(start: Path | None = None) -> Path | None:
    """Find the git root suitable for auto-creating ``.claude/`` (Rule 4).

    Returns the resolved git root, or None if not in a git repo or the
    git root is the user's home directory.  Pure detector -- no side effects.
    """
    cwd = (start or Path.cwd()).resolve()
    git_root = find_git_root(cwd)
    if git_root is None:
        return None

    home = Path.home().resolve()
    if git_root == home:
        return None

    return git_root.resolve()


def _create_claude_dir(root: Path) -> None:
    """Create ``.claude/`` at *root* and log the action."""
    claude_dir = root / ".claude"
    claude_dir.mkdir(exist_ok=True)
    _log.info("Created %s for Forge project", claude_dir)
    console.print(f"[dim]Created {display_path(claude_dir)}[/dim]")


def _parse_modules(modules_str: str | None) -> set[InstallModule] | None:
    """Parse comma-separated module names.

    Args:
        modules_str: Comma-separated module names.

    Returns:
        Set of InstallModule, or None if input is None/empty.
    """
    if not modules_str:
        return None
    return {InstallModule(m.strip()) for m in modules_str.split(",")}


def _parse_skill_runtimes(values: tuple[str, ...]) -> tuple[str, ...] | None:
    """Map repeatable CLI runtime names to stable runtime registry ids."""

    if not values:
        return None
    selected: set[str] = set()
    for value in values:
        if value == "all":
            selected.update(_SKILL_RUNTIME_IDS.values())
        else:
            selected.add(_SKILL_RUNTIME_IDS[value])
    return tuple(runtime for runtime in _SKILL_RUNTIME_IDS.values() if runtime in selected)


def _enforce_claude_version_if_required(plan: InstallPlan, project_root: Path | None = None) -> None:
    """Apply the Claude CLI gate only when the plan mutates Claude surfaces."""

    if not plan.requires_claude_version:
        return
    from forge.install.version import check_minimum_version

    version_check = check_minimum_version()
    if not version_check.ok:
        print_error(f"{version_check.reason}")
        codex_packages_selected = any(
            package.runtime == _SKILL_RUNTIME_IDS["codex"] and package.action in {"install", "update"}
            for package in plan.skill_packages
        )
        if version_check.version is None and codex_packages_selected:
            root_option = f" --root {shlex.quote(str(project_root))}" if project_root is not None else ""
            command = (
                f"forge extension enable --scope {plan.scope}{root_option} --profile minimal "
                "--with skills --without commands --runtime codex"
            )
            print_tip(
                f"Install Claude Code, or install only Codex skills with '{command}'.",
                console=console,
            )
        elif version_check.version is None:
            print_tip("Install Claude Code, then retry.", console=console)
        else:
            print_tip("Run 'claude update' to upgrade.", console=console)
        raise click.exceptions.Exit(1)


def _count_actions(plan: InstallPlan) -> tuple[int, int, int]:
    """Count non-skip actions in a plan.

    Returns:
        Tuple of (file_actions, settings_actions, codex_actions) that
        actually change something. A codex install/update counts as an
        action so a codex-only change never renders "Already up to date.".
    """
    file_actions = sum(1 for f in plan.files if f.action != "skip")
    settings_actions = sum(1 for s in plan.settings if s.action != "skip")
    codex_actions = 1 if plan.codex is not None and plan.codex.action in ("install", "update") else 0
    return file_actions, settings_actions, codex_actions


# Modules that are intentionally empty in the source tree (only .gitkeep).
# Checked by allowlist so a broken wheel that omits skills/ still warns.
_INTENTIONALLY_EMPTY_MODULES: set[InstallModule] = {
    InstallModule.AGENTS,
    InstallModule.COMMANDS,
}


def _warn_if_modules_have_no_files(
    plan: InstallPlan,
    scope: InstallScope,
    project_root: Path | None,
    tracking: TrackingStore,
) -> None:
    """Warn when a file-bearing module has no files anywhere (plan or tracking).

    A clean install with 0 files in the plan is normal IF the existing
    tracked install already has files for the module. But if neither plan
    nor tracking has files for an enabled file-bearing module, the install
    is broken — typically a wheel missing bundled extensions.
    """
    enabled = {InstallModule(m) for m in plan.modules if InstallModule(m) in FILE_MODULES}
    enabled -= _INTENTIONALLY_EMPTY_MODULES
    if not enabled:
        return

    project_str = None if scope == InstallScope.USER else (str(project_root) if project_root else None)
    existing = tracking.get_installation(scope.value, project_str)

    def _module_has_files(module: InstallModule, paths: list[str]) -> bool:
        sep = f"/{module.value}/"
        return any(sep in p for p in paths)

    plan_paths = [f.target_path for f in plan.files]
    existing_paths = [f.target_path for f in existing.files] if existing else []

    missing = {m for m in enabled if not _module_has_files(m, plan_paths) and not _module_has_files(m, existing_paths)}
    if not missing:
        return

    names = ", ".join(sorted(m.value for m in missing))
    console.print(
        f"\n[yellow]Warning:[/yellow] No files found for enabled module(s): {names}. "
        "Your Forge installation may be missing bundled extensions. "
        "Try reinstalling: 'pip install --force-reinstall <wheel>'."
    )


def _enforce_project_compatibility(project_root: Path | None) -> None:
    """Block project-local mutations when `.forge/project.toml` requires it."""

    if project_root is None:
        return
    try:
        enforce_project_compatibility(project_root)
    except ProjectCompatibilityError as e:
        print_error(f"{e.reason}")
        print_tip(format_project_compatibility_recovery(), console=console)
        sys.exit(1)


def _enroll_project_root(
    project_root: Path | None,
    source: EnrollmentSource,
    *,
    announce: bool = False,
) -> None:
    """Enroll a project/local install target in the trusted-project registry."""

    if project_root is None:
        return
    result = ProjectRegistryStore().enroll(project_root, source)
    if announce:
        state = "enrolled" if result.created else "already enrolled"
        console.print(f"[dim]Project registry: {state} {display_path(result.entry.canonical_path)}[/dim]")


def _print_completion_message(
    plan: InstallPlan,
    scope: InstallScope,
    project_root: Path | None,
    tracking: TrackingStore,
) -> None:
    """Print appropriate completion message based on what was done."""
    file_actions, settings_actions, codex_actions = _count_actions(plan)
    total_actions = file_actions + settings_actions + codex_actions

    _warn_if_modules_have_no_files(plan, scope, project_root, tracking)

    if total_actions == 0:
        console.print("\n[dim]Already up to date.[/dim]")
    else:
        parts = []
        if file_actions > 0:
            parts.append(f"{file_actions} file{'s' if file_actions != 1 else ''}")
        if settings_actions > 0:
            parts.append(f"{settings_actions} setting{'s' if settings_actions != 1 else ''}")
        if codex_actions > 0:
            parts.append("Codex hooks")
        console.print(f"\n[green]Extensions enabled.[/green] ({', '.join(parts)} updated)")

    if InstallModule.PERMISSIONS.value in plan.modules:
        print_tip(
            "Run 'forge claude preset edit' to customize permissions and env vars.",
            blank_before=False,
            console=console,
        )

    if InstallModule.SKILLS.value in plan.modules:
        print_tip(
            "Multi-model skills require proxy credentials. Run 'forge auth status' to check.",
            blank_before=False,
            console=console,
        )

    profile = InstallProfile(plan.profile)
    gated = get_gated_skills(profile)
    if gated:
        skill_list = ", ".join(f"/forge:{name}" for name, _ in gated)
        required = gated[0][1].value
        print_tip(
            f"Additional skills available with --profile {required}: {skill_list}",
            console=console,
        )

    _print_runtime_hook_completion(plan, scope)
    _print_codex_completion(plan, scope)


def _print_runtime_hook_completion(plan: InstallPlan, scope: InstallScope) -> None:
    """Explain the T5 scope split when a project/local profile no longer writes hooks."""

    if scope == InstallScope.USER:
        return
    try:
        profile = InstallProfile(plan.profile)
    except ValueError:
        return
    if PROFILE_RANK[profile] < PROFILE_RANK[InstallProfile.STANDARD]:
        return
    console.print("\n[dim]Next steps (runtime hooks):[/dim]")
    console.print("  - Runtime hooks install once at user scope.")
    console.print("  - Run 'forge extension enable --scope user' to register them globally.")


def _print_codex_completion(plan: InstallPlan, scope: InstallScope) -> None:
    """Print the trust-ceremony guidance (or skip notice) for the codex plan.

    Registration alone is inert: Codex hooks fire only after the user's
    one-time interactive trust ceremony, which Forge can neither perform nor
    verify -- so a fresh registration always names the ceremony explicitly.
    """
    codex = plan.codex
    if codex is None:
        return
    if codex.action in ("install", "update"):
        where = "in any project" if scope == InstallScope.USER else "in this project"
        config = display_path(codex.config_path) if codex.config_path else "config.toml"
        console.print("\n[dim]Next steps (Codex hooks):[/dim]")
        console.print(f"  - Forge hooks are registered in {config} but stay inert until trusted.")
        console.print(f"  - Run 'codex' interactively {where} and grant trust when prompted (one-time).")
    elif codex.action == "conflict":
        console.print(f"\n[yellow]Warning:[/yellow] Codex hook registration skipped: {codex.reason}")
    elif codex.action == "unavailable":
        console.print(f"\n[dim]Codex hooks skipped: {codex.reason}.[/dim]")


def _print_hook_migration_candidates(tracking: TrackingStore | None = None) -> None:
    """Report tracked cleanup candidates without reading or enrolling roots."""

    candidates = list_hook_migration_candidates(tracking)
    if not candidates:
        return
    console.print("\n[bold]Legacy hook cleanup candidates[/bold]")
    for candidate in candidates:
        if candidate.cleanup_command is not None:
            console.print(f"  - {display_path(candidate.root or '')}")
            console.print(f"    [dim]{candidate.cleanup_command}[/dim]")
        else:
            detail = candidate.reason or "no recoverable root"
            target = display_path(candidate.root) if candidate.root is not None else "unrecoverable tracking row"
            console.print(f"  - {target}: [yellow]{detail}[/yellow] ({', '.join(candidate.scopes)})")
    console.print("[dim]No project files or registry entries were changed.[/dim]")


def _finish_user_scope_hook_migration(plan: InstallPlan, tracking: TrackingStore | None = None) -> None:
    """Consolidate safe user legacy siblings and report root candidates."""

    store = tracking or TrackingStore()
    if InstallModule.HOOKS.value in plan.modules:
        cleanup = cleanup_user_legacy_hook_files()
        changed_paths = tuple(
            dict.fromkeys(
                [
                    *(Path(path) for path in plan.legacy_hook_cleanup_paths),
                    *cleanup.changed_paths,
                ]
            )
        )
        if changed_paths:
            console.print("\n[dim]Removed legacy user hook registrations from:[/dim]")
            for path in changed_paths:
                console.print(f"  - {display_path(path)}")
        if cleanup.unresolved:
            console.print("\n[yellow]Warning:[/yellow] Some user hook entries require manual cleanup:")
            for issue in cleanup.unresolved:
                console.print(f"  - {issue}")
    _print_hook_migration_candidates(store)


def _print_hook_migration_plan(plan: ProjectHookMigrationPlan) -> None:
    """Render a cleanup preview without mutating state."""

    from forge.install.hook_dispatcher import (
        get_hook_dispatcher_path,
        get_runtime_metadata_path,
    )

    console.print("\n[bold]Hook Migration Plan[/bold]")
    console.print(f"  Root: {display_path(plan.root)}")
    for settings_plan in plan.settings:
        if settings_plan.removals:
            tracked = sum(removal.source == "tracked" for removal in settings_plan.removals)
            fallback = len(settings_plan.removals) - tracked
            console.print(
                f"  - {display_path(settings_plan.path)}: remove {len(settings_plan.removals)} hook wrapper(s) "
                f"({tracked} tracked, {fallback} known legacy); backup first"
            )
        if settings_plan.added_path is not None:
            console.print(f"  - {display_path(settings_plan.added_path)}: reconcile Forge-owned settings metadata")
    if plan.codex.action == "remove":
        console.print(f"  - {display_path(plan.codex.config_path)}: remove managed Codex block; backup first")
    if plan.user.changed:
        if not plan.user.dispatcher_current:
            console.print(f"  - {display_path(get_hook_dispatcher_path())}: install/update hook dispatcher")
            console.print(f"  - {display_path(get_runtime_metadata_path())}: update dispatcher runtime metadata")
        for settings_plan in (plan.user.settings, plan.user.legacy_settings):
            if settings_plan.changed:
                console.print(f"  - {display_path(settings_plan.path)}: update user runtime hooks; backup first")
        if plan.user.codex is not None and plan.user.codex.action in {
            "install",
            "update",
        }:
            console.print(f"  - {display_path(plan.user.codex.config_path)}: install/update user Codex hooks")
        if plan.user.settings.added_path is not None:
            console.print(
                f"  - {display_path(plan.user.settings.added_path)}: reconcile Forge-owned user settings metadata"
            )
    tracked_root_change = any(
        InstallModule.HOOKS.value in installation.modules_enabled
        or InstallModule.CODEX_HOOKS.value in installation.modules_enabled
        or installation.codex_config_path
        or any(entry.key_path.startswith("hooks.") for entry in installation.settings_entries)
        for _scope, installation in plan.tracked_installations
    )
    if tracked_root_change or plan.user.changed:
        console.print(f"  - {display_path(TrackingStore().path)}: reconcile project/user hook ownership")
    if not plan.enrolled:
        console.print(
            f"  - {display_path(ProjectRegistryStore().path)}: enroll last, after cleanup and user registration "
            f"({display_path(plan.root)})"
        )
    if not plan.has_actions:
        console.print("  [dim]No migration changes required.[/dim]")
    if plan.blockers:
        console.print("\n[bold red]Cleanup blockers:[/bold red]")
        for blocker in plan.blockers:
            console.print(f"  [red]- {blocker}[/red]")


def _validate_anchor(anchor: Path) -> None:
    """Reject anchors that point inside a ``.claude/`` directory.

    The ``.claude/`` creation in ``enable_cmd`` runs before the installer's
    ``get_target_root()`` guard, so an anchor like ``/repo/.claude`` would
    create ``/repo/.claude/.claude/`` before the guard fires.
    """
    resolved = anchor.expanduser().resolve()
    if ".claude" in resolved.parts:
        raise click.UsageError(
            f"--root points inside a .claude directory: {anchor}\n"
            "Provide the project root instead (the parent of .claude/)."
        )


def _resolve_project_root(
    scope: InstallScope,
    *,
    anchor: Path | None = None,
    auto_create: bool = False,
) -> Path | None:
    """Resolve canonical project root for a given scope.

    For user scope, returns None.
    For project/local scope, finds the .claude directory and returns
    the canonicalized project root.  When *auto_create* is True and no
    ``.claude/`` exists, creates it at the git root (Rule 4).

    When *anchor* is provided, skips the walk-up and uses that path directly.

    Args:
        scope: The installation scope.
        anchor: Explicit target directory (skips walk-up when set).
        auto_create: Whether to create ``.claude/`` if missing (Rule 4).

    Returns:
        Canonicalized project root path, or None for user scope.

    Raises:
        NoClaudeDirectoryError: If no .claude directory found and auto-create
            is disabled or not in a git repo.
    """
    if scope == InstallScope.USER:
        return None

    if anchor is not None:
        resolved = anchor.expanduser().resolve()
        if auto_create and not (resolved / ".claude").is_dir():
            _create_claude_dir(resolved)
        return resolved

    try:
        _detected_scope, project_root = find_claude_root()
    except NoClaudeDirectoryError:
        # find_claude_root raises when walk reaches FS root without home;
        # treat the same as "no .claude/ found" for auto-create purposes.
        project_root = None

    if project_root is None:
        # Rule 4: auto-create .claude/ at git root for project/local enable
        git_root = _detect_git_project_root()
        if git_root is not None:
            if auto_create:
                _create_claude_dir(git_root)
            return git_root
        raise NoClaudeDirectoryError(
            "No .claude directory found. Use '--scope user' for global install, "
            "or run from within a Claude Code project."
        )

    # Canonicalize to handle symlinks and ensure consistent keys
    return project_root.resolve()


def _print_plan(plan: InstallPlan, dry_run: bool = False) -> None:
    """Print installation plan using Rich.

    Args:
        plan: The plan to display.
        dry_run: If True, prefix output with "(dry-run)".
    """
    prefix = "[dim](dry-run)[/dim] " if dry_run else ""

    console.print(f"\n{prefix}[bold]Installation Plan[/bold]")
    console.print(f"  Scope:   {plan.scope}")
    console.print(f"  Mode:    {plan.mode}")
    console.print(f"  Profile: {plan.profile}")
    console.print(f"  Modules: {', '.join(plan.modules)}")

    if plan.skill_packages:
        console.print(f"\n{prefix}[bold]Skill packages:[/bold]")
        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("ACTION", style="dim")
        table.add_column("RUNTIME")
        table.add_column("SKILL")
        table.add_column("TARGET")
        table.add_column("REASON", style="dim")
        for package in plan.skill_packages:
            style = {
                "install": "green",
                "update": "yellow",
                "skip": "dim",
                "conflict": "red",
            }.get(package.action, "")
            reason = package.reason or ""
            if package.duplicate_dirs:
                duplicates = ", ".join(display_path(path) for path in package.duplicate_dirs)
                reason = f"{reason}; duplicates: {duplicates}" if reason else f"duplicates: {duplicates}"
            table.add_row(
                package.action,
                package.runtime,
                package.skill,
                display_path(package.target_dir) if package.target_dir else "",
                reason,
                style=style,
            )
        console.print(table)

    if plan.files:
        console.print(f"\n{prefix}[bold]Files:[/bold]")
        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("ACTION", style="dim")
        table.add_column("PATH")
        table.add_column("REASON", style="dim")

        for f in plan.files:
            style = {
                "install": "green",
                "update": "yellow",
                "skip": "dim",
                "conflict": "red",
            }.get(f.action, "")
            table.add_row(f.action, display_path(f.target_path), f.reason or "", style=style)

        console.print(table)

    if plan.settings:
        console.print(f"\n{prefix}[bold]Settings:[/bold]")
        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("ACTION", style="dim")
        table.add_column("KEY")
        table.add_column("VALUE", style="dim")

        for s in plan.settings:
            style = "red" if s.action == "conflict" else ""
            value_str = str(s.value) if s.value else ""
            if s.action == "conflict":
                value_str = f"current={s.current_value!r}, forge={s.value!r}"
            table.add_row(s.action, s.key_path, value_str, style=style)

        console.print(table)

    if plan.codex is not None:
        console.print(f"\n{prefix}[bold]Codex hooks (config.toml):[/bold]")
        table = Table(show_header=True, header_style="bold", box=None)
        table.add_column("ACTION", style="dim")
        table.add_column("TARGET")
        table.add_column("REASON", style="dim")
        style = {
            "install": "green",
            "update": "yellow",
            "skip": "dim",
            "conflict": "yellow",  # best-effort: degrades to skip, never blocks
            "unavailable": "dim",
        }.get(plan.codex.action, "")
        target = display_path(plan.codex.config_path) if plan.codex.config_path else ""
        table.add_row(plan.codex.action, target, plan.codex.reason or "", style=style)
        console.print(table)

    if plan.has_conflicts:
        console.print(f"\n{prefix}[bold red]Conflicts detected:[/bold red]")
        for c in plan.conflicts:
            console.print(f"  [red]- {c}[/red]")
        has_policy_conflicts = any(
            package.action == "conflict" and package.reason in _NON_FORCEABLE_SKILL_CONFLICT_REASONS
            for package in plan.skill_packages
        )
        has_forceable_conflicts = any(file.action == "conflict" for file in plan.files) or any(
            setting.action == "conflict" for setting in plan.settings
        )
        if has_policy_conflicts and has_forceable_conflicts:
            print_tip(
                "Use --force only for file or settings conflicts; resolve runtime, scope, "
                "and duplicate-scan conflicts manually.",
                console=console,
            )
        elif has_policy_conflicts:
            print_tip(
                "Resolve runtime, scope, or duplicate-scan conflicts manually; --force does not override them.",
                console=console,
            )
        else:
            print_tip("Use --force to override, or resolve conflicts manually.", console=console)


def _uninstall_all_installations(tracking: TrackingStore, yes: bool) -> None:
    """Uninstall all tracked installations.

    Args:
        tracking: TrackingStore instance.
        yes: If True, skip confirmation prompt.
    """
    installations = tracking.list_installations()

    if not installations:
        console.print("[dim]No Forge installations found.[/dim]")
        return

    console.print(f"[bold]Found {len(installations)} Forge installation(s):[/bold]\n")

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
    table.add_column("SCOPE", style="cyan")
    table.add_column("PROJECT PATH")
    table.add_column("PROFILE")
    table.add_column("FILES")
    table.add_column("SKILL PACKAGES")

    for scope, project_path, installation in installations:
        scope_display = scope
        path_display = project_path or "(global)"
        if len(path_display) > 40:
            path_display = "…" + path_display[-37:]
        table.add_row(
            scope_display,
            path_display,
            installation.profile,
            str(len(installation.files)),
            str(len(installation.skill_packages)),
        )

    console.print(table)
    console.print()

    if not yes:
        if not click.confirm("Disable ALL of these?"):
            console.print("[dim]Cancelled.[/dim]")
            return

    errors = []
    for scope, project_path, _installation in installations:
        try:
            console.print(f"\n[bold]Disabling {scope}[/bold]", end="")
            if project_path:
                console.print(f" [dim]({display_path(project_path)})[/dim]")
            else:
                console.print()

            install_scope = InstallScope(scope)
            project_root = Path(project_path) if project_path else None

            _enforce_project_compatibility(project_root)

            installer = Installer(scope=install_scope, project_root=project_root)
            installer.uninstall()
            console.print("  [green]✓ Done[/green]")

        except ForgeInstallError as e:
            console.print(f"  [red]✗ Failed: {e}[/red]")
            errors.append((scope, project_path, str(e)))

    console.print()
    if errors:
        console.print(f"[yellow]Completed with {len(errors)} error(s).[/yellow]")
        for scope, path, err in errors:
            console.print(f"  [red]- {scope} ({display_path(path) if path else 'global'}): {err}[/red]")
    else:
        console.print(f"[green]All {len(installations)} installation(s) disabled.[/green]")


def _can_resolve_project_root(scope: InstallScope, *, anchor: Path | None = None) -> bool:
    """Check if project root can be resolved without raising."""
    try:
        _resolve_project_root(scope, anchor=anchor)
        return True
    except NoClaudeDirectoryError:
        return False


def _resolve_status_project_root(scope: InstallScope, anchor: Path | None) -> Path | None:
    """Resolve a status lookup root, including tracked installs without ``.claude``."""

    try:
        return _resolve_project_root(scope, anchor=anchor)
    except NoClaudeDirectoryError:
        try:
            detected_scope, detected_root = find_forge_installation(start=anchor)
        except NoForgeInstallationError:
            return None
        return detected_root if detected_scope == scope else None


# --- Commands ---


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def extensions() -> None:
    """Manage Forge extensions lifecycle.

    \b
    Examples:
        forge extension enable                  # Auto-detect scope, enable
        forge extension status                 # Show installation status
        forge extension sync                   # Sync to latest version
    """
    pass


@extensions.command("enable")
@click.option(
    "--scope",
    "-S",
    type=click.Choice(["local", "project", "user"]),
    default=None,
    help=_INSTALL_SCOPE_HELP,
)
@click.option(
    "--root",
    "path",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    default=None,
    help="Target directory (default: walk up from cwd to find .claude/)",
)
@click.option(
    "--profile",
    "-p",
    type=click.Choice(["minimal", "standard", "full"]),
    default="standard",
    help="Installation profile",
)
@click.option(
    "--copy",
    "-c",
    "mode",
    flag_value="copy",
    default=True,
    help="Copy files (default)",
)
@click.option(
    "--symlink",
    "-s",
    "mode",
    flag_value="symlink",
    help="Symlink files (dev mode)",
)
@click.option(
    "--with",
    "-w",
    "with_modules",
    help="Add modules (comma-separated: commands,agents,skills,hooks,status-line,permissions,codex-hooks)",
)
@click.option(
    "--without",
    "-W",
    "without_modules",
    help="Remove modules (comma-separated)",
)
@click.option(
    "--runtime",
    "runtimes",
    type=click.Choice(["claude", "codex", "all"]),
    multiple=True,
    help="Skill runtime target; repeat for multiple targets (default: Claude plus detected Codex)",
)
@click.option("--force", "-f", is_flag=True, help="Override conflicts")
@click.option("--dry-run", "-n", is_flag=True, help="Show plan without executing")
def enable_cmd(
    scope: str | None,
    path: str | None,
    profile: str,
    mode: str,
    with_modules: str | None,
    without_modules: str | None,
    runtimes: tuple[str, ...],
    force: bool,
    dry_run: bool,
) -> None:
    """Enable Forge extensions.

    \b
    Scope Detection (when no --scope specified):
        Walks up from current directory looking for a .claude/ directory.
        - If found: enables local in that project's .claude/settings.local.json
        - If in a git repo: enables local at the git root
        - If reached ~: enables user in ~/.claude/settings.json
        - If not found: fails (use --scope user outside a project)

    \b
    Examples:
        forge extension enable                                # Auto-detect scope
        forge extension enable --scope local                  # Local at nearest .claude/
        forge extension enable --scope local --root /repo/api # Local at specific path
        forge extension enable --root /repo/api               # Same (defaults to local)
        forge extension enable --scope user                   # Global ~/.claude
        forge extension enable --profile minimal              # Commands only
        forge extension enable --runtime codex                # Target skill packages at Codex
        forge extension enable --runtime claude --runtime codex
        forge extension enable --dry-run                      # Preview changes
    """
    try:
        anchor = Path(path) if path else None

        # Validate: --scope user + --root is contradictory
        if scope == "user" and anchor is not None:
            raise click.UsageError("--scope user is global; --root is not applicable.")

        # Validate: anchor must not point inside .claude/
        if anchor is not None:
            _validate_anchor(anchor)

        # Default: --root without --scope implies local
        if anchor is not None and scope is None:
            scope = "local"

        # --- Scope resolution (Rule 4: auto-create .claude/ in git repos) ---
        needs_create = False

        if scope is None:
            try:
                install_scope, project_root = find_claude_root()
            except NoClaudeDirectoryError:
                git_root = _detect_git_project_root()
                if git_root is None:
                    raise
                install_scope = InstallScope.LOCAL
                project_root = git_root
                needs_create = not (git_root / ".claude").is_dir()
            else:
                # P1 fix: auto-detect in a git repo should prefer LOCAL over USER
                if install_scope == InstallScope.USER:
                    git_root = _detect_git_project_root()
                    if git_root is not None:
                        install_scope = InstallScope.LOCAL
                        project_root = git_root
                        needs_create = not (git_root / ".claude").is_dir()
            console.print(f"[dim]Auto-detected scope: {install_scope.value}[/dim]")
        else:
            install_scope = InstallScope(scope)
            project_root = _resolve_project_root(install_scope, anchor=anchor, auto_create=False)
            if project_root is not None:
                needs_create = not (project_root / ".claude").is_dir()

        _enforce_project_compatibility(project_root)

        # Rule 1 anchor: .forge/ is required for session start.
        # Preview in dry-run; actual creation deferred until installer succeeds.
        needs_forge = project_root is not None and not (project_root / ".forge").is_dir()
        if needs_forge and dry_run and project_root is not None:
            console.print(f"[dim]Would create {display_path(project_root / '.forge')}[/dim]")

        install_profile = InstallProfile(profile)
        install_mode = InstallMode(mode)
        selected_runtimes = _parse_skill_runtimes(runtimes)

        installer = Installer(scope=install_scope, project_root=project_root)
        plan = installer.plan(
            profile=install_profile,
            mode=install_mode,
            with_modules=_parse_modules(with_modules),
            without_modules=_parse_modules(without_modules),
            force=force,
            skill_runtimes=selected_runtimes,
        )

        if dry_run:
            if needs_create and project_root is not None and plan.requires_claude_version:
                console.print(f"[dim]Would create {display_path(project_root / '.claude')}[/dim]")
            _print_plan(plan, dry_run=True)
            if plan.has_conflicts:
                sys.exit(1)
            if install_scope == InstallScope.USER:
                _print_hook_migration_candidates()
        else:
            if plan.has_conflicts:
                _print_plan(plan)
                console.print("\n[red]Enable failed due to conflicts.[/red]")
                sys.exit(1)
            _enforce_claude_version_if_required(plan, project_root)
            if needs_create and project_root is not None and plan.requires_claude_version:
                _create_claude_dir(project_root)
            plan = installer.init(
                profile=install_profile,
                mode=install_mode,
                with_modules=_parse_modules(with_modules),
                without_modules=_parse_modules(without_modules),
                force=force,
                skill_runtimes=selected_runtimes,
            )
            _print_plan(plan)
            if plan.has_conflicts:
                console.print("\n[red]Enable failed due to conflicts.[/red]")
                sys.exit(1)
            else:
                # Create .forge/ only after installer succeeds (avoids orphaned
                # directories if enable fails due to conflicts).
                if needs_forge and project_root is not None:
                    (project_root / ".forge").mkdir(exist_ok=True)
                    _log.info("Created %s for session state", project_root / ".forge")

                _enroll_project_root(project_root, "enable", announce=True)
                tracking = TrackingStore()
                _print_completion_message(plan, install_scope, project_root, tracking)
                if install_scope == InstallScope.USER:
                    _finish_user_scope_hook_migration(plan, tracking)

    except click.UsageError:
        raise
    except NoClaudeDirectoryError as e:
        print_error(f"{e}")
        print_tip(
            "Use --scope user to enable globally, or --root <dir> to target a specific directory.",
            console=console,
        )
        sys.exit(1)
    except SettingsConflictError as e:
        console.print(f"[red]Settings conflict:[/red] {e}")
        print_tip("Use --force to override.", console=console)
        sys.exit(1)
    except (StateCorruptedError, StateUnreadableError):
        raise  # corruption defers to the unified top-level handler (uniform reset tip)
    except ForgeInstallError as e:
        print_error(f"{e}")
        sys.exit(1)


@extensions.command("sync")
@click.option(
    "--scope",
    "-S",
    type=click.Choice(["local", "project", "user"]),
    default=None,
    help=_INSTALL_SCOPE_HELP,
)
@click.option("--force", "-f", is_flag=True, help="Override conflicts")
def sync_cmd(scope: str | None, force: bool) -> None:
    """Sync existing Forge extensions.

    Re-runs the enable with the same profile and mode as originally
    configured, refreshing all files and settings from the current Forge
    source.

    \b
    Scope Detection (when no --scope specified):
        Walks up from current directory looking for existing Forge extensions
        (detected by .settings.*.json.forge.* files in .claude/).
        - Checks LOCAL first, then PROJECT, then USER
        - Fails if no extensions found

    \b
    Examples:
        forge extension sync                    # Sync Forge extensions
        forge extension sync --scope local      # Sync local scope
        forge extension sync --force            # Force re-sync
    """
    try:
        if scope is None:
            install_scope, project_root = find_forge_installation()
            console.print(f"[dim]Auto-detected scope: {install_scope.value}[/dim]")
        else:
            install_scope = InstallScope(scope)
            try:
                project_root = _resolve_project_root(install_scope)
            except NoClaudeDirectoryError:
                detected_scope, detected_root = find_forge_installation()
                if detected_scope != install_scope:
                    raise NotInstalledError(install_scope.value) from None
                project_root = detected_root

        _enforce_project_compatibility(project_root)

        installer = Installer(scope=install_scope, project_root=project_root)
        preview = installer.plan_update(force=force)
        if preview.has_conflicts:
            _print_plan(preview)
            console.print("\n[red]Sync failed due to conflicts.[/red]")
            sys.exit(1)
        _enforce_claude_version_if_required(preview, project_root)
        plan = installer.update(force=force)

        _print_plan(plan)
        if plan.has_conflicts:
            console.print("\n[red]Sync failed due to conflicts.[/red]")
            sys.exit(1)
        else:
            file_actions, settings_actions, codex_actions = _count_actions(plan)
            total_actions = file_actions + settings_actions + codex_actions
            if total_actions == 0:
                console.print("\n[dim]Already up to date.[/dim]")
            else:
                parts = []
                if file_actions > 0:
                    parts.append(f"{file_actions} file{'s' if file_actions != 1 else ''}")
                if settings_actions > 0:
                    parts.append(f"{settings_actions} setting{'s' if settings_actions != 1 else ''}")
                if codex_actions > 0:
                    parts.append("Codex hooks")
                console.print(f"\n[green]Sync complete.[/green] ({', '.join(parts)} updated)")

            # A synced block can carry NEW entries whose trust is not yet
            # granted (per-entry trusted_hash) -- the ceremony guidance
            # matters most exactly here.
            _print_runtime_hook_completion(plan, install_scope)
            _print_codex_completion(plan, install_scope)
            if install_scope == InstallScope.USER:
                _finish_user_scope_hook_migration(plan)

    except NoForgeInstallationError as e:
        print_error(f"{e}")
        sys.exit(1)
    except NotInstalledError as e:
        print_error(f"{e}")
        print_tip("Run 'forge extension enable' first.", console=console)
        sys.exit(1)
    except (StateCorruptedError, StateUnreadableError):
        raise  # corruption defers to the unified top-level handler (uniform reset tip)
    except ForgeInstallError as e:
        print_error(f"{e}")
        sys.exit(1)


@extensions.command("cleanup-project")
@click.option(
    "--root",
    "path",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    default=None,
    help="Forge project root to clean (default: current Forge root)",
)
@click.option("--yes", is_flag=True, help="Apply the previewed migration")
def cleanup_project_cmd(path: str | None, yes: bool) -> None:
    """Preview or apply legacy project-hook cleanup for one Forge root."""

    from forge.core.ops.context import find_forge_root

    try:
        anchor = Path(path) if path else Path.cwd()
        if path:
            _validate_anchor(anchor)
        root = find_forge_root(anchor.expanduser().resolve())
        if root is None:
            raise HookMigrationError(
                f"'{anchor}' is not inside a Forge project (expected a project root containing .forge/)"
            )

        _enforce_project_compatibility(root)
        plan = plan_project_hook_migration(root)
        _print_hook_migration_plan(plan)
        if plan.blockers:
            print_tip(
                "Resolve the listed entries manually, then rerun the preview.",
                console=console,
            )
            raise click.exceptions.Exit(1)
        if not yes:
            if plan.has_actions:
                print_tip(
                    f"Apply with: forge extension cleanup-project --root {shlex.quote(str(root))} --yes",
                    console=console,
                )
            return

        result = apply_project_hook_migration(root)
        if result.changed_paths or result.enrollment_created:
            console.print("\n[green]Project hook migration complete.[/green]")
            console.print(f"  Removed hooks: {result.removed_hooks}")
            console.print(f"  Registry:      {'enrolled' if result.enrollment_created else 'already enrolled'}")
            if result.backup_paths:
                console.print("  Backups:")
                for backup in result.backup_paths:
                    console.print(f"    - {display_path(backup)}")
        else:
            console.print("\n[dim]Already migrated; no changes required.[/dim]")
        if result.user_codex_action in {
            "install",
            "update",
        }:
            console.print("\n[dim]Next steps (Codex hooks):[/dim]")
            console.print("  - Run 'codex' interactively in this project and grant trust when prompted (one-time).")

    except click.UsageError:
        raise
    except click.exceptions.Exit:
        raise
    except (StateCorruptedError, StateUnreadableError):
        raise
    except HookMigrationError as e:
        print_error(str(e))
        sys.exit(1)
    except ForgeInstallError as e:
        print_error(str(e))
        sys.exit(1)


@extensions.command("disable")
@click.option(
    "--scope",
    "-S",
    type=click.Choice(["local", "project", "user"]),
    default=None,
    help=_INSTALL_SCOPE_HELP,
)
@click.option(
    "--all",
    "-a",
    "uninstall_all",
    is_flag=True,
    help="Disable ALL tracked installations",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
def disable_cmd(scope: str | None, uninstall_all: bool, yes: bool) -> None:
    """Disable Forge extensions.

    Removes only files and settings entries that were added by Forge.
    User modifications are preserved.

    \b
    Scope Detection (when no --scope/--all specified):
        Walks up from current directory looking for existing Forge extensions
        (detected by .settings.*.json.forge.* files in .claude/).
        - Checks LOCAL first, then PROJECT, then USER
        - Fails if no extensions found

    \b
    --all mode:
        Disables ALL tracked installations (user + all local/project).
        Uses ~/.forge/installed.json to find all installations.

    \b
    Examples:
        forge extension disable                   # Auto-detect scope
        forge extension disable --scope local     # Disable local scope
        forge extension disable --all --yes       # Disable everything
    """
    if uninstall_all and scope is not None:
        raise click.UsageError("--all and --scope are mutually exclusive.")
    try:
        tracking = TrackingStore()

        if uninstall_all:
            _uninstall_all_installations(tracking, yes)
            return

        if scope is None:
            install_scope, project_root = find_forge_installation()
            console.print(f"[dim]Auto-detected scope: {install_scope.value}[/dim]")
        else:
            install_scope = InstallScope(scope)
            try:
                project_root = _resolve_project_root(install_scope)
            except NoClaudeDirectoryError:
                detected_scope, detected_root = find_forge_installation()
                if detected_scope != install_scope:
                    raise NoForgeInstallationError(str(Path.cwd())) from None
                project_root = detected_root

        _enforce_project_compatibility(project_root)

        project_path_str = str(project_root) if project_root else None
        existing = tracking.get_installation(install_scope.value, project_path_str)

        if existing is None:
            console.print(f"[dim]No Forge installation for scope '{install_scope.value}'.[/dim]")
            return

        console.print(f"[bold]Will disable Forge extensions ({install_scope.value}):[/bold]")
        console.print(f"  Profile:  {existing.profile}")
        console.print(f"  Mode:     {existing.mode}")
        console.print()

        if existing.skill_packages:
            table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
            table.add_column("ACTION", style="red")
            table.add_column("RUNTIME")
            table.add_column("SKILL")
            table.add_column("TARGET")
            for package in existing.skill_packages:
                table.add_row(
                    "remove",
                    package.runtime,
                    package.skill,
                    display_path(package.target_dir),
                )
            console.print("[bold]Skill packages:[/bold]")
            console.print(table)
            console.print()

        if existing.files:
            table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
            table.add_column("ACTION", style="red")
            table.add_column("PATH")
            for f in existing.files:
                # Truncate long paths for display
                path_str = str(f.target_path)
                if len(path_str) > 60:
                    path_str = path_str[:57] + "…"
                table.add_row("remove", path_str)
            console.print("[bold]Files:[/bold]")
            console.print(table)
            console.print()

        if existing.settings_entries:
            table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
            table.add_column("ACTION", style="red")
            table.add_column("KEY")
            for entry in existing.settings_entries:
                table.add_row("unmerge", entry.key_path)
            console.print("[bold]Settings:[/bold]")
            console.print(table)

        if existing.codex_config_path:
            console.print("\n[bold]Codex hooks:[/bold]")
            console.print(f"  [red]remove[/red] managed block in {display_path(existing.codex_config_path)}")

        if not yes:
            if not click.confirm("\nProceed with disable?"):
                console.print("[dim]Cancelled.[/dim]")
                return

        installer = Installer(scope=install_scope, project_root=project_root)
        installer.uninstall()

        # Remove .forge/ anchor if it's empty (no sessions, artifacts, etc.).
        # .claude/ is NOT removed — it may contain user-authored content.
        if project_root is not None:
            forge_dir = project_root / ".forge"
            if forge_dir.is_dir():
                try:
                    forge_dir.rmdir()  # Only succeeds if empty
                    _log.info("Removed empty %s", forge_dir)
                except OSError:
                    pass  # Non-empty: sessions/artifacts still present

        console.print("\n[green]Extensions disabled.[/green]")

    except NoForgeInstallationError as e:
        print_error(f"{e}")
        sys.exit(1)
    except (StateCorruptedError, StateUnreadableError):
        # Includes TrackingCorruptedError -- defers to the unified top-level handler
        # (uniform reset tip) instead of printing a raw parse error.
        raise
    except ForgeInstallError as e:
        print_error(f"{e}")
        sys.exit(1)


@extensions.command("status")
@click.option(
    "--scope",
    "-S",
    type=click.Choice(["local", "project", "user"]),
    default=None,
    help=_INSTALL_SCOPE_HELP,
)
@click.option(
    "--root",
    "path",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
    default=None,
    help="Target directory to check (default: walk up from cwd)",
)
@click.option("--all", "-a", "show_all", is_flag=True, help="Show all scopes")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status_cmd(scope: str | None, path: str | None, show_all: bool, as_json: bool) -> None:
    """Show extensions status.

    Displays what Forge has enabled in the specified scope(s).

    \b
    Scope Detection (when no --scope/--all specified):
        Walks up from current directory looking for existing Forge installations
        (detected by .settings.*.json.forge.* files in .claude/).
        - Checks LOCAL first, then PROJECT, then USER
        - If no installation found, shows all scopes for informational purposes

    \b
    Examples:
        forge extension status                                # Auto-detect
        forge extension status --scope local --root /repo/api # Check specific install
        forge extension status --root /repo/api               # Auto-detect scope at path
        forge extension status --all                          # Show all scopes
    """
    import os

    anchor = Path(path) if path else None

    if show_all and scope is not None:
        raise click.UsageError("--all and --scope are mutually exclusive.")
    if show_all and anchor is not None:
        raise click.UsageError("--all and --root are mutually exclusive.")
    if scope == "user" and anchor is not None:
        raise click.UsageError("--scope user is global; --root is not applicable.")

    # A corrupt installed.json raises TrackingCorruptedError (a StateCorruptedError);
    # it propagates to the top-level handler for the uniform reset tip.
    tracking = TrackingStore()
    tracked_installations = tracking.list_installations()
    installations_by_target = {
        (tracked_scope, project_path): installation
        for tracked_scope, project_path, installation in tracked_installations
    }

    cwd = os.getcwd()

    # When auto-detect finds the real install root (which may differ from
    # anchor if --root points at a subdirectory), use it for tracking lookups.
    detected_root: Path | None = None

    detected_scope_name: str | None = None
    if show_all:
        scopes = [InstallScope.USER, InstallScope.PROJECT, InstallScope.LOCAL]
    elif scope is None and anchor is None:
        try:
            detected_scope, detected_root = find_forge_installation()
            detected_scope_name = detected_scope.value
            scopes = [detected_scope]
        except NoForgeInstallationError:
            scopes = [InstallScope.USER, InstallScope.PROJECT, InstallScope.LOCAL]
    elif scope is None and anchor is not None:
        # --root without --scope: auto-detect scope at that path
        try:
            detected_scope, detected_root = find_forge_installation(start=anchor)
            detected_scope_name = detected_scope.value
            scopes = [detected_scope]
        except NoForgeInstallationError:
            scopes = [InstallScope.USER, InstallScope.PROJECT, InstallScope.LOCAL]
    else:
        scopes = [InstallScope(scope)]

    # Use the detected root (from walk-up) over the raw anchor for lookups.
    effective_anchor = detected_root if detected_root is not None else anchor

    if as_json:
        import json

        data = []
        for s in scopes:
            project_root = _resolve_status_project_root(s, effective_anchor)
            project_path_str = str(project_root) if project_root else None

            inst = installations_by_target.get((s.value, project_path_str))
            if inst is None:
                continue
            package_statuses = inspect_skill_package_status(
                inst,
                s,
                project_root,
                tracked_installations=tracked_installations,
            )
            data.append(
                {
                    "scope": s.value,
                    "profile": inst.profile,
                    "mode": inst.mode,
                    "modules": list(inst.modules_enabled),
                    "files_count": len(inst.files),
                    "skill_packages": [
                        {
                            "runtime": package_status.runtime,
                            "skill": package_status.skill,
                            "target_dir": package_status.target_dir,
                            "file_paths": list(package_status.file_paths),
                            "state": package_status.state,
                            "target_present": package_status.target_present,
                            "missing_file_paths": list(package_status.missing_file_paths),
                            "duplicate_dirs": list(package_status.duplicate_dirs),
                            "recovery": package_status.recovery,
                        }
                        for package_status in package_statuses
                    ],
                    "settings_count": len(inst.settings_entries),
                    "codex_config_path": inst.codex_config_path,
                    "codex_commands": list(inst.codex_commands),
                    "installed_at": inst.installed_at,
                    "updated_at": inst.updated_at,
                }
            )
        click.echo(json.dumps(data, indent=2, default=str))
        return

    if detected_scope_name:
        console.print(f"[dim]Auto-detected scope: {detected_scope_name}[/dim]")
    elif scope is None and not show_all:
        location = display_path(str(anchor)) if anchor else display_path(cwd)
        console.print(f"[dim]No extensions detected in {location}[/dim]")
        console.print("[dim]Showing all scopes for this location:[/dim]")

    for s in scopes:
        project_root = _resolve_status_project_root(s, effective_anchor)
        project_path_str = str(project_root) if project_root else None

        installation = installations_by_target.get((s.value, project_path_str))

        console.print(f"\n[bold]Scope: {s.value}[/bold]")

        if installation is None:
            if s == InstallScope.USER:
                location = "~/.claude"
            elif project_path_str:
                location = project_path_str
            else:
                location = str(anchor) if anchor else cwd
            console.print(f"  [dim]Not enabled at {display_path(location)}[/dim]")
            continue

        console.print(f"  Profile:   {installation.profile}")
        console.print(f"  Mode:      {installation.mode}")
        console.print(f"  Modules:   {', '.join(installation.modules_enabled)}")
        console.print(f"  Files:     {len(installation.files)}")
        console.print(f"  Skills:    {len(installation.skill_packages)} runtime package(s)")
        console.print(f"  Settings:  {len(installation.settings_entries)} entries")
        if installation.codex_config_path:
            console.print(f"  Codex:     hooks registered in {display_path(installation.codex_config_path)}")
        console.print(f"  Installed: {installation.installed_at}")
        console.print(f"  Updated:   {installation.updated_at}")

        if installation.skill_packages:
            package_statuses = inspect_skill_package_status(
                installation,
                s,
                project_root,
                tracked_installations=tracked_installations,
            )
            table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
            table.add_column("STATE")
            table.add_column("RUNTIME")
            table.add_column("SKILL")
            table.add_column("TARGET")
            for package_status in package_statuses:
                style = {
                    "present": "green",
                    "missing": "yellow",
                    "duplicate": "red",
                    "invalid-target": "red",
                }.get(package_status.state, "")
                table.add_row(
                    package_status.state,
                    package_status.runtime,
                    package_status.skill,
                    display_path(package_status.target_dir),
                    style=style,
                )
            console.print("\n  [dim]Skill packages:[/dim]")
            console.print(table)
            for package_status in package_statuses:
                if package_status.duplicate_dirs:
                    console.print(
                        f"  [red]{package_status.runtime}/{package_status.skill} duplicates:[/red] "
                        + ", ".join(display_path(path) for path in package_status.duplicate_dirs)
                    )
                if package_status.missing_file_paths:
                    console.print(
                        f"  [yellow]{package_status.runtime}/{package_status.skill} missing files:[/yellow] "
                        + ", ".join(display_path(path) for path in package_status.missing_file_paths)
                    )
                if package_status.recovery:
                    console.print(
                        f"  [yellow]{package_status.runtime}/{package_status.skill}:[/yellow] "
                        f"{package_status.recovery}"
                    )

        try:
            inst_profile = InstallProfile(installation.profile)
            gated = get_gated_skills(inst_profile)
            if gated:
                skill_list = ", ".join(f"/forge:{name}" for name, _ in gated)
                required = gated[0][1].value
                console.print(f"  [dim]Gated:    {skill_list} (needs --profile {required})[/dim]")
        except ValueError:
            pass

        if installation.files and len(installation.files) <= 10:
            console.print("\n  [dim]Files:[/dim]")
            for f in installation.files:
                console.print(f"    - {display_path(f.target_path)}")

    if scope is None and not show_all and anchor is None:
        local_installed = any(
            tracking.get_installation(
                s.value,
                str(_resolve_project_root(s)) if s != InstallScope.USER else None,
            )
            for s in scopes
            if s == InstallScope.USER or _can_resolve_project_root(s)
        )
        if not local_installed:
            all_installations = tracking.list_installations()
            if all_installations:
                print_tip(
                    f"{len(all_installations)} installation(s) exist elsewhere. Run 'forge info' to see all.",
                    console=console,
                )
            else:
                print_tip("Run 'forge extension enable' to set up Forge.", console=console)


@extensions.command("doctor")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def doctor_cmd(as_json: bool) -> None:
    """Report how Forge is installed and whether it is globally reachable.

    Answers "how was ``forge`` installed, and can a hook subprocess find it?" --
    the install kind (global tool / editable / venv), the resolved ``forge``
    launcher path, and PATH reachability including a GUI/launchd-style minimal
    PATH. Distinct from ``forge info`` (the general dashboard).

    \b
    Examples:
        forge extension doctor
        forge extension doctor --json
    """
    import json

    from forge.core.ops.context import find_forge_root
    from forge.install.doctor import diagnose_install
    from forge.install.hook_dispatcher import diagnose_hook_dispatcher
    from forge.install.project_compat import diagnose_project_compatibility
    from forge.install.project_registry import diagnose_project_registry

    # Diagnostic: always exits 0 -- health lives in the payload (install_kind,
    # on_path*, advice), not the exit code. A non-zero-on-unhealthy mode is a
    # future question if hooks/CI ever gate on doctor (epic T2/T5).
    registry_diag = diagnose_project_registry()
    dispatcher_diag = diagnose_hook_dispatcher()
    # The recorded launcher counts as a durable hook-resolver target, so the
    # install-section advice clears for custom runtime.json launchers too.
    diag = diagnose_install(recorded_launcher=dispatcher_diag.forge_binary_path)
    compat_root = find_forge_root(Path.cwd().resolve())
    compat_diag = diagnose_project_compatibility(compat_root)
    cwd = Path.cwd().resolve()
    hook_diagnostics = diagnose_forge_hook_runtime(cwd)
    hook_scopes = sorted(
        {registration.scope for registration in hook_diagnostics.registrations if registration.event == "SessionStart"}
    )
    hook_double_fire = hook_diagnostics.double_fire_risk
    cleanup_registrations = list(hook_diagnostics.cleanup_registrations)
    hook_cleanup_required = bool(cleanup_registrations)

    if as_json:
        payload = diag.to_dict()
        payload["hook_dispatcher"] = dispatcher_diag.to_dict()
        payload["runtime_hooks"] = {
            "scopes": hook_scopes,
            "double_fire_risk": hook_double_fire,
            "cleanup_required": hook_cleanup_required,
            "legacy_registrations": [
                {
                    "scope": registration.scope,
                    "settings_path": str(registration.settings_path),
                    "event": registration.event,
                    "matcher": registration.matcher,
                    "handler": registration.handler,
                    "command": registration.command,
                }
                for registration in cleanup_registrations
            ],
        }
        payload["project_registry"] = registry_diag.to_dict()
        payload["project_compatibility"] = compat_diag.to_dict()
        click.echo(json.dumps(payload, indent=2))
        return

    console.print("\n[bold]Forge install doctor[/bold]")
    console.print(f"  Install kind:    {diag.install_kind}")
    forge_path = display_path(diag.forge_path) if diag.forge_path else "[yellow]not found[/yellow]"
    console.print(f"  forge path:      {forge_path}")
    console.print(f"  On PATH:         {'[green]yes[/green]' if diag.on_path else '[red]no[/red]'}")
    # on_path_minimal=no is expected even for a healthy global install (~/.local/bin
    # is not on launchd's PATH), so it is shown plainly, not as a health failure.
    console.print(
        f"  On minimal PATH: {'yes' if diag.on_path_minimal else 'no'} "
        "[dim](GUI/launchd default -- excludes ~/.local/bin)[/dim]"
    )

    if diag.advice:
        print_tip(diag.advice, commands=list(diag.advice_commands), console=console)

    console.print("\n[bold]Hook dispatcher[/bold]")
    console.print(f"  Path:           {display_path(dispatcher_diag.path)}")
    console.print(f"  Status:         {dispatcher_diag.status}")
    if dispatcher_diag.installed_version:
        console.print(f"  Version:        {dispatcher_diag.installed_version}")
    if dispatcher_diag.forge_binary_path:
        console.print(f"  forge target:   {escape(display_path(dispatcher_diag.forge_binary_path))}")
    override = dispatcher_diag.dev_override
    if override.present:
        value = override.value if override.value else "[empty]"
        console.print(f"  Dev override:   {escape(value)}")
        if override.target:
            console.print(f"  Dev target:     {escape(display_path(override.target))}")
        console.print(f"  Dev valid:      {'yes' if override.valid else 'no'}")
        console.print(f"  Dev effective:  {'yes' if override.effective else 'no'}")
        if override.advice and (not override.valid or dispatcher_diag.advice is None):
            print_tip(escape(override.advice), console=console)
    else:
        console.print("  Dev override:   not set")
    console.print("  Dev env scope:  this doctor process; hook launch environments may differ")
    if dispatcher_diag.advice:
        print_tip(escape(dispatcher_diag.advice), console=console)

    console.print("\n[bold]Runtime hooks[/bold]")
    console.print(f"  Scopes:         {', '.join(hook_scopes) if hook_scopes else 'none'}")
    console.print(f"  Cleanup needed: {'yes' if hook_cleanup_required else 'no'}")
    if hook_cleanup_required:
        console.print("  [yellow]Warning:[/yellow] Legacy project/local or direct user hooks still need cleanup.")
        for registration in cleanup_registrations:
            console.print(
                f"    - {registration.scope}: {display_path(registration.settings_path)} "
                f"({registration.event}/{registration.handler})"
            )
        print_tip(
            "Preview the selected project migration before applying it.",
            commands=[
                "forge extension cleanup-project",
                "forge extension cleanup-project --yes",
            ],
            console=console,
        )
    if hook_double_fire:
        console.print("  [yellow]Warning:[/yellow] Forge hooks are registered more than once and may fire twice.")
        print_tip(
            "Run the cleanup preview for this project; ambiguous entries remain report-only.",
            commands=["forge extension cleanup-project"],
            console=console,
        )

    console.print("\n[bold]Project registry[/bold]")
    console.print(f"  Path:           {display_path(registry_diag.path)}")
    console.print(f"  Status:         {registry_diag.status}")
    console.print(f"  Enrolled roots: {registry_diag.enrolled_count}")
    if registry_diag.stale_roots:
        console.print("  Stale roots:")
        for root in registry_diag.stale_roots:
            console.print(f"    - {display_path(root)}")
    if registry_diag.error:
        console.print(f"  Error:          {registry_diag.error}")
    if registry_diag.advice:
        print_tip(registry_diag.advice, console=console)

    console.print("\n[bold]Project compatibility[/bold]")
    console.print(f"  Status:         {compat_diag.state}")
    if compat_diag.path:
        console.print(f"  File:           {display_path(compat_diag.path)}")
    if compat_diag.required_forge:
        console.print(f"  Required Forge: {compat_diag.required_forge}")
    console.print(f"  Running Forge:  {compat_diag.running_forge}")
    if compat_diag.reason:
        console.print(f"  Detail:         {compat_diag.reason}")
