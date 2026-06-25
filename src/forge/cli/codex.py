"""`forge codex` command group.

Two leaves: `forge codex status` (read-only enrollment inspection) and `forge codex
start --proxy` (launch the Codex TUI routed through a Responses-capable Forge proxy).
The launcher is sessionless and scrubbed -- the proxy owns upstream auth, so no native
codex/OpenAI login is required or leaked; native-direct Codex is just `codex`.

`status` reports registration facts from a static config read; it never claims
enrollment, which can only be proven by `forge runtime preflight codex
--verify-enrollment`.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import click
from rich.console import Console

from forge.cli.output import print_error, print_error_with_tip
from forge.core.invoker.codex import CodexSandbox
from forge.core.paths import display_path
from forge.core.runtime import get_runtime
from forge.core.runtime.codex_preflight import codex_proxy_contract_blocker
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

_log = logging.getLogger(__name__)

console = Console()
err_console = Console(stderr=True)

_VERIFY_COMMAND = "forge runtime preflight codex --verify-enrollment"


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def codex() -> None:
    """Inspect Codex enrollment and launch Codex through a Forge proxy.

    \b
    forge codex status              # Read-only: binary, config, managed-hook registration
    forge codex start --proxy <id>  # Launch the Codex TUI routed through a Responses proxy
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
    except TrackingCorruptedError as e:
        # Best-effort: codex status reports enrollment, not tracking health, so a
        # corrupt installed.json degrades the supplementary tracked-* fields rather
        # than blocking the read. Surfaced (not silent) per the never-silent rule;
        # 'forge extension status' / 'forge clean' route the same corruption to the
        # uniform reset tip.
        _log.warning("codex status: installed.json unreadable (%s); tracked-* fields omitted", e)
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


@codex.command("start")
@click.option(
    "--proxy",
    "proxy",
    type=str,
    required=True,
    help="Responses-capable proxy to route through (proxy_id or template name)",
)
@click.option(
    "--sandbox",
    type=click.Choice(["read-only", "workspace-write", "danger-full-access"]),
    default="workspace-write",
    show_default=True,
    help="Codex sandbox policy for the launched TUI",
)
@click.argument("codex_args", nargs=-1, type=click.UNPROCESSED)
def start_cmd(proxy: str, sandbox: str, codex_args: tuple[str, ...]) -> None:
    """Launch the Codex TUI routed through a Responses-capable Forge proxy.

    Sessionless and scrubbed: the proxy owns upstream auth, so no native codex/OpenAI
    login is required or leaked. Pass extra codex args after `--` (e.g. `-m` to override
    the proxy's default model).

    \b
    Examples:
        forge codex start --proxy codex-responses-local
        forge codex start --proxy my-proxy --sandbox read-only
        forge codex start --proxy my-proxy -- -m gpt-5.5
    """
    # 1. codex installed? FIRST -- cheap, no side effects, so we never start a proxy the
    #    user can't use.
    runtime = get_runtime("codex")
    if not runtime.is_installed():
        print_error_with_tip(
            "codex CLI not found in PATH.",
            "Install codex >=0.141.0 (the proxy-contract-validated version), then retry.",
            console=err_console,
        )
        sys.exit(1)

    # 2. Hard version gate, BEFORE ensure_proxy: a stale codex must not start a proxy and
    #    then fail cryptically at the first -c override. Unparseable version is allowed
    #    (unknown != provably-old).
    blocker = codex_proxy_contract_blocker(runtime.detect())
    if blocker is not None:
        print_error_with_tip(blocker, "Upgrade codex to >=0.141.0.", console=err_console)
        sys.exit(1)

    # Heavy proxy/invoke imports are deferred so `forge codex status` stays light.
    from forge.proxy.proxies import (
        ProxyNotFoundError,
        ProxyResolutionError,
    )
    from forge.proxy.proxy_orchestrator import (
        ProxyIdentityMismatchError,
        ProxyNotResponsesCapableError,
        ProxyStartError,
        ProxyUnreachableError,
        assert_proxy_responses_capable,
        ensure_proxy,
    )
    from forge.session.codex_invoke import invoke_codex_bare_proxy

    # 3. Resolve + start/adopt the proxy.
    try:
        entry, started = ensure_proxy(proxy)
    except (ProxyResolutionError, ProxyStartError) as e:
        if isinstance(e, ProxyNotFoundError):
            print_error_with_tip(
                str(e),
                "Run 'forge proxy template list' to see available templates.",
                console=err_console,
            )
        else:  # AmbiguousProxyError / ProxyStartError already name their fix
            print_error(str(e), console=err_console)
        sys.exit(1)

    if started:
        console.print(f"[dim]Started proxy '{entry.proxy_id}' from '{proxy}'.[/dim]")

    # 4. Hard Responses-capability gate (also re-checks proxy identity + liveness, since
    #    ensure_proxy resolves an exact proxy_id by registry presence, not liveness). On a
    #    capability/identity failure we leave the proxy running -- it's a static property of
    #    the proxy, so killing it would be user-hostile.
    try:
        # wire_shape is "openai_responses_passthrough" on success (uninformative); the
        # failure path names the actual shape via the exception instead.
        default_model, _ = assert_proxy_responses_capable(
            entry.base_url, expected_proxy_id=entry.proxy_id, expected_template=entry.template
        )
    except ProxyUnreachableError as e:
        print_error_with_tip(
            str(e),
            f"Run 'forge proxy start {entry.proxy_id}' to (re)start it.",
            console=err_console,
        )
        sys.exit(1)
    except ProxyIdentityMismatchError as e:
        print_error_with_tip(
            str(e),
            f"The registry entry for '{entry.proxy_id}' looks stale. "
            f"Run 'forge proxy start {entry.proxy_id}' to re-resolve it.",
            console=err_console,
        )
        sys.exit(1)
    except ProxyNotResponsesCapableError as e:
        print_error_with_tip(
            f"Responses-capable proxy required: proxy '{entry.proxy_id}' ({e}).",
            "Use an openai_responses_passthrough proxy with a responses_ingress source, "
            "or run native 'codex' directly.",
            console=err_console,
        )
        sys.exit(1)

    console.print(
        f"Starting Codex through proxy [green]{entry.proxy_id}[/green] "
        f"({entry.template}, model={default_model or 'proxy default'})"
    )
    sys.exit(
        invoke_codex_bare_proxy(
            base_url=entry.base_url,
            sandbox=cast(CodexSandbox, sandbox),
            model=default_model,
            passthrough=list(codex_args),
        )
    )
