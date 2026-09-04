"""Recovery rendering for unavailable persisted session model routes."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, replace

from rich.markup import escape

from forge.cli.output import err_console, print_error_with_tip
from forge.core.ops.session_model_routing import (
    SessionModelRoutingError,
    plan_session_model_route,
    preserved_model_route_request,
)
from forge.session import SessionState


@dataclass(frozen=True)
class SessionRouteRecoveryAction:
    """A route-neutral lifecycle action that can be retried with a replacement proxy route."""

    argv: tuple[str, ...]

    @classmethod
    def resume(
        cls,
        session_name: str,
        *,
        fresh: bool = False,
        child_name: str | None = None,
        strategy: str | None = None,
        drop_last: int | None = None,
        depth: str | None = None,
        resume_mode: str | None = None,
        review: bool = False,
        force: bool = False,
        memory_flag: str | None = None,
        authority_role: str | None = None,
        authority_tier: str | None = None,
    ) -> SessionRouteRecoveryAction:
        """Build a route-neutral resume action from explicitly supplied options."""
        argv = ["forge", "session", "resume", session_name]
        if fresh:
            argv.append("--fresh")
        if child_name is not None:
            argv.extend(("--child-name", child_name))
        if strategy is not None:
            argv.extend(("--strategy", strategy))
        if drop_last is not None:
            argv.extend(("--drop-last", str(drop_last)))
        if depth is not None:
            argv.extend(("--depth", depth))
        if resume_mode is not None:
            argv.extend(("--resume-mode", resume_mode))
        if review:
            argv.append("--review")
        if force:
            argv.append("--force")
        if memory_flag is not None:
            argv.extend(("--memory", memory_flag))
        if authority_role is not None:
            argv.extend(("--authority", authority_role))
        if authority_tier is not None:
            argv.extend(("--authority-tier", authority_tier))
        return cls(tuple(argv))

    def with_proxy(self, proxy: str) -> str:
        return shlex.join((*self.argv, "--proxy", proxy))

    def with_proxy_route(self, *, model: str, model_tier: str | None, proxy: str) -> str:
        argv = [*self.argv, "--model", model]
        if model_tier is not None:
            argv.extend(("--model-tier", model_tier))
        argv.extend(("--proxy", proxy))
        return shlex.join(argv)


def _persisted_proxy_recovery_commands(
    *,
    manifest: SessionState,
    template: str | None,
    base_url: str | None,
    proxy_id: str | None,
    allow_restart: bool,
    recovery_action: SessionRouteRecoveryAction,
) -> tuple[list[str], bool]:
    """Build only recovery commands whose recorded proxy identity still matches."""
    commands: list[str] = []
    has_reroute_command = False
    if allow_restart and proxy_id is not None and template != "" and base_url is not None:
        from forge.config.loader import load_proxy_instance_config

        try:
            recorded_config = load_proxy_instance_config(proxy_id)
        except Exception:
            recorded_config = None
        if (
            recorded_config is not None
            and recorded_config.proxy_endpoint.rstrip("/") == base_url.rstrip("/")
            and (template is None or recorded_config.template == template)
        ):
            commands.append(f"forge proxy start {shlex.quote(proxy_id)}")
    if template:
        from forge.config.loader import template_exists

        try:
            template_available = template_exists(template)
        except Exception:
            template_available = False
        if template_available:
            route = manifest.intent.launch.model_route if manifest.intent.launch is not None else None
            if route is None or route.kind != "proxy":
                commands.append(recovery_action.with_proxy(template))
                has_reroute_command = True
            else:
                from forge.core.ops.session_model_routing import inspect_proxy_reference

                try:
                    recovery_model = preserved_model_route_request(manifest)
                except SessionModelRoutingError:
                    return commands, has_reroute_command
                snapshot = None
                try:
                    snapshot = inspect_proxy_reference(template)
                    # Ignore a mutable proxy default while deciding whether the
                    # stored tier is needed to identify the same route.
                    implicit = plan_session_model_route(
                        recovery_model,
                        explicit_proxy=replace(snapshot, default_tier=None),
                    )
                    include_tier = implicit.selected_tier != route.selected_tier
                except SessionModelRoutingError:
                    include_tier = True
                except Exception:
                    snapshot = None
                    include_tier = True

                try:
                    if snapshot is None:
                        raise SessionModelRoutingError("proxy template is not inspectable")
                    if include_tier:
                        plan_session_model_route(
                            recovery_model,
                            model_tier=route.selected_tier,
                            explicit_proxy=snapshot,
                        )
                    commands.append(
                        recovery_action.with_proxy_route(
                            model=recovery_model,
                            model_tier=route.selected_tier if include_tier else None,
                            proxy=template,
                        )
                    )
                    has_reroute_command = True
                except SessionModelRoutingError:
                    pass
    return commands, has_reroute_command


def _render_persisted_proxy_refusal(
    *,
    manifest: SessionState,
    error: object,
    template: str | None,
    base_url: str | None,
    proxy_id: str | None,
    allow_restart: bool,
    parent_name: str | None = None,
    recovery_action: SessionRouteRecoveryAction | None = None,
) -> None:
    """Render the shared fail-closed recovery surface for a persisted proxy route."""
    default_action = SessionRouteRecoveryAction.resume(manifest.name)
    action = recovery_action or default_action
    caller_action_supplied = action != default_action
    commands, has_reroute_command = _persisted_proxy_recovery_commands(
        manifest=manifest,
        template=template,
        base_url=base_url,
        proxy_id=proxy_id,
        allow_restart=allow_restart,
        recovery_action=action,
    )
    route = manifest.intent.launch.model_route if manifest.intent.launch is not None else None
    route_request_invalid = False
    if route is not None and route.kind == "proxy":
        try:
            raw_recovery_model = preserved_model_route_request(manifest)
        except SessionModelRoutingError:
            raw_recovery_model = "<catalog-id>"
            route_request_invalid = True
        if caller_action_supplied:
            retry = escape(
                action.with_proxy_route(
                    model=raw_recovery_model,
                    model_tier=None,
                    proxy="<proxy_id-or-template>",
                )
            )
            unavailable_tip = (
                "Repair the recorded model-route request and proxy identity, or rerun the intended action with a "
                f"replacement route: {retry}. Add --model-tier {route.selected_tier} when that model is available "
                "through multiple tiers."
            )
        else:
            recovery_model = escape(raw_recovery_model if route_request_invalid else shlex.quote(raw_recovery_model))
            unavailable_tip = (
                "Repair the recorded model-route request and proxy identity, or select a replacement with "
                f"--model {recovery_model} --proxy <proxy_id-or-template>; add "
                f"--model-tier {route.selected_tier} when that model is available through multiple tiers."
            )
    else:
        if caller_action_supplied:
            retry = escape(action.with_proxy("<proxy_id-or-template>"))
            unavailable_tip = f"Repair the recorded proxy identity, or rerun the intended action as {retry}."
        else:
            unavailable_tip = "Repair the recorded proxy identity, or retry with --proxy <proxy_id-or-template>."
    tips = ["Use an applicable recovery command below, then retry."] if commands else []
    if (
        not commands
        or route_request_invalid
        or (route is not None and route.kind == "proxy" and not has_reroute_command)
    ):
        tips.append(unavailable_tip)
    if parent_name is not None:
        tips.append(
            f"Child session '{manifest.name}' was created and retained. Resume that child after recovery; "
            f"retrying parent '{parent_name}' creates another child."
        )
    tips.append("Forge did not launch Claude or replace the recorded proxy route.")
    print_error_with_tip(
        f"Persisted proxy route for session '{manifest.name}' is unavailable: {error}",
        *tips,
        commands=commands,
        console=err_console,
    )


def _render_replayed_model_route_refusal(
    *,
    manifest: SessionState,
    error: object,
    recovery_action: SessionRouteRecoveryAction | None = None,
) -> None:
    """Render recovery for a read-only failure while replaying stored proxy intent."""
    intent_proxy = manifest.intent.proxy
    template = (intent_proxy.template or None) if intent_proxy is not None else None
    base_url = (intent_proxy.base_url or None) if intent_proxy is not None else None
    _render_persisted_proxy_refusal(
        manifest=manifest,
        error=error,
        template=template,
        base_url=base_url,
        proxy_id=None,
        allow_restart=False,
        recovery_action=recovery_action,
    )
