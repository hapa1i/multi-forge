"""Launch notice naming the model that judges Claude Code auto-mode actions."""

from __future__ import annotations

import click
from rich.markup import escape

from forge.cli.output import err_console
from forge.cli.statusline.routing import predict_route
from forge.core.ops.claude_session import ClaudeLaunchReady
from forge.proxy.runtime_truth import ProxyRuntimeTruth

_SESSION_LAUNCH_COMMANDS = frozenset({"start", "resume", "fork", "incognito"})


def print_auto_mode_judge_notice(
    classifier_model: str,
    runtime: ProxyRuntimeTruth | None,
    *,
    projected_tier: str | None = None,
) -> None:
    """Print one stderr line naming the backend that will judge auto-mode actions.

    ``runtime`` must describe the proxy this launch uses; pass None when no
    matching snapshot is available so the notice names only the request model.
    """
    route = predict_route(classifier_model, runtime, authoritative=runtime is not None, projected_tier=projected_tier)
    if route.model and route.model != classifier_model:
        tier = f", {route.tier} tier" if route.tier else ""
        judge = f"{route.model} (requested as {classifier_model}{tier})"
    elif route.model or "/" in classifier_model:
        judge = f"{classifier_model} through this proxy"
    else:
        judge = f"the model this proxy serves for {classifier_model}"
    err_console.print(
        f"[dim]Auto mode: actions are judged by {escape(judge)}; "
        "Forge turned off the server-side check for translated proxies.[/dim]",
        soft_wrap=True,
    )


def print_session_auto_mode_judge_notice(event: ClaudeLaunchReady) -> None:
    """Render the auto-mode judge notice for an interactive managed session launch."""
    classifier_model = event.auto_mode_classifier_model
    ctx = click.get_current_context(silent=True)
    if (
        classifier_model is None
        or ctx is None
        or ctx.parent is None
        or ctx.parent.command.name != "session"
        or ctx.command.name not in _SESSION_LAUNCH_COMMANDS
        or ctx.params.get("no_launch")
        or ctx.params.get("json_output")
        or ctx.params.get("json")
    ):
        return
    runtime = event.runtime
    if runtime is not None and (
        not runtime.is_proxy
        or (event.template is not None and runtime.template != event.template)
        or (event.proxy_id is not None and runtime.proxy_id != event.proxy_id)
    ):
        runtime = None
    # Matches the X-Forge-Model-Tier projection that classifier requests also carry.
    route = event.model_route
    projected_tier = route.selected_tier if route and route.kind == "proxy" and event.direct_model is None else None
    print_auto_mode_judge_notice(classifier_model, runtime, projected_tier=projected_tier)
