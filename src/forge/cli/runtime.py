"""Runtime registry CLI: inspect agent-runtime capabilities (Phase 4e).

``forge runtime list`` renders the capability matrix from ``core/runtime`` -- which
runtimes Forge knows about, whether each is installed, and what it can do (interactive,
headless, hooks, usage source, native resume, install scopes).
"""

from __future__ import annotations

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from forge.core.runtime import RuntimeSpec, list_runtimes


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
    # `[features] codex_hooks = true`) that Rich would otherwise eat as markup.
    for s in specs:
        if s.note:
            console.print(f"[dim]{s.id}: {escape(s.note)}[/dim]")
