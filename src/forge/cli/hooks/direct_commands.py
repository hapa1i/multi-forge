"""Direct command (%) dispatcher and handlers for UserPromptSubmit hook."""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any

import click

from forge.core.paths import display_path
from forge.core.state import FileLockTimeoutError
from forge.core.state.exceptions import StateCorruptedError, StateUnreadableError
from forge.session import set_override
from forge.session.effective import compute_effective_intent
from forge.session.hooks import resolve_session_store
from forge.session.models import SessionState
from forge.session.store import HOOK_LOCK_TIMEOUT_S

from ._helpers import _output_json


def _parse_direct_command(prompt: str) -> tuple[str, list[str]] | None:
    """Parse `%<cmd> [subcmd] [args...]` direct command.

    This intentionally feels like a tiny CLI:

    - supports quoted args via shell-like parsing (shlex)
    - returns (cmd, argv) where cmd does NOT include the `%`

    Examples:
    - `%help`
    - `%session list`
    - `%policy enable tdd`
    - `%proxy show my-proxy`
    """

    s = prompt.strip()
    if not s.startswith("%"):
        return None

    try:
        parts = shlex.split(s[1:])
    except ValueError:
        # Unbalanced quotes, etc.
        return None

    if not parts:
        return None

    cmd = parts[0].strip().lower()
    argv = [p for p in parts[1:]]
    if not cmd:
        return None

    return cmd, argv


def _emit_state_error_block(e: StateCorruptedError | StateUnreadableError) -> None:
    """Emit a durable-state error as a UserPromptSubmit JSON block.

    Hook context: %-dispatched commands must emit a ``{decision:block}`` decision,
    never the CLI Rich tip. Letting the error escape would unwind to ``AliasGroup.main``
    -> ``handle_corrupt_state_error`` / ``handle_unreadable_state_error`` (Rich stderr +
    ``sys.exit(1)``), breaking the assistant-facing JSON contract. ``%session``/``%proxy``
    are the assistant-facing dispatchers and are the sole hand-rolled tip-bearing exception.

    Corruption and an unreadable (failed-read) file get distinct guidance: corruption is
    deletable/resettable, an unreadable file is transient and must NOT be deleted.
    """
    if isinstance(e, StateCorruptedError):
        reason = (
            f"Forge state is corrupt: {e}\n"
            "Tip: run 'forge clean', or delete .forge / ~/.forge and re-run "
            "'forge extension enable'."
        )
    else:
        reason = (
            f"Forge could not read a state file: {e}\n"
            "Tip: this is usually transient (locked/busy file, I/O error, or permissions) -- "
            "check the file named above and retry. Forge will not delete it."
        )
    click.echo(json.dumps({"decision": "block", "reason": reason}))


def _handle_cmd_help() -> None:
    """Print a short help message for direct commands."""

    click.echo(
        json.dumps(
            {
                "decision": "block",
                "reason": "Direct commands:\n"
                "- %session show [name] | list\n"
                "- %proxy list | show <id> | audit show|diff [id]\n"
                "- %clean [--scope workspace|project|all]\n"
                "- %plan\n"
                "- %config (show runtime config)\n"
                "- %policy status | enable | disable | check\n"
                "- %cancel-verification (bypass verification loop)\n"
                "- %h/%help\n"
                "\n"
                "Tip: Use /copy to copy assistant responses (built-in).",
            }
        )
    )


def _handle_cmd_session(data: dict[str, Any], argv: list[str]) -> None:
    """Handle `%session ...` commands (mirrors CLI syntax).

    Supported:

    - `%session list` (optionally: `--no-incognito` / `--include-incognito`)
    - `%session show [name]` (default: current session from FORGE_SESSION)

    Always emits `{decision:block}` when handled.
    """

    if not argv:
        click.echo(json.dumps({"decision": "block", "reason": "Usage: %session list | show [name]"}))
        return

    sub = argv[0].lower()
    if sub == "show":
        _handle_session_show(argv[1:])
        return
    if sub != "list":
        click.echo(json.dumps({"decision": "block", "reason": "Usage: %session list | show [name]"}))
        return

    include_incognito = True
    if "--no-incognito" in argv:
        include_incognito = False

    # Parse --scope VALUE or --scope=VALUE (default: workspace)
    scope = "workspace"
    for i, arg in enumerate(argv):
        if arg.startswith("--scope="):
            scope = arg.split("=", 1)[1].lower()
            break
        if arg == "--scope" and i + 1 < len(argv):
            scope = argv[i + 1].lower()
            break

    from forge.core.ops.context import ExecutionContext
    from forge.core.ops.session import ForgeOpError
    from forge.core.ops.session import list_sessions as list_sessions_op

    ctx = ExecutionContext.from_cwd()

    try:
        result = list_sessions_op(ctx=ctx, include_incognito=include_incognito, scope=scope)
    except (StateCorruptedError, StateUnreadableError) as e:
        _emit_state_error_block(e)
        return
    except ForgeOpError as e:
        click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
        return

    if not result.sessions:
        click.echo(json.dumps({"decision": "block", "reason": "No sessions found."}))
        return

    lines = ["Sessions:"]
    for item in result.sessions:
        template = item.proxy_template or "-"
        lines.append(f"  {item.name}  ({template})")

    click.echo(json.dumps({"decision": "block", "reason": "\n".join(lines)}))


def _handle_session_show(argv: list[str]) -> None:
    """Handle `%session show [name]`.

    Default (no name): use FORGE_SESSION env var only — no active-session
    fallback to avoid cross-repo ambiguity.
    """
    from forge.core.ops.session_context import SessionContextError, get_session_context

    # Explicit name or FORGE_SESSION env var (no active-session fallback)
    session_id: str | None = argv[0] if argv else os.environ.get("FORGE_SESSION")
    if not session_id:
        click.echo(
            json.dumps(
                {
                    "decision": "block",
                    "reason": "No active session (bare launch).\n"
                    "Tip: Use 'forge session start' for managed sessions,\n"
                    "or '%session show <name>' to inspect a specific session.",
                }
            )
        )
        return

    try:
        ctx = get_session_context(session_id)
    except (StateCorruptedError, StateUnreadableError) as e:
        _emit_state_error_block(e)
        return
    except SessionContextError as e:
        click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
        return

    lines = [f"Session: {ctx.session_name}"]
    if ctx.claude_session_id:
        lines.append(f"  UUID:     {ctx.claude_session_id}")
    if ctx.parent_session:
        lines.append(f"  Parent:   {ctx.parent_session}")
    if ctx.is_fork:
        lines.append("  Type:     fork")
    if ctx.proxy.template:
        lines.append(f"  Template: {ctx.proxy.template}")
    if ctx.proxy.base_url:
        lines.append(f"  Base URL: {ctx.proxy.base_url}")
    if ctx.worktree_path:
        lines.append(f"  Worktree: {display_path(ctx.worktree_path)}")
    if ctx.model_family != "anthropic":
        lines.append(f"  Family:   {ctx.model_family}")
    if ctx.models:
        tier_str = ", ".join(f"{t}={m}" for t, m in sorted(ctx.models.items()))
        lines.append(f"  Models:   {tier_str}")

    click.echo(json.dumps({"decision": "block", "reason": "\n".join(lines)}))


def _handle_cmd_proxy(data: dict[str, Any], argv: list[str]) -> None:
    """Handle `%proxy ...` commands (mirrors CLI syntax, read-only).

    Supported:

    - `%proxy list`: list all registered proxies
    - `%proxy show <id>`: show details for a specific proxy
    - `%proxy audit show|diff [id]`: recent audit metadata / wire changes (metadata only)

    Always emits `{decision:block}` when handled.

    Note: Proxy mutations require terminal (`forge proxy ...`), not direct commands.
    """

    if not argv:
        click.echo(json.dumps({"decision": "block", "reason": "Usage: %proxy list | show <id> | audit show|diff [id]"}))
        return

    sub = argv[0].lower()

    if sub == "list":
        _handle_proxy_list()
        return

    if sub == "show":
        if len(argv) < 2:
            click.echo(json.dumps({"decision": "block", "reason": "Usage: %proxy show <id>"}))
            return
        proxy_id = argv[1]
        _handle_proxy_show(proxy_id)
        return

    if sub == "audit":
        action = argv[1].lower() if len(argv) > 1 else ""
        if action not in ("show", "diff"):
            click.echo(json.dumps({"decision": "block", "reason": "Usage: %proxy audit show|diff [id]"}))
            return
        target = argv[2] if len(argv) > 2 else None
        if action == "show":
            _handle_proxy_audit_show(target)
        else:
            _handle_proxy_audit_diff(target)
        return

    click.echo(json.dumps({"decision": "block", "reason": "Usage: %proxy list | show <id> | audit show|diff [id]"}))


def _handle_proxy_audit_show(proxy_id: str | None) -> None:
    """Show recent audit metadata (read-only; metadata only, never secrets)."""
    from forge.proxy.audit_logger import read_audit_logs

    records = read_audit_logs(proxy_id=proxy_id)[-10:]
    if not records:
        scope = f" for '{proxy_id}'" if proxy_id else ""
        click.echo(json.dumps({"decision": "block", "reason": f"No audit data{scope}."}))
        return

    lines = ["Proxy audit (metadata, last 10):"]
    for record in records:
        ts = record.get("ts", "")
        proxy = record.get("proxy_id", "-")
        if record.get("record_type") == "drift":
            lines.append(f"  {ts} {proxy} drift {record.get('dimension')}")
            continue
        sys_hash = (record.get("system_prompt_hash") or "-").removeprefix("sha256:")[:10]
        lines.append(f"  {ts} {proxy} {record.get('mode', '-')} sys:{sys_hash}")
    click.echo(json.dumps({"decision": "block", "reason": "\n".join(lines)}))


def _handle_proxy_audit_diff(proxy_id: str | None) -> None:
    """Show recent wire changes (drift + override mutations; metadata only, never secrets)."""
    from forge.proxy.audit_logger import read_audit_logs

    changes = [r for r in read_audit_logs(proxy_id=proxy_id) if r.get("record_type") in ("drift", "mutation")][-10:]
    if not changes:
        scope = f" for '{proxy_id}'" if proxy_id else ""
        click.echo(json.dumps({"decision": "block", "reason": f"No wire changes{scope}."}))
        return

    lines = ["Proxy wire changes (last 10):"]
    for record in changes:
        ts = record.get("ts", "")
        proxy = record.get("proxy_id", "-")
        if record.get("record_type") == "drift":
            prev = (record.get("previous_hash") or "-").removeprefix("sha256:")[:8]
            curr = (record.get("current_hash") or "-").removeprefix("sha256:")[:8]
            lines.append(f"  {ts} {proxy} drift {record.get('dimension')}: {prev} -> {curr}")
        else:
            actions = ",".join(m.get("action", "?") for m in record.get("mutations", []))
            tag = "blocked" if record.get("blocked") else "mutation"
            lines.append(f"  {ts} {proxy} {tag}: {actions}")
    click.echo(json.dumps({"decision": "block", "reason": "\n".join(lines)}))


def _handle_proxy_list() -> None:
    """List all registered proxies."""
    from forge.core.ops.context import ExecutionContext
    from forge.core.ops.proxy import list_proxies as list_proxies_op
    from forge.core.ops.session import ForgeOpError

    ctx = ExecutionContext.from_cwd()

    try:
        result = list_proxies_op(ctx=ctx)
    except (StateCorruptedError, StateUnreadableError) as e:
        _emit_state_error_block(e)
        return
    except ForgeOpError as e:
        click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
        return

    if not result.proxies:
        click.echo(json.dumps({"decision": "block", "reason": "No proxies found."}))
        return

    lines = ["Proxies:"]
    for item in result.proxies:
        status = item.entry.status or "unknown"
        template = item.entry.template or "-"
        port = item.entry.port or "-"
        lines.append(f"  {item.proxy_id}  {template}  :{port}  ({status})")

    click.echo(json.dumps({"decision": "block", "reason": "\n".join(lines)}))


def _handle_proxy_show(proxy_id: str) -> None:
    """Show details for a specific proxy."""
    from forge.core.ops.context import ExecutionContext
    from forge.core.ops.proxy import show_proxy as show_proxy_op
    from forge.core.ops.session import ForgeOpError

    ctx = ExecutionContext.from_cwd()

    try:
        result = show_proxy_op(ctx=ctx, proxy_id=proxy_id)
    except ForgeOpError as e:
        click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
        return

    lines = [f"Proxy: {result.proxy_id}"]
    if result.entry:
        lines.append(f"  Template: {result.entry.template}")
        lines.append(f"  Base URL: {result.entry.base_url}")
        lines.append(f"  Port: {result.entry.port}")
        lines.append(f"  Status: {result.entry.status or 'unknown'}")
    else:
        lines.append("  (not in registry — config file only)")

    if result.config:
        lines.append(f"  Provider: {result.config.provider}")
        lines.append(f"  Default tier: {result.config.default_tier}")
        if result.config.tiers:
            lines.append("  Tiers:")
            # TierModels is a dataclass with haiku/sonnet/opus attributes
            for tier in ("haiku", "sonnet", "opus"):
                model = getattr(result.config.tiers, tier, "")
                if model:
                    lines.append(f"    {tier}: {model}")

    click.echo(json.dumps({"decision": "block", "reason": "\n".join(lines)}))


def _handle_cmd_plan(argv: list[str]) -> None:
    """Handle `%plan` (show the plan file for this session or its immediate parent)."""
    if argv:
        click.echo(json.dumps({"decision": "block", "reason": "Usage: %plan"}))
        return

    store = resolve_session_store(Path.cwd().resolve())
    if store is None:
        click.echo(json.dumps({"decision": "block", "reason": "No session found"}))
        return

    try:
        manifest = store.read()
    except Exception as e:
        click.echo(json.dumps({"decision": "block", "reason": f"Error reading session: {e}"}))
        return

    from forge.session.plan_resolution import (
        resolve_displayed_plan_path,
        resolve_plan_info,
        resolve_plan_launch_root,
    )

    plan_info = resolve_plan_info(manifest, current_forge_root=str(store.forge_root))
    displayed = resolve_displayed_plan_path(
        plan_info,
        current_forge_root=str(store.forge_root),
        current_launch_root=resolve_plan_launch_root(manifest),
    )

    if displayed is None or plan_info.source is None:
        click.echo(
            json.dumps(
                {
                    "decision": "block",
                    "reason": "No plan file recorded for this session or its ancestry",
                }
            )
        )
        return

    missing = "" if displayed.exists else " (file missing)"

    if plan_info.approved_snapshots:
        if plan_info.source == "parent":
            reason = (
                f"Approved plan (snapshot, from '{plan_info.parent_session}'): "
                f"{display_path(displayed.path)}{missing}"
            )
        else:
            reason = f"Approved plan (snapshot): {display_path(displayed.path)}{missing}"
    else:
        if plan_info.source == "parent":
            reason = f"Plan (draft, from '{plan_info.parent_session}'): " f"{display_path(displayed.path)}{missing}"
        else:
            reason = f"Plan (draft): {display_path(displayed.path)}{missing}"

    click.echo(json.dumps({"decision": "block", "reason": reason}))


def _handle_cmd_config(data: dict[str, Any], argv: list[str]) -> None:
    """Handle `%config` command (read-only — shows effective runtime config).

    No mutations from inside a session (matching %proxy policy).
    """
    from dataclasses import fields as dc_fields
    from dataclasses import is_dataclass

    from forge.runtime_config import RuntimeConfig, get_config_path, load_runtime_config

    rc = load_runtime_config()
    config_path = get_config_path()
    env_sources: dict[str, str] = getattr(rc, "_env_sources", {})

    lines = ["Forge Runtime Config:"]
    if config_path.is_file():
        lines.append(f"  Path: {display_path(config_path)}")
    else:
        lines.append("  Path: (no file — using defaults)")

    for f in dc_fields(RuntimeConfig):
        val = getattr(rc, f.name)
        # Expand nested config (e.g. statusline) instead of printing its repr.
        if is_dataclass(val) and not isinstance(val, type):
            lines.append(f"  {f.name}:")
            for sub in dc_fields(type(val)):
                lines.append(f"    {sub.name}: {getattr(val, sub.name)}")
            continue
        env_var = env_sources.get(f.name)
        if env_var:
            lines.append(f"  {f.name}: {val}  (from {env_var})")
        else:
            lines.append(f"  {f.name}: {val}")

    click.echo(json.dumps({"decision": "block", "reason": "\n".join(lines)}))


def _handle_cmd_policy(data: dict[str, Any], argv: list[str]) -> None:
    """Handle `%policy ...` commands (mirrors CLI syntax).

    Supported:

    - `%policy status`: show policy configuration and state
    - `%policy enable --bundle tdd`: enable with specified bundles
    - `%policy disable`: disable policy enforcement
    - `%policy check [--staged] [--bundle tdd]`: evaluate git diff against policies

    Always emits `{decision:block}` when handled.
    """
    if not argv:
        click.echo(
            json.dumps(
                {
                    "decision": "block",
                    "reason": "Usage: %policy status | enable | disable | check | supervisor",
                }
            )
        )
        return

    sub = argv[0].lower()

    if sub == "status":
        _handle_policy_status()
        return

    if sub == "enable":
        _handle_policy_enable(argv[1:])
        return

    if sub == "disable":
        _handle_policy_disable()
        return

    if sub == "check":
        _handle_policy_check(argv[1:])
        return

    if sub == "supervisor":
        _handle_policy_supervisor(argv[1:])
        return

    click.echo(
        json.dumps({"decision": "block", "reason": "Usage: %policy status | enable | disable | check | supervisor"})
    )


def _handle_policy_status() -> None:
    """Show policy configuration and state."""
    cwd = Path.cwd().resolve()
    store = resolve_session_store(cwd)
    if store is None:
        _output_json({"success": True, "action": "skip", "reason": "no_session"})
        return

    try:
        manifest = store.read()
    except Exception:
        click.echo(json.dumps({"decision": "block", "reason": "No session found"}))
        return

    from forge.session.effective import compute_effective_intent

    try:
        effective = compute_effective_intent(manifest)
    except Exception as e:
        click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
        return

    lines = [f"Policy Status: {manifest.name}"]

    if effective.policy:
        lines.append(f"  Enabled: {'Yes' if effective.policy.enabled else 'No'}")
        lines.append(f"  Fail Mode: {effective.policy.fail_mode or 'open'}")
        bundles = ", ".join(effective.policy.bundles) if effective.policy.bundles else "None"
        lines.append(f"  Bundles: {bundles}")
        if effective.policy.bundle_config:
            for bundle, cfg in effective.policy.bundle_config.items():
                cfg_str = ", ".join(f"{k}={v}" for k, v in cfg.items())
                lines.append(f"    {bundle}: {cfg_str}")

        if effective.policy.supervisor and effective.policy.supervisor.resume_id:
            sup = effective.policy.supervisor
            assert sup.resume_id is not None
            sup_resume: str = sup.resume_id
            lines.append(f"  Supervisor: {sup_resume}")
            if sup.suspended:
                lines.append("    Status: suspended")
            try:
                from forge.policy.queries import read_scoped_supervisor_target

                ts = read_scoped_supervisor_target(sup_resume, sup.forge_root, manifest.forge_root)
                if ts is not None:
                    uuid = ts.confirmed.claude_session_id
                    if uuid:
                        lines.append(f"    UUID: {uuid[:16]}...")
                    swp = ts.confirmed.started_with_proxy
                    if swp and swp.template:
                        lines.append(f"    Source model: {swp.template}")
            except Exception:
                pass
            if sup.proxy:
                lines.append(f"    Routing: proxy: {sup.proxy}")
            elif sup.direct:
                lines.append("    Routing: direct (no proxy)")
            lines.append(f"    Fork: {'yes' if sup.fork_session else 'no'}")
            if sup.plan_override_path:
                lines.append(f"    Plan override: {sup.plan_override_path}")
        else:
            lines.append("  Supervisor: Not configured")
    else:
        lines.append("  Enabled: No (not configured)")

    if manifest.confirmed.policy:
        confirmed = manifest.confirmed.policy
        lines.append("")
        lines.append("Policy State:")
        lines.append(f"  Decisions Logged: {len(confirmed.decisions or [])}")
        lines.append(f"  Policy States: {len(confirmed.policy_states or {})}")

    # Supervised-sessions tip
    try:
        from forge.policy.queries import find_sessions_supervised_by

        supervised = find_sessions_supervised_by(
            manifest.name, manifest.confirmed.claude_session_id, manifest.forge_root
        )
        if supervised:
            names = ", ".join(supervised)
            lines.append(
                f"\nTip: This session supervises: {names}. "
                f"Check with: forge policy status --session {supervised[0]}"
            )
    except Exception:
        pass

    click.echo(json.dumps({"decision": "block", "reason": "\n".join(lines)}))


def _handle_policy_enable(argv: list[str]) -> None:
    """Enable policy with specified bundles.

    Uses overrides (not intent mutation) to preserve the original session baseline.
    Resolves session via CWD-based hook resolution (not SessionManager/index).
    """
    from forge.session.models import SessionState

    bundles: list[str] = []
    fail_mode = "open"
    permissive = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--bundle", "-b") and i + 1 < len(argv):
            bundle = argv[i + 1]
            if bundle in ("tdd", "coding_standards"):
                bundles.append(bundle)
            i += 2
        elif arg in ("--fail-mode",) and i + 1 < len(argv):
            fm = argv[i + 1]
            if fm in ("open", "closed"):
                fail_mode = fm
            i += 2
        elif arg == "--permissive":
            permissive = True
            i += 1
        else:
            # Try to interpret as a bundle name directly
            if arg in ("tdd", "coding_standards"):
                bundles.append(arg)
            i += 1

    if not bundles:
        click.echo(
            json.dumps(
                {
                    "decision": "block",
                    "reason": "Usage: %policy enable --bundle tdd [--bundle coding_standards] [--permissive]",
                }
            )
        )
        return

    bundle_config: dict[str, dict[str, object]] = {}
    if permissive and "tdd" in bundles:
        bundle_config["tdd"] = {"strict": False}

    cwd = Path.cwd().resolve()
    store = resolve_session_store(cwd)
    if store is None:
        _output_json({"success": True, "action": "skip", "reason": "no_session"})
        return

    try:
        store.read()  # Verify session exists
    except Exception:
        click.echo(json.dumps({"decision": "block", "reason": "No session found"}))
        return

    def _mutate(m: object) -> None:
        if not isinstance(m, SessionState):
            raise TypeError(f"Expected SessionState, got {type(m)}")
        set_override(m.overrides, "policy.enabled", True)
        set_override(m.overrides, "policy.bundles", bundles)
        set_override(m.overrides, "policy.fail_mode", fail_mode)
        if bundle_config:
            set_override(m.overrides, "policy.bundle_config", bundle_config)

    try:
        store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_mutate)
    except Exception as e:
        click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
        return

    mode_note = " (permissive)" if permissive else ""
    click.echo(
        json.dumps(
            {
                "decision": "block",
                "reason": f"Policy enabled with bundles: {', '.join(bundles)} (fail_mode: {fail_mode}){mode_note}",
            }
        )
    )


def _handle_policy_disable() -> None:
    """Disable policy enforcement.

    Uses overrides (not intent mutation) to preserve the original session baseline.
    Resolves session via CWD-based hook resolution (not SessionManager/index).
    """
    from forge.session.models import SessionState

    cwd = Path.cwd().resolve()
    store = resolve_session_store(cwd)
    if store is None:
        _output_json({"success": True, "action": "skip", "reason": "no_session"})
        return

    try:
        store.read()  # Verify session exists
    except Exception:
        click.echo(json.dumps({"decision": "block", "reason": "No session found"}))
        return

    def _mutate(m: object) -> None:
        if not isinstance(m, SessionState):
            raise TypeError(f"Expected SessionState, got {type(m)}")
        set_override(m.overrides, "policy.enabled", False)

    try:
        store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_mutate)
    except Exception as e:
        click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
        return

    click.echo(json.dumps({"decision": "block", "reason": "Policy enforcement disabled"}))


def _handle_policy_supervisor(argv: list[str]) -> None:
    """Configure or show the semantic supervisor.

    Writes to intent (not overrides) so supervisor config survives
    ``resume --fresh`` which deepcopies ``intent.policy`` into child sessions.

    - ``%policy supervisor <target>``: set supervisor
    - ``%policy supervisor off``: suspend (preserves config)
    - ``%policy supervisor on``: resume suspended supervisor
    - ``%policy supervisor remove``: remove supervisor entirely
    - ``%policy supervisor reload [path]``: reload latest relevant approved plan
    - ``%policy supervisor cascade on|off``: toggle the tier-1 plan check
    - ``%policy supervisor``: show current config
    """
    from forge.session.models import SessionState

    cwd = Path.cwd().resolve()
    store = resolve_session_store(cwd)
    if store is None:
        _output_json({"success": True, "action": "skip", "reason": "no_session"})
        return

    try:
        manifest = store.read()
    except Exception:
        click.echo(json.dumps({"decision": "block", "reason": "No session found"}))
        return

    cmd = argv[0].lower() if argv else ""

    # %policy supervisor off — suspend
    if cmd == "off":
        has_sup = (
            manifest.intent.policy and manifest.intent.policy.supervisor and manifest.intent.policy.supervisor.resume_id
        )
        if not has_sup:
            click.echo(json.dumps({"decision": "block", "reason": "No supervisor configured"}))
            return

        def _suspend(m: object) -> None:
            if not isinstance(m, SessionState):
                raise TypeError(f"Expected SessionState, got {type(m)}")
            if m.intent.policy and m.intent.policy.supervisor:
                m.intent.policy.supervisor.suspended = True

        try:
            store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_suspend)
        except Exception as e:
            click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
            return
        click.echo(
            json.dumps({"decision": "block", "reason": "Supervisor suspended (use 'on' to resume, 'remove' to delete)"})
        )
        return

    # %policy supervisor on — resume
    if cmd == "on":

        def _resume(m: object) -> None:
            if not isinstance(m, SessionState):
                raise TypeError(f"Expected SessionState, got {type(m)}")
            if m.intent.policy and m.intent.policy.supervisor:
                m.intent.policy.supervisor.suspended = False

        has_sup = (
            manifest.intent.policy and manifest.intent.policy.supervisor and manifest.intent.policy.supervisor.resume_id
        )
        if not has_sup:
            click.echo(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": "No supervisor configured. Use '%policy supervisor <target>' to set one.",
                    }
                )
            )
            return

        try:
            store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_resume)
        except Exception as e:
            click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
            return
        click.echo(json.dumps({"decision": "block", "reason": "Supervisor resumed"}))
        return

    # %policy supervisor remove — destructive
    if cmd == "remove":
        has_sup = manifest.intent.policy and manifest.intent.policy.supervisor
        if not has_sup:
            click.echo(json.dumps({"decision": "block", "reason": "No supervisor configured"}))
            return

        def _remove(m: object) -> None:
            if not isinstance(m, SessionState):
                raise TypeError(f"Expected SessionState, got {type(m)}")
            if m.intent.policy and m.intent.policy.supervisor:
                m.intent.policy.supervisor = None

        try:
            store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_remove)
        except Exception as e:
            click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
            return
        click.echo(json.dumps({"decision": "block", "reason": "Supervisor removed"}))
        return

    # %policy supervisor reload [path]
    if cmd == "reload":
        if len(argv) > 2:
            click.echo(json.dumps({"decision": "block", "reason": "Usage: %policy supervisor reload [path]"}))
            return

        from forge.session.effective import compute_effective_intent

        effective = compute_effective_intent(manifest)
        if not effective.policy or not effective.policy.supervisor or not effective.policy.supervisor.resume_id:
            click.echo(json.dumps({"decision": "block", "reason": "No supervisor configured"}))
            return

        plan_path: str | None = None

        if len(argv) == 2:
            # Explicit path — resolve to absolute from CWD
            resolved = Path(argv[1])
            if not resolved.is_absolute():
                resolved = cwd / resolved
            resolved = resolved.resolve()
            if not resolved.is_file():
                click.echo(json.dumps({"decision": "block", "reason": f"Plan file not found: {resolved}"}))
                return
            plan_path = str(resolved)
            source_desc = str(resolved)
        else:
            from forge.policy.semantic.supervisor import (
                resolve_supervisor_reload_plan_path,
            )

            result = resolve_supervisor_reload_plan_path(effective.policy.supervisor, manifest)
            if result is None:
                click.echo(
                    json.dumps(
                        {
                            "decision": "block",
                            "reason": "No approved plan found for supervisor target or related sessions",
                        }
                    )
                )
                return
            plan_path = result.path
            source_map = {
                "self": "current session",
                "fork": f"review fork '{result.session_name}'",
                "target": "supervisor target",
            }
            source_desc = source_map.get(result.source, result.source)

        def _set_plan(m: object) -> None:
            if not isinstance(m, SessionState):
                raise TypeError(f"Expected SessionState, got {type(m)}")
            if m.intent.policy and m.intent.policy.supervisor:
                m.intent.policy.supervisor.plan_override_path = plan_path

        try:
            store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_set_plan)
        except Exception as e:
            click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
            return
        click.echo(json.dumps({"decision": "block", "reason": f"Supervisor plan updated from {source_desc}"}))
        return

    # %policy supervisor cascade on|off — toggle the tier-1 plan check
    if cmd == "cascade":
        sub = argv[1].lower() if len(argv) == 2 else None
        if sub not in ("on", "off"):
            click.echo(json.dumps({"decision": "block", "reason": "Usage: %policy supervisor cascade on|off"}))
            return

        sup = manifest.intent.policy.supervisor if manifest.intent.policy else None
        if not (sup and sup.resume_id):
            click.echo(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": "No supervisor configured. Use '%policy supervisor <target>' to set one.",
                    }
                )
            )
            return

        if sub == "off":

            def _cascade_off(m: object) -> None:
                if not isinstance(m, SessionState):
                    raise TypeError(f"Expected SessionState, got {type(m)}")
                if m.intent.policy and m.intent.policy.supervisor:
                    m.intent.policy.supervisor.cascade = False

            try:
                store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_cascade_off)
            except Exception as e:
                click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
                return
            click.echo(json.dumps({"decision": "block", "reason": "Cascade disabled"}))
            return

        # Enabling: the tier-1 checker needs plan snapshot text. Resolve before mutating.
        plan_path = sup.plan_override_path
        cascade_source: str | None = None
        if not plan_path:
            from forge.policy.semantic.supervisor import (
                resolve_supervisor_reload_plan_path,
            )
            from forge.session.effective import compute_effective_intent

            effective = compute_effective_intent(manifest)
            sup_effective = effective.policy.supervisor if effective.policy else None
            result = resolve_supervisor_reload_plan_path(sup_effective, manifest) if sup_effective else None
            if result is None:
                click.echo(
                    json.dumps(
                        {
                            "decision": "block",
                            "reason": (
                                "No approved plan snapshot found for the cascade's tier-1 checker. "
                                "Approve a plan (ExitPlanMode), or use '%policy supervisor reload <path>' "
                                "to set one explicitly, then retry."
                            ),
                        }
                    )
                )
                return
            plan_path = result.path
            source_map = {
                "self": "current session",
                "fork": f"review fork '{result.session_name}'",
                "target": "supervisor target",
            }
            cascade_source = source_map.get(result.source, result.source)

        def _cascade_on(m: object) -> None:
            if not isinstance(m, SessionState):
                raise TypeError(f"Expected SessionState, got {type(m)}")
            if m.intent.policy and m.intent.policy.supervisor:
                m.intent.policy.supervisor.cascade = True
                if not m.intent.policy.supervisor.plan_override_path:
                    m.intent.policy.supervisor.plan_override_path = plan_path

        try:
            store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_cascade_on)
        except Exception as e:
            click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
            return
        msg = "Cascade enabled"
        if cascade_source:
            msg += f" (tier-1 plan from {cascade_source})"
        click.echo(json.dumps({"decision": "block", "reason": msg}))
        return

    # %policy supervisor <target> — set supervisor
    if argv:
        target = argv[0]

        from forge.policy.semantic.supervisor import (
            apply_supervisor_to_intent,
            auto_seed_supervisor_proxy,
            should_supervisor_use_direct,
            validate_supervisor_target,
        )
        from forge.session.models import SupervisorConfig

        _dc_forge_root = manifest.forge_root
        try:
            source_state = validate_supervisor_target(target, forge_root=_dc_forge_root)
        except ValueError as e:
            click.echo(json.dumps({"decision": "block", "reason": str(e)}))
            return

        sup_config = SupervisorConfig(resume_id=target, forge_root=source_state.forge_root or _dc_forge_root)
        current_template = manifest.intent.proxy.template if manifest.intent.proxy else None
        current_proxy_id = None
        if manifest.intent.proxy and hasattr(manifest.intent.proxy, "proxy_id"):
            current_proxy_id = manifest.intent.proxy.proxy_id  # type: ignore[union-attr]

        seeded_proxy = auto_seed_supervisor_proxy(
            source_state,
            current_proxy_id=current_proxy_id,
            current_template=current_template,
            current_direct=not bool(manifest.intent.proxy),
        )
        if seeded_proxy:
            sup_config.proxy = seeded_proxy
        if should_supervisor_use_direct(source_state):
            sup_config.direct = True

        def _set(m: object) -> None:
            if not isinstance(m, SessionState):
                raise TypeError(f"Expected SessionState, got {type(m)}")
            apply_supervisor_to_intent(m, sup_config)

        try:
            store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_set)
        except Exception as e:
            click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
            return

        msg = f"Supervisor set to '{target}'"
        if seeded_proxy:
            msg += f" (proxy: {seeded_proxy})"
        click.echo(json.dumps({"decision": "block", "reason": msg}))
        return

    # %policy supervisor (no args) — show current config
    from forge.session.effective import compute_effective_intent

    effective = compute_effective_intent(manifest)

    if not effective.policy or not effective.policy.supervisor or not effective.policy.supervisor.resume_id:
        click.echo(json.dumps({"decision": "block", "reason": "No supervisor configured"}))
        return

    sup = effective.policy.supervisor
    assert sup.resume_id is not None  # guarded above
    lines = [f"Supervisor: {sup.resume_id}"]
    if sup.suspended:
        lines.append("  Status: suspended")
    try:
        from forge.session.manager import SessionManager

        target_state = SessionManager().get_session(sup.resume_id, forge_root=sup.forge_root or manifest.forge_root)
        uuid = target_state.confirmed.claude_session_id
        if uuid:
            lines.append(f"  UUID: {uuid[:16]}...")
    except Exception:
        pass
    if sup.proxy:
        lines.append(f"  Routing: proxy: {sup.proxy}")
    elif sup.direct:
        lines.append("  Routing: direct (no proxy)")
    lines.append(f"  Fork: {'yes' if sup.fork_session else 'no'}")
    lines.append(f"  Timeout: {sup.timeout_seconds}s, Throttle: {sup.throttle_seconds}s")
    lines.append(f"  Cascade: {'on' if sup.cascade else 'off'}")
    if sup.cascade:
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
            checker_model = route.model
            checker_provider: str = route.provider or "auto"
        except ValueError:
            checker_model = sup.checker_model or "unresolved"
            checker_provider = f"{sup.checker_provider or 'auto'} (unsupported)"
        lines.append(f"  Checker: {checker_model} via {checker_provider} ({budget} tokens)")
    if sup.plan_override_path:
        lines.append(f"  Plan override: {sup.plan_override_path}")

    click.echo(json.dumps({"decision": "block", "reason": "\n".join(lines)}))


# --- %policy check helpers ---

# Primary split boundary: diff --git a/<path> b/<path>
_DIFF_GIT_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)
# Fallback path extraction: +++ b/<path> (may be absent for binary files)
_DIFF_PLUS_PATH_RE = re.compile(r"^\+\+\+ b/(.+?)(?:\t.*)?$", re.MULTILINE)


def _split_diff_per_file(diff: str) -> list[tuple[str, str]]:
    """Split a multi-file unified diff into (path, chunk) pairs.

    Primary split is on ``diff --git`` boundaries (handles binary diffs).
    Path extracted from ``diff --git a/... b/<path>``, with ``+++ b/<path>``
    as fallback. Deleted files (target /dev/null) are skipped.
    """
    if not diff or not diff.strip():
        return []

    headers = list(_DIFF_GIT_HEADER_RE.finditer(diff))
    if not headers:
        return []

    results: list[tuple[str, str]] = []
    for i, match in enumerate(headers):
        start = match.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(diff)
        chunk = diff[start:end]

        # Primary: path from diff --git header (group 2 = b/ path)
        path = match.group(2).strip()

        # Fallback: if diff --git path looks odd, try +++ b/
        if not path:
            plus_match = _DIFF_PLUS_PATH_RE.search(chunk)
            if plus_match:
                path = plus_match.group(1).strip()

        if not path:
            continue

        # Skip deleted files
        if path == "/dev/null":
            continue
        if "\n+++ /dev/null" in chunk:
            continue

        results.append((path, chunk))

    return results


def _sort_tests_first(file_diffs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Sort file diffs so tests/ paths come before src/ paths.

    Optimistic ordering for TDD stateful evaluation: test files populate
    ``_tests_touched`` before implementation files are checked.
    """

    def _sort_key(item: tuple[str, str]) -> int:
        path = item[0]
        if path.startswith("tests/") or path.startswith("tests\\"):
            return 0
        if path.startswith("src/") or path.startswith("src\\"):
            return 2
        return 1

    return sorted(file_diffs, key=_sort_key)


def _handle_policy_check(argv: list[str]) -> None:
    """Run policy evaluation against the current git diff.

    Runs ``git diff`` (or ``git diff --staged``) in-process, splits into
    per-file chunks, evaluates each against policy bundles using a single
    engine with tests-first ordering, and reports aggregated results.
    """
    import subprocess

    from forge.policy.engine import build_engine
    from forge.policy.types import ActionContext, extract_added_lines

    bundles: list[str] = []
    staged = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--bundle", "-b") and i + 1 < len(argv):
            bundle = argv[i + 1]
            if bundle in ("tdd", "coding_standards"):
                bundles.append(bundle)
            i += 2
        elif arg == "--staged":
            staged = True
            i += 1
        else:
            # Positional bundle names
            if arg in ("tdd", "coding_standards"):
                bundles.append(arg)
            i += 1

    cwd = Path.cwd().resolve()
    bundle_config: dict[str, dict[str, object]] = {}

    if not bundles:
        store = resolve_session_store(cwd)
        if store is not None:
            try:
                manifest = store.read()
                effective = compute_effective_intent(manifest)
                if effective.policy and effective.policy.bundles:
                    bundles = list(effective.policy.bundles)
                if effective.policy and effective.policy.bundle_config:
                    bundle_config = effective.policy.bundle_config
            except Exception as e:
                click.echo(
                    json.dumps(
                        {
                            "decision": "block",
                            "passed": False,
                            "reason": f"Error reading session: {e}. Use --bundle to specify bundles explicitly.",
                        }
                    )
                )
                return

    if not bundles:
        click.echo(
            json.dumps(
                {
                    "decision": "block",
                    "passed": False,
                    "reason": "No bundles configured. Use --bundle or enable via %policy enable.",
                }
            )
        )
        return

    try:
        root_proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(cwd),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        click.echo(json.dumps({"decision": "block", "passed": False, "reason": "Error: git not found or timed out"}))
        return

    if root_proc.returncode != 0:
        msg = root_proc.stderr.strip()[:200] if root_proc.stderr else "not a git repository"
        click.echo(json.dumps({"decision": "block", "passed": False, "reason": f"Error: {msg}"}))
        return

    repo_root = root_proc.stdout.strip()

    git_cmd = ["git", "diff"]
    if staged:
        git_cmd.append("--staged")

    try:
        proc = subprocess.run(git_cmd, capture_output=True, text=True, timeout=10, cwd=repo_root)
    except FileNotFoundError:
        click.echo(json.dumps({"decision": "block", "passed": False, "reason": "Error: git not found"}))
        return
    except subprocess.TimeoutExpired:
        click.echo(json.dumps({"decision": "block", "passed": False, "reason": "Error: git diff timed out"}))
        return

    if proc.returncode != 0:
        msg = proc.stderr.strip()[:200] if proc.stderr else "unknown error"
        click.echo(json.dumps({"decision": "block", "passed": False, "reason": f"Error: git diff failed: {msg}"}))
        return

    diff_output = proc.stdout
    if not diff_output.strip():
        label = "staged" if staged else "unstaged"
        click.echo(json.dumps({"decision": "block", "passed": True, "reason": f"No {label} changes to check."}))
        return

    file_diffs = _split_diff_per_file(diff_output)
    if not file_diffs:
        click.echo(
            json.dumps(
                {
                    "decision": "block",
                    "passed": False,
                    "reason": "Error: diff output present but no files could be parsed",
                }
            )
        )
        return

    file_diffs = _sort_tests_first(file_diffs)

    try:
        engine = build_engine(list(bundles), fail_mode="closed", bundle_config=bundle_config or None)
    except Exception as e:
        click.echo(json.dumps({"decision": "block", "passed": False, "reason": f"Error building policy engine: {e}"}))
        return

    all_violations: list[str] = []
    all_warnings: list[str] = []
    any_deny = False
    files_checked = 0

    for file_path, diff_chunk in file_diffs:
        added = extract_added_lines(diff_chunk) if diff_chunk else None
        # origin stays "claude_code": %policy check is dispatched from a Claude
        # UserPromptSubmit hook, so the invoking actor genuinely is the Claude session
        # (unlike the forge_cli-tagged terminal leaves in cli/policy.py).
        context = ActionContext(
            origin="claude_code",
            event="OnDemand.Check",
            tool_name="Edit",
            tool_args={"file_path": file_path, "content": (added or "")[:200]},
            repo_root=repo_root,
            session_name="on-demand",
            target_path=file_path,
            new_content=added[:5000] if added else None,
            raw_diff=diff_chunk[:5000] if diff_chunk else None,
        )

        try:
            result = engine.evaluate(context)
        except Exception as e:
            files_checked += 1
            any_deny = True
            all_violations.append(f"  [engine-error] {file_path}: evaluation crashed: {e}")
            continue

        files_checked += 1

        if result.final_decision == "deny":
            any_deny = True
            for d in result.decisions:
                if d.decision != "deny":
                    continue
                for i, v in enumerate(d.violations):
                    all_violations.append(f"  [{v.rule_id}] {file_path}: {v.message}")
                    if d.intent and i == 0:
                        all_violations.append(f"    Intent: {d.intent}")
                    if v.suggested_fix:
                        all_violations.append(f"    Fix: {v.suggested_fix}")

        all_warnings.extend(f"  {file_path}: {w}" for w in result.all_warnings)

    passed = not any_deny
    lines: list[str] = []
    bundles_str = ", ".join(bundles)

    if any_deny:
        lines.append(f"Policy check FAILED ({files_checked} files checked, tests-first ordering)")
        lines.append("")
        lines.append("Violations:")
        lines.extend(all_violations)
    else:
        lines.append(f"All policies passed ({files_checked} files checked, tests-first ordering)")

    if all_warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(all_warnings)

    lines.append("")
    lines.append(f"Bundles: {bundles_str}")

    click.echo(
        json.dumps(
            {
                "decision": "block",
                "passed": passed,
                "files_checked": files_checked,
                "bundles": list(bundles),
                "reason": "\n".join(lines),
            }
        )
    )


def _handle_cmd_cancel_verification() -> None:
    """Handle `%cancel-verification` command - bypass verification loop.

    This is an escape hatch for users who are stuck in a verification loop
    (e.g., when the promise string can't be produced by the assistant).

    Implementation:
    - Sets `verification.bypass = true` as an override (not mutating intent)
    - This preserves the original verification config while bypassing it
    - The bypass takes immediate effect on the next Stop hook invocation

    Robustness:
    - Uses strict=False for compute_effective_intent to avoid failing on
      malformed overrides. As an escape hatch, this must work even when
      session state is broken.
    """
    cwd = Path.cwd().resolve()
    store = resolve_session_store(cwd)
    if store is None:
        _output_json({"success": True, "action": "skip", "reason": "no_session"})
        return

    try:
        manifest = store.read()
    except Exception:
        click.echo(json.dumps({"decision": "block", "reason": "No session found"}))
        return

    # Use strict=False: escape hatch must work even with malformed overrides
    try:
        effective = compute_effective_intent(manifest, strict=False)
    except Exception:
        # If even non-strict fails, fall back to raw intent check
        if manifest.intent.verification is None or not manifest.intent.verification.promise:
            click.echo(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": "No verification configured for this session",
                    }
                )
            )
            return
        # Has verification config, proceed with bypass
        effective = None

    # Match existing behavior contract: if no verification is configured, refuse.
    if effective is not None:
        if not effective.verification or not effective.verification.promise:
            click.echo(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": "No verification configured for this session",
                    }
                )
            )
            return

        if effective.verification.bypass:
            click.echo(json.dumps({"decision": "block", "reason": "Verification already bypassed"}))
            return

    def _mutate(m: object) -> None:
        if not isinstance(m, SessionState):
            raise TypeError(f"Expected SessionState, got {type(m)}")
        # Use set_override to preserve original intent while bypassing
        set_override(m.overrides, "verification.bypass", True)

    try:
        store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_mutate)
    except FileLockTimeoutError:
        click.echo(json.dumps({"decision": "block", "reason": "Session locked, try again"}))
        return
    except Exception as e:
        click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
        return

    click.echo(
        json.dumps(
            {
                "decision": "block",
                "reason": "Verification bypass enabled. Session can now exit without promise.",
            }
        )
    )


def _handle_cmd_clean(argv: list[str]) -> None:
    """Handle `%clean` — read-only listing of orphans scoped to current project.

    Always emits `{decision:block}` with the dry-run report.
    No destructive operations from within a session.
    """
    from forge.core.ops.context import ExecutionContext
    from forge.core.ops.gc import CleanError, collect_clean_report

    scope = "project"
    for i, arg in enumerate(argv):
        if arg.startswith("--scope="):
            scope = arg.split("=", 1)[1].lower()
            break
        if arg == "--scope" and i + 1 < len(argv):
            scope = argv[i + 1].lower()
            break

    try:
        ctx = ExecutionContext.from_cwd()
        report = collect_clean_report(ctx=ctx, scope=scope)
    except (CleanError, Exception) as e:
        click.echo(json.dumps({"decision": "block", "reason": f"Error: {e}"}))
        return

    if report.is_clean:
        click.echo(json.dumps({"decision": "block", "reason": "Nothing to clean."}))
        return

    lines = [f"Clean report (scope: {report.scope}):"]
    for cat in report.categories:
        if cat.count > 0:
            lines.append(f"  {cat.description}: {cat.count}")
    lines.append(f"\nTotal: {report.total_count} objects")
    lines.append("\nRun `forge clean --yes` from terminal to clean.")

    click.echo(json.dumps({"decision": "block", "reason": "\n".join(lines)}))
