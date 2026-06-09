"""Runtime registry CLI: inspect agent-runtime capabilities (Phase 4e).

``forge runtime list`` renders the capability matrix from ``core/runtime`` -- which
runtimes Forge knows about, whether each is installed, and what it can do (interactive,
headless, hooks, usage source, native resume, install scopes).
"""

from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from forge.core.runtime import (
    CodexPreflight,
    RuntimeSpec,
    list_runtimes,
    preflight_codex,
)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def runtime() -> None:
    """Inspect agent-runtime capabilities (Claude Code, Codex, Gemini).

    Claude Code is the only launchable frontend today; the Codex and Gemini
    entries describe detected capabilities for follow-up runtime work.

    \b
    Examples:
        forge runtime list           # Capability matrix for all runtimes
        forge runtime list --json    # Machine-readable
    """


def _installed_label(spec: RuntimeSpec) -> str:
    """A version when detectable, else presence-only, else not installed."""
    version = spec.detect()
    if version:
        return version
    return "installed" if spec.is_installed() else "-"


def _spec_dict(spec: RuntimeSpec) -> dict[str, object]:
    """JSON-safe view of a spec (drops the ``detect`` callable; adds resolved version)."""
    return {
        "id": spec.id,
        "display_name": spec.display_name,
        "installed": spec.is_installed(),
        "version": spec.detect(),
        "headless_cmd": list(spec.headless_cmd),
        "interactive": spec.interactive,
        "headless": spec.headless,
        "native_hooks": spec.native_hooks,
        "hook_min_version": spec.hook_min_version,
        "hook_feature_flag": spec.hook_feature_flag,
        "pretool_policy": spec.pretool_policy,
        "usage_source": spec.usage_source,
        "native_resume": spec.native_resume,
        "install_scopes": list(spec.install_scopes),
        "curated_transfer_in": spec.curated_transfer_in,
        "curated_transfer_out": spec.curated_transfer_out,
        "note": spec.note,
    }


@runtime.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_cmd(as_json: bool) -> None:
    """List agent runtimes and their capabilities."""
    console = Console(width=200)
    specs = list_runtimes()

    if as_json:
        import json

        click.echo(json.dumps([_spec_dict(s) for s in specs], indent=2))
        return

    table = Table(title="Forge Runtimes")
    table.add_column("RUNTIME", style="cyan")
    table.add_column("INSTALLED")
    table.add_column("INTERACTIVE")
    table.add_column("HEADLESS")
    table.add_column("HOOKS")
    table.add_column("PRETOOL")
    table.add_column("USAGE")
    table.add_column("RESUME")
    table.add_column("SCOPES")

    for s in specs:
        table.add_row(
            s.id,
            _installed_label(s),
            s.interactive,
            " ".join(s.headless_cmd),
            s.native_hooks,
            s.pretool_policy,
            s.usage_source,
            "yes" if s.native_resume else "no",
            ", ".join(s.install_scopes) or "-",
        )

    console.print(table)
    # Escape note text: a free-text note may contain bracketed tokens (e.g.
    # `[features] hooks`) that Rich would otherwise eat as markup.
    for s in specs:
        if s.note:
            console.print(f"[dim]{s.id}: {escape(s.note)}[/dim]")


def _render_preflight(console: Console, result: CodexPreflight) -> None:
    """Render a CodexPreflight as a labeled report (escapes free-text; carries no secret)."""
    version = result.version or "-"
    floor_met = "yes" if result.version_ok else "no"
    ready = "[green]YES[/green]" if result.ready else "[red]NO[/red]"

    console.print("[bold]Codex preflight[/bold]")
    console.print(f"  Installed:  {'yes' if result.installed else 'no'}")
    console.print(f"  Version:    {escape(version)} (hook floor met: {floor_met})")
    console.print(
        f"  Auth:       {escape(result.auth_method)}  "
        f"(source: {escape(result.auth_source)}, billing: {escape(result.billing_mode)})"
    )
    console.print(f"  Hook seam:  {escape(result.hook_seam)}")
    console.print(f"  Responses:  {escape(result.proxy_responses)}")
    if result.doctor_status:
        console.print(f"  Doctor:     {escape(result.doctor_status)} [dim](informational)[/dim]")
    console.print(f"  Ready:      {ready}")
    if not result.ready and result.blocking_reason:
        console.print()
        console.print(escape(result.blocking_reason))


@runtime.command("preflight")
@click.argument("runtime_name", metavar="RUNTIME")
@click.option(
    "--proxy",
    "proxy_id",
    default=None,
    metavar="PROXY_ID",
    help="Check Responses support against an existing proxy id (reads proxy.yaml; starts nothing).",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def preflight_cmd(runtime_name: str, proxy_id: str | None, as_json: bool) -> None:
    """Preflight a runtime for headless runs: auth, hooks, and Responses readiness.

    Runs the dynamic, per-machine checks the static `forge runtime list` matrix cannot:
    resolves a non-interactive credential, reads `codex doctor`, checks hook state, and
    -- with --proxy -- whether that proxy can serve Codex its Responses API. Exits
    non-zero when the runtime is not ready.

    \b
    Examples:
        forge runtime preflight codex
        forge runtime preflight codex --json
        forge runtime preflight codex --proxy my-openai-proxy
    """
    if runtime_name != "codex":
        # Codex is the only runtime with a preflight today; this is the dispatch seam.
        raise click.BadParameter(
            f"No preflight available for '{runtime_name}' (supported: codex).",
            param_hint="RUNTIME",
        )

    result = preflight_codex(proxy_id=proxy_id)

    if as_json:
        import json
        from dataclasses import asdict

        click.echo(json.dumps(asdict(result), indent=2))
    else:
        _render_preflight(Console(), result)

    if not result.ready:
        sys.exit(1)
