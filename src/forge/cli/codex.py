"""`forge codex` command group.

Read-only Codex inspection (`forge codex status`). The proxy-backed launcher
(`forge codex start --proxy`) is parked until the Responses transport exists
(the forge_codex_command_group card, Phases 2-4); until then `forge codex` is a
single diagnostic leaf and native `codex` remains the direct path.

`status` reports registration facts from a static config read; it never claims
enrollment, which can only be proven by `forge runtime preflight codex
--verify-enrollment`.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path

import click
from rich.console import Console

from forge.core.paths import display_path
from forge.core.runtime import get_runtime
from forge.install.codex_hooks import (
    codex_registration_pairs,
    get_builtin_codex_entries,
    get_codex_config_path,
    read_codex_registration,
)
from forge.install.exceptions import NoForgeInstallationError, TrackingCorruptedError
from forge.install.installer import find_forge_installation
from forge.install.models import InstallScope
from forge.install.tracking import TrackingStore

console = Console()

_VERIFY_COMMAND = "forge runtime preflight codex --verify-enrollment"


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def codex() -> None:
    """Inspect Codex enrollment through Forge.

    \b
    forge codex status   # Read-only: binary, config, managed-hook registration

    The proxy-backed launcher (`forge codex start --proxy`) is parked until the
    Responses transport lands; until then, run native `codex` directly.
    """


# --- status models --------------------------------------------------------


@dataclass(frozen=True)
class _RuntimeInfo:
    id: str
    display_name: str
    installed: bool
    version: str | None


@dataclass(frozen=True)
class _ScopeStatus:
    scope: str
    config_path: str
    config_exists: bool
    block_present: bool
    registered: str  # yes | no | partial | wrong-event
    registered_pairs: list[str]
    commands_registered: list[str]
    tracked_config_path: str | None
    tracked_commands: list[str]


@dataclass(frozen=True)
class _StatusReport:
    runtime: _RuntimeInfo
    scopes: list[_ScopeStatus]
    enrollment: str
    verify_command: str


# --- status computation ---------------------------------------------------


def _runtime_info() -> _RuntimeInfo:
    spec = get_runtime("codex")
    installed = spec.is_installed()
    return _RuntimeInfo(
        id=spec.id,
        display_name=spec.display_name,
        installed=installed,
        version=spec.detect() if installed else None,  # detect() probes `codex --version`
    )


def _enrollment_posture(
    expected: set[tuple[str, str]],
    actual: set[tuple[str, str]],
    commands_registered: tuple[str, ...],
) -> str:
    """Classify static registration as yes/no/partial/wrong-event (no probe).

    `expected` is the builtin (event, command) set; `actual` is the event-aware
    set really in the config; `commands_registered` is the event-agnostic set of
    our commands found anywhere. A command present by name but not under its
    expected event is `wrong-event` (not merely missing).
    """
    if expected <= actual:
        return "yes"
    present_cmds = set(commands_registered)
    if not present_cmds:
        return "no"
    wrong_event = any((ev, cmd) not in actual and cmd in present_cmds for ev, cmd in expected)
    return "wrong-event" if wrong_event else "partial"


def _project_root() -> Path:
    """Resolve the project root for project/local scope.

    Walks up for `.git`/`.codex` so `status` anchors the same project root that
    `forge extension enable` uses (`extensions.py` walks to the git root). A bare
    cwd would miss the per-project `.codex/config.toml` and the scope-keyed
    installed.json record whenever `status` runs from a subdirectory.
    """
    cur = Path.cwd().resolve()
    for parent in (cur, *cur.parents):
        if (parent / ".git").exists() or (parent / ".codex").exists():
            return parent
    return cur


def _resolve_targets(
    scope: str | None, show_all: bool, tracking: TrackingStore | None
) -> list[tuple[InstallScope, Path | None]]:
    """Resolve which (scope, project_root) pairs `status` inspects.

    Default mirrors the card: the detected Forge install scope when one is known,
    else user. PROJECT and LOCAL share the per-project config path but keep
    distinct installed.json keys, so `--all` lists both.
    """
    if show_all:
        root = _project_root()
        return [
            (InstallScope.USER, None),
            (InstallScope.PROJECT, root),
            (InstallScope.LOCAL, root),
        ]
    if scope is not None:
        target = InstallScope(scope)
        return [(target, None if target == InstallScope.USER else _project_root())]
    # Default: detected install scope (find_forge_installation re-reads tracking,
    # so skip it when the store is corrupt and fall back to user).
    if tracking is not None:
        try:
            detected, detected_root = find_forge_installation(tracking=tracking)
            return [(detected, detected_root)]
        except NoForgeInstallationError:
            pass
    return [(InstallScope.USER, None)]


def _scope_status(scope: InstallScope, project_root: Path | None, tracking: TrackingStore | None) -> _ScopeStatus:
    config_path = get_codex_config_path(scope, project_root)
    entries = get_builtin_codex_entries()
    registration = read_codex_registration(config_path, entries)
    actual = codex_registration_pairs(config_path)
    expected = {(e.event, e.command) for e in entries}
    forge_commands = {e.command for e in entries}

    tracked_path: str | None = None
    tracked_commands: list[str] = []
    if tracking is not None:
        project_path = None if project_root is None else str(project_root)
        installation = tracking.get_installation(scope.value, project_path)
        if installation is not None:
            tracked_path = installation.codex_config_path
            tracked_commands = list(installation.codex_commands)

    return _ScopeStatus(
        scope=scope.value,
        config_path=display_path(config_path),
        config_exists=config_path.exists(),
        block_present=registration.block_present,
        registered=_enrollment_posture(expected, actual, registration.commands_registered),
        # Forge footprint only: unrelated user hooks in the same config are not ours to report.
        registered_pairs=sorted(f"{ev} -> {cmd}" for ev, cmd in actual if cmd in forge_commands),
        commands_registered=list(registration.commands_registered),
        tracked_config_path=display_path(tracked_path) if tracked_path else None,
        tracked_commands=tracked_commands,
    )


def _build_report(scope: str | None, show_all: bool) -> _StatusReport:
    # installed.json tracking is supplementary; a corrupt store degrades the
    # tracked-* fields (and scope detection) rather than failing the read.
    store = TrackingStore()
    tracking: TrackingStore | None
    try:
        store.read()
        tracking = store
    except TrackingCorruptedError:
        tracking = None
    targets = _resolve_targets(scope, show_all, tracking)
    return _StatusReport(
        runtime=_runtime_info(),
        scopes=[_scope_status(s, root, tracking) for s, root in targets],
        enrollment="unverified by static read",
        verify_command=_VERIFY_COMMAND,
    )


def _render_human(report: _StatusReport) -> None:
    rt = report.runtime
    console.print("[bold]Codex runtime[/bold]")
    if rt.installed:
        console.print(f"  Installed: [green]yes[/green]  ({rt.version or 'unknown'})")
    else:
        console.print("  Installed: [dim]no[/dim]")

    for sc in report.scopes:
        console.print()
        console.print(f"[bold]Scope:[/bold] {sc.scope}  ([dim]{sc.config_path}[/dim])")
        if not sc.config_exists:
            console.print("  Config: [dim]not found[/dim]")
        else:
            console.print("  Config: present")
            console.print(f"  Managed block: {'yes' if sc.block_present else 'no'}")
        console.print(f"  Registered: {sc.registered}")
        for pair in sc.registered_pairs:
            console.print(f"    {pair}")
        if sc.tracked_commands:
            console.print(f"  Tracked (installed.json): {', '.join(sc.tracked_commands)}")

    console.print()
    console.print(f"[bold]Enrollment:[/bold] {report.enrollment}")
    console.print(f"  Verify: {report.verify_command}")


# --- commands -------------------------------------------------------------


@codex.command("status")
@click.option(
    "--scope",
    "-S",
    type=click.Choice(["user", "project", "local"]),
    default=None,
    help="Codex config scope to inspect (default: detected install scope, else user)",
)
@click.option("--all", "-a", "show_all", is_flag=True, help="Inspect every scope")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status_cmd(scope: str | None, show_all: bool, as_json: bool) -> None:
    """Show Codex binary, config, and Forge hook registration (read-only).

    Reports registration facts from a static config read; it never claims
    enrollment. Verify enrollment empirically with
    'forge runtime preflight codex --verify-enrollment'.
    """
    if show_all and scope is not None:
        raise click.UsageError("--all and --scope are mutually exclusive.")

    report = _build_report(scope, show_all)

    if as_json:
        click.echo(json.dumps(dataclasses.asdict(report), indent=2))
        return

    _render_human(report)
