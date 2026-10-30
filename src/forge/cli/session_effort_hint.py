"""Launch-only guidance for translated managed Claude sessions."""

from __future__ import annotations

import shlex
from pathlib import Path

import click

from forge.cli.output import err_console, print_tip
from forge.core.ops.claude_session import ClaudeLaunchReady
from forge.core.wire_shapes import ANTHROPIC_PASSTHROUGH
from forge.session.artifacts import resolve_forge_root


def print_derived_effort_hint(event: ClaudeLaunchReady) -> None:
    """Explain derived effort using the existing launch-time proxy snapshot."""
    ctx = click.get_current_context(silent=True)
    runtime = event.runtime
    if (
        ctx is None
        or ctx.parent is None
        or ctx.parent.command.name != "session"
        or ctx.command.name not in {"start", "resume", "fork", "incognito"}
        or ctx.params.get("effort") is not None
        or ctx.params.get("no_launch")
        or ctx.params.get("json_output")
        or ctx.params.get("json")
        or not (event.template or event.proxy_id)
        or runtime is None
        or not runtime.is_proxy
        or runtime.wire_shape is None
        or runtime.wire_shape == ANTHROPIC_PASSTHROUGH
    ):
        return
    if event.template is not None and runtime.template != event.template:
        return
    if event.proxy_id is not None and runtime.proxy_id != event.proxy_id:
        return
    proxy_runtime = runtime.raw.get("runtime")
    defaults = proxy_runtime.get("llm_defaults_by_tier") if isinstance(proxy_runtime, dict) else None
    defaults = defaults if isinstance(defaults, dict) else {}
    projected_tier = event.model_route.selected_tier if event.model_route else None
    minimum = "the selected tier minimum"
    floors = []
    for tier in ("haiku", "sonnet", "opus"):
        if projected_tier is not None and projected_tier != tier:
            continue
        tier_defaults = defaults.get(tier)
        floor = tier_defaults.get("reasoning_effort") if isinstance(tier_defaults, dict) else None
        if isinstance(floor, str) and floor in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}:
            floors.append(f"{tier}: {floor}")
    if floors:
        label = "configured minimums: " if projected_tier is None else ""
        minimum += f" ({label}{', '.join(floors)})"

    # Creation has already committed, including unnamed forks and fresh resumes.
    # Durable route intent makes a short resume command sufficient on the next launch.
    args = ["forge", "session", "resume", event.session]
    guidance = "After exiting, opt in to client effort with:"
    if event.incognito:
        args = ["forge", "session", "incognito", "--proxy", event.proxy_id or event.template or ""]
        if event.model_route is not None:
            args.extend(["--model", event.model_route.requested_model, "--model-tier", event.model_route.selected_tier])
        elif event.direct_model is not None:
            args.extend(["--model", event.direct_model])
        guidance = "This incognito session is deleted on exit. Opt in on a new incognito launch with:"
    args.extend(["--effort", "<level>"])
    command = shlex.join(args)
    if not event.incognito and event.forge_root and Path(event.forge_root).resolve() != resolve_forge_root(Path.cwd()):
        command = f"cd {shlex.quote(event.forge_root)} && {command}"
    print_tip(
        f"Effort is derived from thinking and {minimum}.",
        guidance,
        commands=[command],
        blank_before=False,
        console=err_console,
    )
