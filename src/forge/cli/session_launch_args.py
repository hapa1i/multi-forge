"""Click wiring for launch-only ``--effort`` and ``--`` runtime passthrough."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

import click

from forge.cli.output import err_console, print_error
from forge.core.ops.session_model_routing import ResolvedModelRoute
from forge.core.runtime.launch_args import (
    ALL_EFFORT_LEVELS,
    LaunchArgsError,
    LaunchRuntime,
    RuntimeLaunchArgs,
    validate_launch_args,
)
from forge.session.models import AuthorityIntent

PASSTHROUGH_META_KEY = "forge.runtime_passthrough"


class RuntimePassthroughCommand(click.Command):
    """A command whose ``--`` tail is forwarded to the launched runtime.

    Click binds tokens after ``--`` to positional parameters, so an optional
    ``NAME`` argument would capture the first runtime flag. The tail is split off
    before Click parses the command line and stored on the context instead.
    """

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        passthrough: tuple[str, ...] = ()
        if "--" in args:
            split = args.index("--")
            passthrough = tuple(args[split + 1 :])
            args = args[:split]
        ctx.meta[PASSTHROUGH_META_KEY] = passthrough
        return super().parse_args(ctx, args)

    def collect_usage_pieces(self, ctx: click.Context) -> list[str]:
        return [*super().collect_usage_pieces(ctx), "[-- RUNTIME_ARGS]..."]


def effort_option(f: Callable[..., Any]) -> Callable[..., Any]:
    return click.option(
        "--effort",
        type=click.Choice(ALL_EFFORT_LEVELS),
        default=None,
        help="Reasoning effort for this launch only (Claude: low-max; Codex: none-max).",
    )(f)


def checked_launch_args(
    ctx: click.Context,
    *,
    runtime: LaunchRuntime,
    authority: AuthorityIntent | None,
) -> RuntimeLaunchArgs:
    """Return validated launch arguments, or print the refusal and exit 1.

    ``authority`` is the launched session's effective authority: the creation flag,
    the resumed manifest's intent, or a derived child's inherited/explicit value.
    Call this before any session or proxy mutation.
    """
    args = RuntimeLaunchArgs(
        effort=ctx.params.get("effort"),
        passthrough=tuple(ctx.meta.get(PASSTHROUGH_META_KEY, ())),
    )
    if ctx.params.get("no_launch") and not args.is_empty:
        print_error("--effort and runtime arguments after '--' apply only to a launch; drop them or --no-launch")
        sys.exit(1)
    try:
        return validate_launch_args(args, runtime=runtime, advisory=authority is not None and authority.is_advisory)
    except LaunchArgsError as e:
        print_error(str(e))
        sys.exit(1)


def warn_if_effort_clamped(launch_args: RuntimeLaunchArgs, route: ResolvedModelRoute | None) -> None:
    """Warn before launch when a translated route's model cannot express ``--effort`` exactly.

    Only a selected model route names the upstream model at launch; otherwise Claude
    Code picks a tier per request and the proxy clamps without a launch-time warning.
    """
    effort = launch_args.effort
    if effort is None or route is None or route.kind != "proxy" or route.selected_model is None:
        return
    from forge.core.reactive.env import resolve_proxy_wire_shape
    from forge.core.wire_shapes import ANTHROPIC_PASSTHROUGH
    from forge.proxy.reasoning import (
        clamp_effort_to_supported,
        supported_efforts_for_model,
    )

    if resolve_proxy_wire_shape(proxy_id=route.proxy_id, template=route.proxy_template) == ANTHROPIC_PASSTHROUGH:
        return
    supported = supported_efforts_for_model(route.selected_model)
    clamped = clamp_effort_to_supported(effort, supported)
    if supported is not None and clamped != effort:
        err_console.print(
            f"[yellow]Warning:[/yellow] {route.selected_model} supports effort {', '.join(supported)}; "
            f"--effort {effort} will run as {clamped}."
        )
