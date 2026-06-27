"""Runtime registry CLI: inspect agent-runtime capabilities (Phase 4e).

``forge runtime list`` renders the capability matrix from ``core/runtime`` -- which
runtimes Forge knows about, whether each is installed, and what it can do (interactive,
headless, hooks, usage source, native resume, install scopes).
"""

from __future__ import annotations

import logging
import sys

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

# Light dataclass import (codex_enrollment defers its heavy invoker/ops graph into
# _run_probe_turn), so the `forge runtime` path stays lean. The verify_codex_enrollment
# *call* is still imported lazily in preflight_cmd (the CLI tests patch the source module).
from forge.core.ops.codex_enrollment import CodexEnrollmentVerification
from forge.core.runtime import (
    CodexPreflight,
    RuntimeSpec,
    list_runtimes,
    preflight_codex,
)

_log = logging.getLogger(__name__)


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
    if result.version_beyond_validated:
        # Non-blocking: the binary may be fine. Codex trust/enrollment + apply_patch/argv
        # facts are pinned empirically, so a version past the probe ceiling means those
        # facts are unverified here -- point the operator at the standing probe harness.
        console.print(
            f"  [yellow]Note:[/yellow] codex {escape(version)} runs ahead of the probe-validated "
            f"{escape(result.version_validated)}; re-run scripts/experiments/codex-hooks/ to re-pin "
            "trust/enrollment behavior."
        )
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


def _render_enrollment(console: Console, result: CodexEnrollmentVerification) -> None:
    """Render an empirical enrollment-verification result (escapes free text)."""
    if result.enrolled is True:
        verdict = "[green]ENROLLED[/green]"
    elif result.enrolled is False:
        verdict = "[red]NOT ENROLLED[/red]"
    else:
        verdict = "[yellow]UNVERIFIED[/yellow]"

    console.print("[bold]Codex hook enrollment[/bold]")
    console.print(f"  Config:     {escape(result.config_path)}")
    console.print(f"  Registered: {'yes' if result.registered else 'no'}")
    console.print(f"  Probe turn: {'ran' if result.attempted else 'skipped (answer already knowable)'}")
    console.print(f"  Enrolled:   {verdict}")
    console.print()
    console.print(escape(result.reason))


@runtime.command("preflight")
@click.argument("runtime_name", metavar="RUNTIME")
@click.option(
    "--proxy",
    "proxy_id",
    default=None,
    metavar="PROXY_ID",
    help="Check Responses support against an existing proxy id (reads proxy.yaml; starts nothing).",
)
@click.option(
    "--verify-enrollment",
    "verify_enrollment",
    is_flag=True,
    help="Empirically confirm user-scope Codex hooks are trust-enrolled (runs one cheap 'codex exec' turn).",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def preflight_cmd(runtime_name: str, proxy_id: str | None, verify_enrollment: bool, as_json: bool) -> None:
    """Preflight a runtime for headless runs: auth, hooks, and Responses readiness.

    Runs the dynamic, per-machine checks the static `forge runtime list` matrix cannot:
    resolves a non-interactive credential, reads `codex doctor`, checks hook state, and
    -- with --proxy -- whether that proxy can serve Codex its Responses API. Exits
    non-zero when the runtime is not ready.

    --verify-enrollment goes further: it confirms (by EFFECT) that Forge's user-scope
    Codex hooks are trust-enrolled, by running one trivial 'codex exec' turn and checking
    whether the SessionStart hook fired. The trust ceremony is unverifiable from a config
    read, so this is the only positive confirmation that it took. Costs one cheap turn.

    \b
    Examples:
        forge runtime preflight codex
        forge runtime preflight codex --json
        forge runtime preflight codex --proxy my-openai-proxy
        forge runtime preflight codex --verify-enrollment
    """
    if runtime_name != "codex":
        # Codex is the only runtime with a preflight today; this is the dispatch seam.
        raise click.BadParameter(
            f"No preflight available for '{runtime_name}' (supported: codex).",
            param_hint="RUNTIME",
        )

    if verify_enrollment:
        from forge.core.ops.codex_enrollment import verify_codex_enrollment

        enrollment_preflight = preflight_codex(proxy_id=proxy_id) if proxy_id is not None else None
        enrollment = verify_codex_enrollment(preflight=enrollment_preflight)
        if as_json:
            import json
            from dataclasses import asdict

            click.echo(json.dumps(asdict(enrollment), indent=2))
        else:
            _render_enrollment(Console(), enrollment)
        # Exit non-zero unless enrollment was positively confirmed (False/None both fail:
        # the operator asked to verify and we could not say yes).
        if enrollment.enrolled is not True:
            sys.exit(1)
        return

    result = preflight_codex(proxy_id=proxy_id)

    # Persist the DIRECT preflight so the supervisor's codex lane (a per-Write/Edit hook)
    # can read readiness without re-running the ~20s doctor probe (epic consumer_lanes, T4).
    # A --proxy run answers a different question (proxied Responses posture), so it must not
    # overwrite the direct cache. Best-effort: a regenerable cache never fails the command.
    if proxy_id is None:
        from forge.core.runtime.codex_preflight_cache import write_codex_preflight_cache

        try:
            write_codex_preflight_cache(result)
        except Exception as e:  # best-effort: a regenerable cache must never fail the command
            _log.warning("Could not write codex preflight cache: %s", e)

    if as_json:
        import json
        from dataclasses import asdict

        click.echo(json.dumps(asdict(result), indent=2))
    else:
        _render_preflight(Console(), result)

    if not result.ready:
        sys.exit(1)
