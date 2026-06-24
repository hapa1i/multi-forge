"""Policy CLI commands for policy management.

Commands for managing policy enforcement:
- enable: Enable policy bundles for the current session
- disable: Disable policy enforcement
- status: Show current policy configuration and state
- check: Evaluate policies on demand against a file or diff
- supervisor: Configure/run the semantic plan supervisor
  ({status, set, off, on, remove, reload, cascade, evaluate})
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from forge.cli.output import print_error_with_tip, print_tip
from forge.core.effort import CLAUDE_EFFORT_LEVELS
from forge.core.llm.types import REASONING_EFFORT_LEVELS
from forge.core.paths import display_path
from forge.policy.queries import (
    find_sessions_supervised_by,
    read_scoped_supervisor_target,
)
from forge.policy.semantic.supervisor import (
    CHECKER_PROVIDER_CHOICES,
    apply_checker_options,
    validate_checker_model,
)
from forge.session import SessionStore
from forge.session.effective import compute_effective_intent
from forge.session.exceptions import AmbiguousSessionError, ForgeSessionError
from forge.session.hooks.session_start import ENV_SESSION
from forge.session.models import PolicyIntent, SessionState, SupervisorConfig
from forge.session.store import HOOK_LOCK_TIMEOUT_S, MANIFEST_FILENAME, get_sessions_dir

console = Console()

# Click wrappers over the shared (Click-free) vocabularies. Checker effort uses the
# core.llm ReasoningEffort set (the tier-1 checker is a core.llm call); supervisor effort
# uses the claude --effort set (the frontier is a claude -p subprocess).
_CHECKER_PROVIDER_CHOICES = click.Choice(list(CHECKER_PROVIDER_CHOICES))
_CHECKER_EFFORT_CHOICES = click.Choice(list(REASONING_EFFORT_LEVELS))
_SUPERVISOR_EFFORT_CHOICES = click.Choice(list(CLAUDE_EFFORT_LEVELS))


def _checker_display(sup: SupervisorConfig) -> tuple[str, str, int]:
    from forge.policy.semantic.plan_check import (
        DEFAULT_PLAN_CHECK_BUDGET_TOKENS,
        resolve_plan_check_route,
    )

    budget = (
        max(1, int(sup.checker_budget_tokens))
        if sup.checker_budget_tokens is not None
        else DEFAULT_PLAN_CHECK_BUDGET_TOKENS
    )

    try:
        route = resolve_plan_check_route(sup)
    except ValueError:
        provider = sup.checker_provider or "auto"
        return (
            f"{provider} (unsupported)",
            sup.checker_model or "unresolved",
            budget,
        )

    return (
        route.provider or "auto",
        route.model,
        budget,
    )


def _list_local_sessions(cwd: Path) -> list[str]:
    """Return sorted names of sessions with a manifest in the local forge_root."""
    sessions_dir = get_sessions_dir(_resolve_forge_root(cwd))
    if not sessions_dir.is_dir():
        return []
    return sorted(d.name for d in sessions_dir.iterdir() if d.is_dir() and (d / MANIFEST_FILENAME).exists())


def _resolve_forge_root(cwd: Path) -> str:
    """Resolve forge_root from CWD (falls back to CWD itself)."""
    try:
        from forge.core.ops.context import find_forge_root

        fr = find_forge_root(cwd)
        return str(fr) if fr else str(cwd)
    except Exception:
        return str(cwd)


def _resolve_session_for_display(
    name: str,
    cwd: Path,
) -> tuple[SessionStore, SessionState]:
    """Resolve a named session, workspace-scoped with current-project preference.

    Delegates to the shared two-tier resolver in core.ops.resolution.
    """
    from forge.core.ops.resolution import resolve_session_repo_wide

    resolved = resolve_session_repo_wide(name, _resolve_forge_root(cwd))
    return resolved.store, resolved.state


def _resolve_policy_session(cwd: Path, explicit: str | None) -> tuple[SessionStore, SessionState]:
    """Resolve the policy target session as (store, state), or exit(1) with an actionable error.

    Precedence: explicit --session > FORGE_SESSION > sole local session. The absent case
    (zero local sessions) and the ambiguous case (multiple, none selected) produce distinct
    messages so the caller isn't told "No session found" when several exist.
    """
    if explicit:
        try:
            return _resolve_session_for_display(explicit, cwd)
        except AmbiguousSessionError as exc:
            console.print(f"[red]Error:[/red] Session '{explicit}' exists in multiple projects:")
            for root in exc.forge_roots:
                console.print(Text(f"  - {display_path(root)}", style="dim", no_wrap=True), soft_wrap=True)
            console.print("[dim]Run the command from the target project directory.[/dim]")
            sys.exit(1)
        except ForgeSessionError as exc:
            console.print(f"[red]Error:[/red] Session '{explicit}' not found: {exc}")
            sys.exit(1)

    name = os.environ.get(ENV_SESSION)
    if not name:
        candidates = _list_local_sessions(cwd)
        if len(candidates) == 1:
            name = candidates[0]
        elif not candidates:
            console.print(f"[red]Error:[/red] No session found in {display_path(cwd)}")
            console.print("  Run 'forge session start' first to create a session.")
            sys.exit(1)
        else:
            console.print(f"[red]Error:[/red] Multiple sessions in {display_path(cwd)}; specify one with --session.")
            console.print("  Sessions: " + ", ".join(candidates))
            print_tip(f"Run 'forge policy <command> --session {candidates[0]}'.", blank_before=False, console=console)
            sys.exit(1)

    store = SessionStore(_resolve_forge_root(cwd), name)
    try:
        state = store.read()
    except Exception:
        console.print(f"[red]Error:[/red] No session found in {display_path(cwd)}")
        console.print("  Run 'forge session start' first to create a session.")
        sys.exit(1)
    return store, state


@click.group()
def policy() -> None:
    """Manage policy enforcement for the current session.

    \b
    Examples:
        forge policy enable --bundle tdd        # Enable TDD policy
        forge policy status                     # Show policy state
        forge policy check --bundle tdd -f src/foo.py  # On-demand check
    """
    pass


@policy.command(name="list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_bundles(as_json: bool) -> None:
    """List available policy bundles and their rules."""
    from forge.policy.deterministic.registry import BUNDLES, get_bundle_policies

    if as_json:
        import json

        data = []
        for bundle_name in sorted(BUNDLES):
            policies = get_bundle_policies(bundle_name)
            data.append(
                {
                    "name": bundle_name,
                    "policies": [
                        {"policy_id": p.policy_id, "description": getattr(p, "description", None)} for p in policies
                    ],
                }
            )
        click.echo(json.dumps(data, indent=2, default=str))
        return

    for bundle_name in sorted(BUNDLES):
        policies = get_bundle_policies(bundle_name)
        console.print(f"[bold cyan]{bundle_name}[/bold cyan]")
        for p in policies:
            console.print(f"  {p.policy_id}")
            if hasattr(p, "description") and p.description:
                console.print(f"    [dim]{p.description}[/dim]")
        console.print()


@policy.command(name="enable")
@click.option(
    "--bundle",
    "-b",
    "bundles",
    multiple=True,
    type=click.Choice(["tdd", "coding_standards"]),
    help="Policy bundles to enable (can be repeated)",
)
@click.option(
    "--fail-mode",
    type=click.Choice(["open", "closed"]),
    default="open",
    help="Behavior on policy errors (default: open)",
)
@click.option(
    "--permissive",
    is_flag=True,
    default=False,
    help="TDD permissive mode: warn instead of deny (sets bundle_config.tdd.strict=false)",
)
@click.option("--session", "-s", "session_name", help="Target session (default: auto-detect)")
def enable(bundles: tuple[str, ...], fail_mode: str, permissive: bool, session_name: str | None) -> None:
    """Enable policy enforcement for the current session.

    \b
    Examples:
        forge policy enable --bundle tdd --bundle coding_standards
        forge policy enable --bundle tdd --permissive
    """
    if not bundles:
        console.print("[yellow]Warning:[/yellow] No bundles specified. Use --bundle to enable policies.")
        console.print("Available bundles: tdd, coding_standards")
        return

    cwd = Path.cwd().resolve()
    store, _ = _resolve_policy_session(cwd, session_name)

    bundle_config: dict[str, dict[str, object]] = {}
    if permissive and "tdd" in bundles:
        bundle_config["tdd"] = {"strict": False}

    def _mutate(m: object) -> None:
        if not isinstance(m, SessionState):
            raise TypeError(f"Expected SessionState, got {type(m)}")

        m.intent.policy = PolicyIntent(
            enabled=True,
            fail_mode=fail_mode,  # type: ignore[arg-type]  # click Choice returns str, not Literal
            bundles=list(bundles),
            bundle_config=bundle_config,
        )

    try:
        store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_mutate)
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to update session: {e}")
        sys.exit(1)

    console.print(f"[green]Policy enabled[/green] with bundles: {', '.join(bundles)}")
    console.print(f"  Fail mode: {fail_mode}")

    from forge.install.hooks import has_forge_hook

    if not has_forge_hook(cwd, "PreToolUse", "forge hook policy-check"):
        console.print(
            "\n[yellow]Warning:[/yellow] Policy configured but PreToolUse hook is not installed. "
            "Enforcement will not be active."
        )
        print_tip("Run 'forge extension enable' to install hooks.", blank_before=False, console=console)
    if bundle_config:
        for bundle, cfg in bundle_config.items():
            cfg_str = ", ".join(f"{k}={v}" for k, v in cfg.items())
            console.print(f"  {bundle}: {cfg_str}")

    from forge.policy.deterministic.registry import get_policy_ids_for_bundle

    rules = []
    for bundle in bundles:
        rules.extend(get_policy_ids_for_bundle(bundle))

    if rules:
        console.print("  Active rules:")
        for rule in rules:
            console.print(f"    - {rule}")


@policy.command(name="disable")
@click.option("--session", "-s", "session_name", help="Target session (default: auto-detect)")
def disable(session_name: str | None) -> None:
    """Disable policy enforcement for the current session."""
    cwd = Path.cwd().resolve()
    store, _ = _resolve_policy_session(cwd, session_name)

    def _mutate(m: object) -> None:
        if not isinstance(m, SessionState):
            raise TypeError(f"Expected SessionState, got {type(m)}")

        if m.intent.policy:
            m.intent.policy.enabled = False
        else:
            m.intent.policy = PolicyIntent(enabled=False)

    try:
        store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_mutate)
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to update session: {e}")
        sys.exit(1)

    console.print("[green]Policy enforcement disabled[/green]")


def _supervisor_status_dict(sup: SupervisorConfig | None, manifest: SessionState) -> dict[str, object] | None:
    """Build the canonical supervisor JSON dict.

    Shared by `policy status --json` and `policy supervisor status --json` so there is
    exactly one supervisor JSON shape. Returns None when no supervisor is configured.
    """
    if not sup:
        return None
    data: dict[str, object] = {
        "resume_id": sup.resume_id,
        "suspended": sup.suspended,
        "plan_override_path": sup.plan_override_path,
        "proxy": sup.proxy,
        "direct": sup.direct,
        "fork_session": sup.fork_session,
        "timeout_seconds": sup.timeout_seconds,
        "throttle_seconds": sup.throttle_seconds,
        "cascade": sup.cascade,
        "checker_model": sup.checker_model,
        "checker_provider": sup.checker_provider,
        "checker_budget_tokens": sup.checker_budget_tokens,
        "checker_effort": sup.checker_effort,
        "supervisor_effort": sup.supervisor_effort,
        "resolved_uuid": None,
        "source_model": None,
    }
    if sup.resume_id:
        ts = read_scoped_supervisor_target(sup.resume_id, sup.forge_root, manifest.forge_root)
        if ts is not None:
            data["resolved_uuid"] = ts.confirmed.claude_session_id
            swp = ts.confirmed.started_with_proxy
            if swp and swp.template:
                data["source_model"] = swp.template
    return data


@policy.command(name="status")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--session", "-s", "session_name", help="Target session (default: auto-detect)")
def status(as_json: bool, session_name: str | None) -> None:
    """Show current policy configuration and state."""
    cwd = Path.cwd().resolve()
    _, manifest = _resolve_policy_session(cwd, session_name)

    try:
        effective = compute_effective_intent(manifest)
    except Exception as exc:
        console.print(f"[red]Error:[/red] Failed to compute effective config: {exc}")
        sys.exit(1)

    if as_json:
        import json

        policy_data: dict[str, object] = {"session_name": manifest.name}
        if effective.policy:
            sup_data = _supervisor_status_dict(effective.policy.supervisor, manifest)
            policy_data["policy"] = {
                "enabled": effective.policy.enabled,
                "fail_mode": effective.policy.fail_mode or "open",
                "bundles": effective.policy.bundles or [],
                "bundle_config": effective.policy.bundle_config or {},
                "supervisor": sup_data,
            }
        else:
            policy_data["policy"] = None

        confirmed_policy = manifest.confirmed.policy
        if confirmed_policy:
            policy_data["confirmed"] = {
                "decisions_count": len(confirmed_policy.decisions or []),
                "policy_states_count": len(confirmed_policy.policy_states or {}),
            }
        else:
            policy_data["confirmed"] = None

        supervised = find_sessions_supervised_by(
            manifest.name, manifest.confirmed.claude_session_id, manifest.forge_root
        )
        if supervised:
            policy_data["supervised_sessions"] = supervised

        click.echo(json.dumps(policy_data, indent=2, default=str))
        return

    table = Table(title=f"Policy Status: {manifest.name}", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")

    if effective.policy:
        table.add_row("Enabled", "Yes" if effective.policy.enabled else "No")
        table.add_row("Fail Mode", effective.policy.fail_mode or "open")
        table.add_row(
            "Bundles",
            ", ".join(effective.policy.bundles) if effective.policy.bundles else "None",
        )
        if effective.policy.bundle_config:
            for bundle, cfg in effective.policy.bundle_config.items():
                cfg_str = ", ".join(f"{k}={v}" for k, v in cfg.items())
                table.add_row(f"  {bundle}", cfg_str)

        if effective.policy.supervisor:
            sup = effective.policy.supervisor
            status = "Suspended" if sup.suspended else "Configured"
            table.add_row("Supervisor", status)
            if sup.resume_id:
                table.add_row("  Target", sup.resume_id)
                ts = read_scoped_supervisor_target(sup.resume_id, sup.forge_root, manifest.forge_root)
                if ts is not None:
                    uuid = ts.confirmed.claude_session_id
                    if uuid:
                        table.add_row("  Claude UUID", uuid[:16] + "...")
                    swp = ts.confirmed.started_with_proxy
                    if swp and swp.template:
                        table.add_row("  Source model", swp.template)
            if sup.proxy:
                table.add_row("  Routing", f"proxy: {sup.proxy}")
            elif sup.direct:
                table.add_row("  Routing", "direct (no proxy)")
            table.add_row("  Fork session", "Yes" if sup.fork_session else "No")
            table.add_row("  Timeout", f"{sup.timeout_seconds}s")
            table.add_row("  Throttle", f"{sup.throttle_seconds}s")
            if sup.supervisor_effort:
                table.add_row("  Supervisor effort", sup.supervisor_effort)
            table.add_row("  Cascade", "On" if sup.cascade else "Off")
            if sup.cascade:
                checker_provider, checker_model, checker_budget = _checker_display(sup)

                table.add_row("  Checker provider", checker_provider)
                table.add_row("  Checker model", checker_model)
                table.add_row("  Checker budget", f"{checker_budget} tokens")
                if sup.checker_effort:
                    table.add_row("  Checker effort", sup.checker_effort)
            if sup.plan_override_path:
                table.add_row("  Plan override", sup.plan_override_path)
        else:
            table.add_row("Supervisor", "Not configured")
    else:
        table.add_row("Enabled", "No (not configured)")

    console.print(table)

    if manifest.confirmed.policy:
        confirmed = manifest.confirmed.policy
        console.print()
        state_table = Table(title="Policy State (from hooks)", show_header=False)
        state_table.add_column("Key", style="cyan")
        state_table.add_column("Value")

        state_table.add_row("Decisions Logged", str(len(confirmed.decisions or [])))
        state_table.add_row("Policy States", str(len(confirmed.policy_states or {})))

        console.print(state_table)

        if confirmed.policy_states:
            for policy_id, state in confirmed.policy_states.items():
                items = ", ".join(f"{k}: {len(v) if isinstance(v, (list, dict)) else v}" for k, v in state.items())
                console.print(f"  [dim]{policy_id}[/dim]: {items}")

    # Supervised-sessions tip (always, not gated on "no supervisor" — chains are valid)
    supervised = find_sessions_supervised_by(manifest.name, manifest.confirmed.claude_session_id, manifest.forge_root)
    if supervised:
        names = ", ".join(supervised)
        print_tip(
            f"This session supervises: {names}. Run 'forge policy status --session {supervised[0]}' to check.",
            console=console,
        )


_DIFF_PATH_RE = re.compile(r"^\+\+\+ b/(.+?)(?:\t.*)?$", re.MULTILINE)


def _extract_path_from_diff(diff: str) -> str | None:
    """Extract the first file path from a unified diff.

    Parses ``+++ b/<path>`` lines, stripping trailing tab-delimited
    metadata (timestamps, etc.). Returns None if no path found.
    """
    m = _DIFF_PATH_RE.search(diff)
    if m:
        path = m.group(1).strip()
        return path if path and path != "/dev/null" else None
    return None


@policy.command(name="check")
@click.option(
    "--bundle",
    "-b",
    "bundles",
    multiple=True,
    required=True,
    type=click.Choice(["tdd", "coding_standards"]),
    help="Policy bundles to evaluate (can be repeated)",
)
@click.option(
    "--file",
    "-f",
    "file_path",
    type=click.Path(exists=True),
    help="File to evaluate policies against",
)
@click.option(
    "--diff",
    "use_diff",
    is_flag=True,
    help="Read git diff from stdin",
)
@click.option(
    "--fail-mode",
    type=click.Choice(["open", "closed"]),
    default="closed",
    help="Behavior on policy errors (default: closed for on-demand checks)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output structured JSON",
)
def check(
    bundles: tuple[str, ...],
    file_path: str | None,
    use_diff: bool,
    fail_mode: str,
    as_json: bool,
) -> None:
    """Evaluate policies on demand against a file or diff.

    Unlike hook-triggered checks, this runs explicitly and defaults to
    fail-mode=closed (violations are reported, not swallowed).

    \b
    Examples:
        forge policy check --bundle tdd --file src/foo.py
        forge policy check --bundle tdd --bundle coding_standards -f src/foo.py --json
        git diff | forge policy check --bundle coding_standards --diff
    """
    from forge.policy.engine import build_engine
    from forge.policy.types import ActionContext, extract_added_lines

    if not file_path and not use_diff:
        console.print("[red]Error:[/red] Provide --file or --diff")
        sys.exit(2)

    cwd = Path.cwd().resolve()

    if use_diff:
        if sys.stdin.isatty():
            console.print("[red]Error:[/red] --diff requires input on stdin (e.g., git diff | forge policy check ...)")
            sys.exit(2)
        raw_input = sys.stdin.read()
        tool_name = "Edit"
        target_path = _extract_path_from_diff(raw_input)
        new_content = extract_added_lines(raw_input)
    else:
        assert file_path is not None
        target = Path(file_path)
        try:
            raw_input = target.read_text()
        except Exception as e:
            console.print(f"[red]Error:[/red] Failed to read {display_path(file_path)}: {e}")
            sys.exit(2)
        tool_name = "Write"
        new_content = raw_input
        try:
            target_path = str(target.resolve().relative_to(cwd))
        except ValueError:
            target_path = str(target)

    context = ActionContext(
        origin="forge_cli",
        event="OnDemand.Check",
        tool_name=tool_name,
        tool_args={"file_path": file_path or "", "content": new_content[:200]},
        repo_root=str(cwd),
        session_name="on-demand",
        target_path=target_path,
        new_content=new_content[:5000] if new_content else None,
        raw_diff=raw_input[:5000] if use_diff and raw_input else None,
    )

    try:
        engine = build_engine(list(bundles), fail_mode=fail_mode)  # type: ignore[arg-type]
        result = engine.evaluate(context)
    except Exception as e:
        if as_json:
            click.echo(json.dumps({"error": str(e), "passed": False}))
        else:
            console.print(f"[red]Error:[/red] Policy evaluation failed: {e}")
        sys.exit(2)

    # Determine exit code: allow and warn both exit 0 (warn = advisory)
    passed = result.final_decision in ("allow", "warn")
    exit_code = 0 if passed else 1

    if as_json:
        # Build violations with intent from their parent decisions
        violations_json = []
        for d in result.decisions:
            if d.decision != "deny":
                continue
            for v in d.violations:
                entry: dict[str, str | None] = {
                    "rule_id": v.rule_id,
                    "message": v.message,
                    "severity": v.severity,
                    "suggested_fix": v.suggested_fix,
                }
                if d.intent:
                    entry["intent"] = d.intent
                violations_json.append(entry)
        output = {
            "passed": passed,
            "clean": result.final_decision == "allow",
            "final_decision": result.final_decision,
            "violations": violations_json,
            "warnings": result.all_warnings,
            "policies_evaluated": [d.policy_id for d in result.decisions],
        }
        click.echo(json.dumps(output, indent=2))
    else:
        if result.final_decision == "allow":
            console.print("[green]All policies passed[/green]")
        elif result.final_decision == "warn":
            console.print("[yellow]Passed with warnings[/yellow]")
            for w in result.all_warnings:
                console.print(f"  ⚠︎ {w}", style="yellow")
        else:
            console.print(f"[red]Policy check failed ({result.final_decision})[/red]")
            for d in result.decisions:
                if d.decision != "deny":
                    continue
                table = Table(show_header=True)
                table.add_column("Rule", style="cyan")
                table.add_column("Severity", style="red")
                table.add_column("Message")
                table.add_column("Fix", style="dim")
                for v in d.violations:
                    table.add_row(v.rule_id, v.severity, v.message, v.suggested_fix or "")
                if d.intent:
                    table.add_row("", "", f"[dim]Intent: {d.intent}[/dim]", "")
                console.print(table)

        if result.all_warnings and result.final_decision != "warn":
            for w in result.all_warnings:
                console.print(f"  [dim]⚠︎ {w}[/dim]")

    sys.exit(exit_code)


# Prefixes that invoke_supervisor() uses in warnings when it fails open.
# Used by the CLI to convert allow→exit(2).
_INFRA_FAILURE_PREFIXES = ("Supervisor error:", "Supervisor skipped")


@policy.group(name="supervisor")
def supervisor() -> None:
    """Configure and run the semantic plan supervisor for the current session.

    \b
    Examples:
        forge policy supervisor set planner                      # Set planner as supervisor
        forge policy supervisor status                           # Show supervisor config
        forge policy supervisor off                              # Suspend (preserves config)
        forge policy supervisor evaluate -f src/foo.py -r planner  # One-shot file-vs-plan check
    """


def _session_option(f: Any) -> Any:
    """Attach the shared --session/-s option used by every supervisor leaf."""
    return click.option("--session", "-s", "session_name", help="Target session (default: auto-detect)")(f)


def _resolve_supervisor_session(session_name: str | None) -> tuple[SessionStore, str, SessionState]:
    """Resolve the policy session; return (store, display_name, fresh manifest)."""
    cwd = Path.cwd().resolve()
    store, state = _resolve_policy_session(cwd, session_name)
    return store, state.name, store.read()


@supervisor.command(name="evaluate")
@click.option(
    "--file",
    "-f",
    "file_path",
    type=click.Path(exists=True),
    required=True,
    help="File to evaluate against the plan",
)
@click.option(
    "--resume-id",
    "-r",
    required=True,
    help="Claude session UUID for --resume, or a Forge session name to resolve",
)
@click.option(
    "--proxy",
    "proxy_name",
    type=str,
    default=None,
    help="Proxy (proxy_id or template name) for base_url resolution",
)
@click.option("--no-proxy", "direct", is_flag=True, default=False, help="Force direct Anthropic routing (bypass proxy)")
@click.option(
    "--timeout",
    "-t",
    type=int,
    default=45,
    help="Supervisor timeout in seconds (default: 45)",
)
@click.option(
    "--supervisor-effort",
    "supervisor_effort",
    type=_SUPERVISOR_EFFORT_CHOICES,
    default=None,
    help="Supervisor reasoning effort (claude --effort: low/medium/high/xhigh/max)",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Output structured JSON",
)
def supervisor_evaluate(
    file_path: str,
    resume_id: str,
    proxy_name: str | None,
    direct: bool,
    timeout: int,
    supervisor_effort: str | None,
    as_json: bool,
) -> None:
    """Evaluate a single file against a supervisor plan (one-shot).

    For persistent supervisor configuration, use 'forge policy supervisor set' instead.

    Fail-closed: exit 0 (aligned), exit 1 (divergent), exit 2 (could not evaluate).

    \b
    Examples:
        forge policy supervisor evaluate -f src/foo.py -r abc-123 --json
        forge policy supervisor evaluate -f src/foo.py -r planning-session --json
        forge policy supervisor evaluate -f src/foo.py -r abc-123 --proxy openrouter-openai
        forge policy supervisor evaluate -f src/foo.py -r abc-123 --no-proxy
    """
    if direct and proxy_name:
        console.print("[red]Error:[/red] --no-proxy and --proxy are mutually exclusive")
        sys.exit(1)

    from forge.policy.semantic.supervisor import SUPERVISOR_INTENT, invoke_supervisor
    from forge.policy.types import ActionContext
    from forge.session.models import SupervisorConfig

    target = Path(file_path)
    try:
        file_content = target.read_text()
    except Exception as e:
        if as_json:
            click.echo(json.dumps({"error": str(e), "passed": False}))
        else:
            console.print(f"[red]Error:[/red] Failed to read {display_path(file_path)}: {e}")
        sys.exit(2)

    cwd = Path.cwd().resolve()
    try:
        target_path = str(target.resolve().relative_to(cwd))
    except ValueError:
        target_path = str(target)

    config = SupervisorConfig(
        resume_id=resume_id,
        proxy=proxy_name,
        direct=direct,
        timeout_seconds=timeout,
        supervisor_effort=supervisor_effort,
        fork_session=True,
    )

    context = ActionContext(
        origin="forge_cli",
        event="OnDemand.Supervisor",
        tool_name="Write",
        tool_args={"file_path": file_path, "content": file_content[:200]},
        repo_root=str(cwd),
        session_name="on-demand",
        target_path=target_path,
        new_content=file_content[:5000],
    )

    try:
        decision = invoke_supervisor(config, context, intent=SUPERVISOR_INTENT)
    except Exception as e:
        if as_json:
            click.echo(json.dumps({"error": str(e), "passed": False}))
        else:
            console.print(f"[red]Error:[/red] Supervisor invocation failed: {e}")
        sys.exit(2)

    # Detect infra failures hidden behind fail-open allow decisions
    infra_failure = decision.decision == "allow" and any(
        w.startswith(prefix) for w in (decision.warnings or []) for prefix in _INFRA_FAILURE_PREFIXES
    )

    if infra_failure:
        passed = False
        exit_code = 2
    elif decision.decision == "deny":
        passed = False
        exit_code = 1
    else:
        passed = True
        exit_code = 0

    if as_json:
        violations_list = []
        for v in decision.violations:
            v_entry: dict[str, str | None] = {
                "rule_id": v.rule_id,
                "severity": v.severity,
                "message": v.message,
                "evidence": v.evidence,
                "suggested_fix": v.suggested_fix,
            }
            if decision.intent:
                v_entry["intent"] = decision.intent
            violations_list.append(v_entry)
        output = {
            "passed": passed,
            "clean": decision.decision == "allow" and not infra_failure,
            "final_decision": decision.decision if not infra_failure else "error",
            "policy_id": decision.policy_id,
            "violations": violations_list,
            "warnings": decision.warnings or [],
        }
        click.echo(json.dumps(output, indent=2))
    else:
        if exit_code == 0:
            if decision.decision == "allow":
                console.print("[green]Aligned with plan[/green]")
            else:
                console.print("[yellow]Aligned with warnings[/yellow]")
                for w in decision.warnings or []:
                    console.print(f"  ⚠︎ {w}", style="yellow")
        elif exit_code == 1:
            console.print("[red]Divergent from plan[/red]")
            for w in decision.warnings or []:
                console.print(f"  [red]{w}[/red]")
        else:
            console.print("[red]Could not evaluate[/red]")
            for w in decision.warnings or []:
                console.print(f"  [dim]{w}[/dim]")

    sys.exit(exit_code)


def _resolve_cascade_plan(sup_config: SupervisorConfig, manifest: SessionState) -> tuple[str, str]:
    """Resolve the approved-plan snapshot the cascade's tier-1 checker will read.

    Returns (plan_path, source_description). Exits 1 with a tip when no approved
    snapshot is resolvable -- before any manifest mutation.
    """
    from forge.policy.semantic.supervisor import resolve_supervisor_reload_plan_path

    result = resolve_supervisor_reload_plan_path(sup_config, manifest)
    if result is None:
        print_error_with_tip(
            "No approved plan snapshot found for the cascade's tier-1 checker.",
            "Approve a plan (ExitPlanMode) in the planning session, or run "
            "'forge policy supervisor reload --from <path>' to set one explicitly, then retry.",
            console=console,
        )
        sys.exit(1)
    source_map = {
        "self": "current session",
        "fork": f"review fork '{result.session_name}'",
        "target": "supervisor target",
    }
    return result.path, source_map.get(result.source, result.source)


@supervisor.command(name="status")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@_session_option
def supervisor_status(as_json: bool, session_name: str | None) -> None:
    """Show the current supervisor configuration."""
    cwd = Path.cwd().resolve()
    _, manifest = _resolve_policy_session(cwd, session_name)
    try:
        effective = compute_effective_intent(manifest)
    except Exception as exc:
        console.print(f"[red]Error:[/red] Failed to compute effective config: {exc}")
        sys.exit(1)

    sup = effective.policy.supervisor if effective.policy else None

    if as_json:
        click.echo(
            json.dumps(
                {"session_name": manifest.name, "supervisor": _supervisor_status_dict(sup, manifest)},
                indent=2,
                default=str,
            )
        )
        return

    if not (sup and sup.resume_id):
        console.print("No supervisor configured.")
        return

    console.print(f"Supervisor: [green]{sup.resume_id}[/green]")
    if sup.suspended:
        console.print("  Status: [yellow]suspended[/yellow]")

    target_state = read_scoped_supervisor_target(sup.resume_id, sup.forge_root, manifest.forge_root)
    if target_state is not None:
        uuid = target_state.confirmed.claude_session_id
        if uuid:
            console.print(f"  Claude UUID: {uuid[:16]}...")
        swp = target_state.confirmed.started_with_proxy
        if swp and swp.template:
            console.print(f"  Source model: {swp.template}")

    if sup.proxy:
        console.print(f"  Routing: proxy: {sup.proxy}")
    elif sup.direct:
        console.print("  Routing: direct (no proxy)")
    console.print(f"  Fork session: {'yes' if sup.fork_session else 'no'}")
    console.print(f"  Timeout: {sup.timeout_seconds}s")
    console.print(f"  Throttle: {sup.throttle_seconds}s")
    if sup.supervisor_effort:
        console.print(f"  Supervisor effort: {sup.supervisor_effort}")
    console.print(f"  Cascade: {'on' if sup.cascade else 'off'}")
    if sup.cascade:
        checker_provider, checker_model, checker_budget = _checker_display(sup)

        console.print(f"  Checker provider: {checker_provider}")
        console.print(f"  Checker model: {checker_model}")
        console.print(f"  Checker budget: {checker_budget} tokens")
        if sup.checker_effort:
            console.print(f"  Checker effort: {sup.checker_effort}")
    if sup.plan_override_path:
        console.print(f"  Plan override: {sup.plan_override_path}")


@supervisor.command(name="set")
@click.argument("target")
@_session_option
@click.option("--supervisor-proxy", type=str, default=None, help="Proxy for supervisor routing (proxy_id or template)")
@click.option(
    "--no-supervisor-proxy",
    "supervisor_direct",
    is_flag=True,
    default=False,
    help="Force supervisor to use direct Anthropic routing",
)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=click.IntRange(min=1),
    default=None,
    help="Supervisor check timeout in seconds (default: 45)",
)
@click.option(
    "--cascade/--no-cascade",
    "cascade_flag",
    default=None,
    help="Enable the tier-1 plan check before the frontier supervisor",
)
@click.option(
    "--checker-model",
    "checker_model",
    default=None,
    help="Tier-1 checker model (prefixed id; default depends on checker provider)",
)
@click.option(
    "--checker-provider",
    "checker_provider",
    type=_CHECKER_PROVIDER_CHOICES,
    default=None,
    help="Tier-1 checker provider (default: openrouter)",
)
@click.option(
    "--checker-effort",
    "checker_effort",
    type=_CHECKER_EFFORT_CHOICES,
    default=None,
    help="Tier-1 checker reasoning effort (none/low/medium/high/xhigh)",
)
@click.option(
    "--supervisor-effort",
    "supervisor_effort",
    type=_SUPERVISOR_EFFORT_CHOICES,
    default=None,
    help="Frontier supervisor effort (claude --effort: low/medium/high/xhigh/max)",
)
def supervisor_set(
    target: str,
    session_name: str | None,
    supervisor_proxy: str | None,
    supervisor_direct: bool,
    timeout_seconds: int | None,
    cascade_flag: bool | None,
    checker_model: str | None,
    checker_provider: str | None,
    checker_effort: str | None,
    supervisor_effort: str | None,
) -> None:
    """Set the semantic supervisor target for the session.

    Durable plan supervision that persists through session resume.

    \b
    Examples:
        forge policy supervisor set planner               # Set planner as supervisor
        forge policy supervisor set planner --timeout 90  # Set with a longer check timeout
        forge policy supervisor set planner --cascade     # Set with the tier-1 cascade enabled
    """
    from forge.policy.semantic.supervisor import (
        apply_supervisor_routing,
        apply_supervisor_to_intent,
        ensure_supervisor_proxy,
        validate_supervisor_target,
    )

    if supervisor_proxy and supervisor_direct:
        console.print("[red]Error:[/red] --supervisor-proxy and --no-supervisor-proxy are mutually exclusive")
        sys.exit(1)
    if cascade_flag is False:
        console.print("[red]Error:[/red] --no-cascade is redundant on set (cascade defaults to off)")
        sys.exit(1)
    try:
        validate_checker_model(checker_model)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        print_tip("Example: google/gemini-3.5-flash", blank_before=False, console=console)
        sys.exit(1)
    checker_option_supplied = bool(checker_model or checker_provider or checker_effort)

    cwd = Path.cwd().resolve()
    store, _state = _resolve_policy_session(cwd, session_name)
    name = _state.name
    manifest = store.read()
    # Validate the target in the selected session's scope, not CWD: a cross-worktree
    # --session would otherwise search the wrong project.
    _policy_fr = manifest.forge_root or _resolve_forge_root(cwd)
    try:
        source_state = validate_supervisor_target(target, forge_root=_policy_fr)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    # Resolve/auto-start the supervisor proxy only after the target validates, so a bad
    # target can't leave a freshly started proxy running.
    if supervisor_proxy:
        try:
            _sup_proxy_id, _sup_started = ensure_supervisor_proxy(supervisor_proxy)
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
        if _sup_started:
            console.print(f"[dim]Started proxy '{_sup_proxy_id}' from template '{supervisor_proxy}'.[/dim]")
        supervisor_proxy = _sup_proxy_id

    current_template = manifest.intent.proxy.template if manifest.intent.proxy else None
    current_proxy_id = None
    if manifest.intent.proxy and hasattr(manifest.intent.proxy, "proxy_id"):
        current_proxy_id = manifest.intent.proxy.proxy_id  # type: ignore[union-attr]
    current_direct = not bool(manifest.intent.proxy)

    sup_config = SupervisorConfig(resume_id=target, forge_root=source_state.forge_root or _policy_fr)
    if timeout_seconds is not None:
        sup_config.timeout_seconds = timeout_seconds
    if supervisor_effort is not None:
        sup_config.supervisor_effort = supervisor_effort
    routing_display = apply_supervisor_routing(
        sup_config,
        source_state,
        supervisor_proxy=supervisor_proxy,
        supervisor_direct=supervisor_direct,
        current_proxy_id=current_proxy_id,
        current_template=current_template,
        current_direct=current_direct,
    )

    cascade_source_desc: str | None = None
    if cascade_flag:
        # The tier-1 checker needs plan snapshot text. Resolve it (exits 1 with a tip
        # when unresolvable) before any manifest mutation.
        sup_config.cascade = True
        apply_checker_options(
            sup_config,
            checker_model=checker_model,
            checker_provider=checker_provider,
            checker_effort=checker_effort,
        )
        plan_path, cascade_source_desc = _resolve_cascade_plan(sup_config, manifest)
        sup_config.plan_override_path = plan_path
    elif checker_option_supplied:
        apply_checker_options(
            sup_config,
            checker_model=checker_model,
            checker_provider=checker_provider,
            checker_effort=checker_effort,
        )

    store.update(timeout_s=5.0, mutate=lambda m: apply_supervisor_to_intent(m, sup_config))
    console.print(f"Supervisor set to [green]{target}[/green] for session [cyan]{name}[/cyan]")
    if routing_display:
        label = "auto-seeded" if not supervisor_proxy and not supervisor_direct else "explicit"
        console.print(f"  Routing ({label}): {routing_display}")
    if timeout_seconds is not None:
        console.print(f"  Timeout: {timeout_seconds}s")
    if sup_config.cascade:
        route_provider, route_model, route_budget = _checker_display(sup_config)
        console.print(
            f"  Cascade: on (checker: {route_model} via {route_provider}, budget: {route_budget} tokens)",
            soft_wrap=True,
        )
        if cascade_source_desc:
            console.print(f"  Tier-1 plan resolved from {cascade_source_desc}: {sup_config.plan_override_path}")


@supervisor.command(name="off")
@_session_option
def supervisor_off(session_name: str | None) -> None:
    """Suspend the supervisor (preserves config)."""
    store, name, manifest = _resolve_supervisor_session(session_name)
    has_sup = (
        manifest.intent.policy and manifest.intent.policy.supervisor and manifest.intent.policy.supervisor.resume_id
    )
    if not has_sup:
        console.print("No supervisor configured.")
        return

    def _suspend(m: SessionState) -> None:
        if m.intent.policy and m.intent.policy.supervisor:
            m.intent.policy.supervisor.suspended = True

    store.update(timeout_s=5.0, mutate=_suspend)
    console.print(f"Supervisor suspended for session [cyan]{name}[/cyan]")
    print_tip(
        "Run 'forge policy supervisor on' to resume or 'forge policy supervisor remove' to delete.",
        blank_before=False,
        console=console,
    )


@supervisor.command(name="on")
@_session_option
def supervisor_on(session_name: str | None) -> None:
    """Resume a suspended supervisor."""
    store, name, manifest = _resolve_supervisor_session(session_name)
    has_sup = (
        manifest.intent.policy and manifest.intent.policy.supervisor and manifest.intent.policy.supervisor.resume_id
    )
    if not has_sup:
        console.print("No supervisor configured. Use 'forge policy supervisor set <target>' to set one.")
        return

    def _resume_sup(m: SessionState) -> None:
        if m.intent.policy and m.intent.policy.supervisor:
            m.intent.policy.supervisor.suspended = False

    store.update(timeout_s=5.0, mutate=_resume_sup)
    console.print(f"Supervisor resumed for session [cyan]{name}[/cyan]")


@supervisor.command(name="remove")
@_session_option
def supervisor_remove(session_name: str | None) -> None:
    """Remove the supervisor configuration entirely."""
    store, name, manifest = _resolve_supervisor_session(session_name)
    has_sup = manifest.intent.policy and manifest.intent.policy.supervisor
    if not has_sup:
        console.print("No supervisor configured.")
        return

    def _remove_sup(m: SessionState) -> None:
        if m.intent.policy and m.intent.policy.supervisor:
            m.intent.policy.supervisor = None

    store.update(timeout_s=5.0, mutate=_remove_sup)
    console.print(f"Supervisor removed from session [cyan]{name}[/cyan]")


@supervisor.command(name="reload")
@click.option(
    "--from",
    "reload_path",
    default=None,
    help="Reload plan from an explicit file path (default: auto-resolve the latest approved plan)",
)
@_session_option
def supervisor_reload(reload_path: str | None, session_name: str | None) -> None:
    """Reload the supervisor's approved plan (auto-resolves the latest unless --from is given)."""
    cwd = Path.cwd().resolve()
    store, _ = _resolve_policy_session(cwd, session_name)
    manifest = store.read()
    effective = compute_effective_intent(manifest)
    if not effective.policy or not effective.policy.supervisor or not effective.policy.supervisor.resume_id:
        console.print("[red]Error:[/red] No supervisor configured.")
        sys.exit(1)

    if reload_path:
        resolved = Path(reload_path)
        if not resolved.is_absolute():
            resolved = (cwd / resolved).resolve()
        if not resolved.is_file():
            console.print(f"[red]Error:[/red] Plan file not found: {resolved}")
            sys.exit(1)
        plan_path = str(resolved)
        source_desc = str(resolved)
    else:
        from forge.policy.semantic.supervisor import (
            resolve_supervisor_reload_plan_path,
        )

        result = resolve_supervisor_reload_plan_path(effective.policy.supervisor, manifest)
        if result is None:
            console.print("[red]Error:[/red] No approved plan found for supervisor target or related sessions.")
            sys.exit(1)
        plan_path = result.path
        source_map = {
            "self": "current session",
            "fork": f"review fork '{result.session_name}'",
            "target": "supervisor target",
        }
        source_desc = source_map.get(result.source, result.source)

    def _set_plan(m: SessionState) -> None:
        if m.intent.policy and m.intent.policy.supervisor:
            m.intent.policy.supervisor.plan_override_path = plan_path

    store.update(timeout_s=5.0, mutate=_set_plan)
    console.print(f"Supervisor plan updated from {source_desc}")


@supervisor.command(name="cascade")
@click.argument("state", type=click.Choice(["on", "off"]))
@_session_option
@click.option(
    "--checker-model",
    "checker_model",
    default=None,
    help="Tier-1 checker model (prefixed id; default depends on checker provider)",
)
@click.option(
    "--checker-provider",
    "checker_provider",
    type=_CHECKER_PROVIDER_CHOICES,
    default=None,
    help="Tier-1 checker provider (default: openrouter)",
)
@click.option(
    "--checker-effort",
    "checker_effort",
    type=_CHECKER_EFFORT_CHOICES,
    default=None,
    help="Tier-1 checker reasoning effort (none/low/medium/high/xhigh)",
)
def supervisor_cascade(
    state: str,
    session_name: str | None,
    checker_model: str | None,
    checker_provider: str | None,
    checker_effort: str | None,
) -> None:
    """Toggle the tier-1 plan check (cascade) on the existing supervisor.

    \b
    Examples:
        forge policy supervisor cascade on    # Enable the tier-1 pre-check
        forge policy supervisor cascade off   # Disable it
    """
    cascade_on = state == "on"
    if not cascade_on and (checker_model or checker_provider or checker_effort):
        console.print("[red]Error:[/red] Checker options only apply when enabling cascade (state 'on')")
        sys.exit(1)
    try:
        validate_checker_model(checker_model)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        print_tip("Example: google/gemini-3.5-flash", blank_before=False, console=console)
        sys.exit(1)

    store, name, manifest = _resolve_supervisor_session(session_name)
    sup = manifest.intent.policy.supervisor if manifest.intent.policy else None
    if not (sup and sup.resume_id):
        console.print("No supervisor configured. Use 'forge policy supervisor set <target>' to set one.")
        return

    if not cascade_on:

        def _disable_cascade(m: SessionState) -> None:
            if m.intent.policy and m.intent.policy.supervisor:
                m.intent.policy.supervisor.cascade = False

        store.update(timeout_s=5.0, mutate=_disable_cascade)
        console.print(f"Cascade disabled for session [cyan]{name}[/cyan]")
        return

    # Enabling: the tier-1 checker needs plan snapshot text. Resolve it (exits 1 with a
    # tip when unresolvable) before any manifest mutation.
    plan_path: str | None = sup.plan_override_path
    source_desc: str | None = None
    if not plan_path:
        effective = compute_effective_intent(manifest)
        assert effective.policy and effective.policy.supervisor  # guarded via intent above
        plan_path, source_desc = _resolve_cascade_plan(effective.policy.supervisor, manifest)

    def _enable_cascade(m: SessionState) -> None:
        if m.intent.policy and m.intent.policy.supervisor:
            m.intent.policy.supervisor.cascade = True
            apply_checker_options(
                m.intent.policy.supervisor,
                checker_model=checker_model,
                checker_provider=checker_provider,
                checker_effort=checker_effort,
            )
            if not m.intent.policy.supervisor.plan_override_path:
                m.intent.policy.supervisor.plan_override_path = plan_path

    store.update(timeout_s=5.0, mutate=_enable_cascade)

    preview = replace(sup)
    preview.cascade = True
    apply_checker_options(
        preview,
        checker_model=checker_model,
        checker_provider=checker_provider,
        checker_effort=checker_effort,
    )
    route_provider, route_model, route_budget = _checker_display(preview)
    console.print(
        f"Cascade enabled for session [cyan]{name}[/cyan] "
        f"(checker: {route_model} via {route_provider}, budget: {route_budget} tokens)",
        soft_wrap=True,
    )
    if source_desc:
        console.print(f"  Tier-1 plan resolved from {source_desc}: {plan_path}")


@policy.group(name="shadow")
def shadow_group() -> None:
    """Inspect supervisor shadow-sampling audit results.

    Shadow sampling replays the frontier supervisor post-hoc on a sample of tier-1
    allows to measure how often the cascade wrongly short-circuited a divergent
    action. Enable it on a supervised session with
    'forge session set policy.supervisor.shadow_sample_rate <0..1>'.

    \b
    Examples:
        forge policy shadow show              # disagreements for the current session
        forge policy shadow show --all        # every audited candidate
    """


@shadow_group.command(name="run", hidden=True)
@click.option("--session-name", required=True, help="Forge session whose shadow candidates to drain")
@click.option("--root", "forge_root", default=None, help="Forge project root (defaults to cwd resolution)")
def shadow_run_cmd(session_name: str, forge_root: str | None) -> None:
    """Drain a session's pending shadow candidates (detached worker; not user-facing).

    Spawned fire-and-forget by the Stop-hook's shadow marker. Replays the frontier
    supervisor on each captured tier-1 allow, records the verdict, and never
    enforces. Per-candidate atomic claims bound frontier billing to at-most-once,
    so a re-spawn after a crash is safe.
    """
    from forge.policy.semantic.shadow_runner import run_shadow_for_session

    if not forge_root:
        from forge.session.artifacts import resolve_forge_root

        forge_root = str(resolve_forge_root(Path.cwd()))

    counts = run_shadow_for_session(session_name, forge_root)
    click.echo(json.dumps({"session": session_name, "drained": counts}))


@shadow_group.command(name="show")
@click.argument("session", required=False)
@click.option("--all", "show_all", is_flag=True, help="Show every audited candidate, not just disagreements")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def shadow_show_cmd(session: str | None, show_all: bool, as_json: bool) -> None:
    """Show shadow-audit disagreements for a session (the cascade's false-aligned cases).

    A disagreement is a fresh tier-1 allow the frontier supervisor would have
    *blocked* (high-confidence, cited divergence). Use --all to also list agree /
    inconclusive / error audits.

    \b
    Examples:
        forge policy shadow show              # current session ($FORGE_SESSION)
        forge policy shadow show planner      # a named session
        forge policy shadow show --all --json
    """
    from forge.core.ops.session_context import (
        SessionContextError,
        resolve_session_identifier,
    )
    from forge.policy.semantic.shadow import read_done_records
    from forge.policy.semantic.shadow_runner import STATUS_DISAGREE

    try:
        session_name, forge_root = resolve_session_identifier(session)
    except SessionContextError as e:
        if as_json:
            click.echo(json.dumps({"error": str(e)}))
        else:
            print_error_with_tip(str(e), "Run 'forge session list' to see sessions.", console=console)
        sys.exit(1)

    records = read_done_records(forge_root, session_name)
    if not show_all:
        records = [r for r in records if r.get("status") == STATUS_DISAGREE]

    if as_json:
        click.echo(json.dumps({"session": session_name, "records": records}, indent=2))
        return

    if not records:
        scope = "audited candidates" if show_all else "disagreements"
        console.print(f"[dim]No shadow {scope} for session '{session_name}'.[/dim]")
        return

    console.print(f"\n[bold]Shadow audit — {session_name}[/bold] [dim]({len(records)} shown)[/dim]")
    for r in records:
        _render_shadow_record(r)


def _render_shadow_record(record: dict[str, Any]) -> None:
    """Render one finalized shadow record: the action, the verdict, and any citations."""
    status = record.get("status", "?")
    color = {"disagree": "yellow", "error": "red"}.get(status, "dim")
    target = record.get("target_path") or "N/A"
    console.print(f"\n  [{color}]{status}[/{color}] · {record.get('tool_name', '?')} {target}")

    confidence = record.get("frontier_confidence")
    if record.get("frontier_verdict"):
        conf = f" (confidence {confidence:.0%})" if isinstance(confidence, (int, float)) else ""
        console.print(f"    frontier: {record['frontier_verdict']}{conf}")

    violations = [v for v in (record.get("frontier_violations") or ()) if isinstance(v, dict)]
    # For a disagreement, only the *cited* violations met the block bar (confidence >= 0.8
    # + citations) and drove the would-be block -- the uncited ones are review noise. For
    # other statuses (shown via --all) keep all: an inconclusive's uncited violations are
    # exactly why it did NOT block.
    if status == "disagree":
        violations = [v for v in violations if v.get("citations")]

    for v in violations:
        evidence = v.get("evidence")
        if evidence:
            console.print(f"    [dim]•[/dim] {evidence}")
        for citation in v.get("citations") or ():
            console.print(f"      [dim]↳ {citation}[/dim]")
