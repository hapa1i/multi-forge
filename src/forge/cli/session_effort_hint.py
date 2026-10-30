"""Launch-only guidance for translated managed Claude sessions."""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass

import click
import httpx
from rich.markup import escape

from forge.cli.output import err_console, print_tip
from forge.cli.session_launch_args import LIFECYCLE_ARGV_META_KEY
from forge.core.ops.session_model_routing import ResolvedModelRoute
from forge.core.wire_shapes import ANTHROPIC_PASSTHROUGH, VALID_WIRE_SHAPES
from forge.session.models import SessionState

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class SessionEffortHint:
    """Keep prepared routing facts until the presenter's actual launch boundary."""

    projected_tier: str | None = None
    base_url: str | None = None
    template: str | None = None
    proxy_id: str | None = None

    def set_route(self, base_url: str | None, template: str | None, proxy_id: str | None = None) -> None:
        """Capture the route selected by session preparation."""
        self.base_url = base_url
        self.template = template
        self.proxy_id = proxy_id

    def show(self) -> None:
        """Render guidance using the current lifecycle command's launch arguments."""
        print_derived_effort_hint(
            base_url=self.base_url,
            template=self.template,
            proxy_id=self.proxy_id,
            projected_tier=self.projected_tier,
        )


def selected_tier(state: SessionState, selection: ResolvedModelRoute | None) -> str | None:
    """Use explicit route selection before the resumed session's stored tier."""
    if selection is not None:
        return selection.selected_tier
    model_route = state.intent.launch.model_route if state.intent.launch else None
    return model_route.selected_tier if model_route is not None else None


def print_derived_effort_hint(
    *,
    base_url: str | None,
    template: str | None,
    proxy_id: str | None,
    projected_tier: str | None = None,
) -> None:
    """Explain derived effort once for a proven translated managed launch."""
    ctx = click.get_current_context(silent=True)
    if (
        ctx is None
        or ctx.parent is None
        or ctx.parent.command.name != "session"
        or ctx.command.name not in {"start", "resume", "fork", "incognito"}
        or ctx.params.get("effort") is not None
        or ctx.params.get("no_launch")
        or ctx.params.get("json_output")
        or ctx.params.get("json")
        or not base_url
        or not (template or proxy_id)
    ):
        return
    raw_argv = ctx.meta.get(LIFECYCLE_ARGV_META_KEY)
    if not isinstance(raw_argv, tuple):
        return
    try:
        response = httpx.get(base_url.rstrip("/") + "/", timeout=0.5)
        response.raise_for_status()
        info = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Guidance is optional: a failed live probe must not block an admitted launch.
        logger.debug("Could not inspect launch effort policy: %s", exc)
        return
    if not isinstance(info, dict) or info.get("is_proxy") is not True:
        return
    if template is not None and info.get("template") != template:
        return
    proxy = info.get("proxy")
    if not isinstance(proxy, dict) or (proxy_id is not None and proxy.get("proxy_id") != proxy_id):
        return
    wire_shape = info.get("wire_shape")
    if not isinstance(wire_shape, str) or wire_shape not in VALID_WIRE_SHAPES or wire_shape == ANTHROPIC_PASSTHROUGH:
        return
    runtime = info.get("runtime")
    runtime = runtime if isinstance(runtime, dict) else {}
    defaults = runtime.get("llm_defaults_by_tier")
    defaults = defaults if isinstance(defaults, dict) else {}
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
    args = list(raw_argv)
    boundary = args.index("--") if "--" in args else len(args)
    args[boundary:boundary] = ["--effort", "<level>"]
    command = " ".join(_quote_argument(arg) for arg in ["forge", "session", ctx.command.name, *args])
    print_tip(
        f"Effort is derived from thinking and {minimum}; use {escape(command)} to opt in to client effort.",
        blank_before=False,
        console=err_console,
        soft_wrap=True,
    )


def _quote_argument(value: str) -> str:
    if "\n" not in value and "\r" not in value:
        return shlex.quote(value)
    # ANSI-C quoting preserves multiline prompts in bash/zsh without splitting the hint.
    escaped = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")
    return f"$'{escaped}'"
