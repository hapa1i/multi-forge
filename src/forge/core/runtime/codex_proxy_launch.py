"""Verified Responses listener selection and native Codex provider arguments."""

from __future__ import annotations

import json
import subprocess
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from forge.core.models.catalog import model_exists
from forge.core.models.model_reference import strip_transport_model_suffix
from forge.core.models.model_routes import get_model_route_candidates
from forge.core.reactive.env import RunIdentity
from forge.core.run_id import (
    FORGE_ROOT_RUN_ID_HEADER,
    FORGE_RUN_ID_HEADER,
    is_valid_run_id,
)
from forge.core.runtime.codex_preflight import (
    CodexPreflight,
    codex_proxy_contract_blocker,
    preflight_codex,
)
from forge.core.runtime.codex_usage import CodexUsageBaseline
from forge.core.wire_shapes import OPENAI_RESPONSES_PASSTHROUGH
from forge.session.models import ProxyIntent

CODEX_PROXY_TOKEN_VAR = "FORGE_CODEX_PROXY_TOKEN"


@dataclass(frozen=True)
class CodexProxyLaunch:
    proxy_id: str
    template: str
    base_url: str
    backend_id: str
    provider: str
    requested_model: str
    dispatched_model: str
    required_zdr: bool | None
    notices: tuple[str, ...] = ()
    wire_shape: str = OPENAI_RESPONSES_PASSTHROUGH
    usage_baseline: CodexUsageBaseline | None = None

    def provider_args(
        self,
        run: RunIdentity,
        extra_args: Sequence[str],
        *,
        env: Mapping[str, str],
        cwd: str,
    ) -> list[str]:
        """Codex global options; run headers are consumed at the Forge listener."""
        if not is_valid_run_id(run.run_id) or not is_valid_run_id(run.root_run_id):
            raise ValueError("Managed Codex proxy launch requires a valid Forge run and root ID.")
        args = provider_overrides(self.base_url)
        headers = f'{{"{FORGE_RUN_ID_HEADER}"="{run.run_id}","{FORGE_ROOT_RUN_ID_HEADER}"="{run.root_run_id}"}}'
        args += ["-c", f"model_providers.forge_proxy.http_headers={headers}"]
        if self.required_zdr is not None:
            args += openrouter_launch_defaults(extra_args, env=env, cwd=cwd)
        args += responses_policy_args(self.required_zdr)
        if passthrough_model(extra_args) is None:
            args += ["-m", self.requested_model]
        return args


def resolve_codex_proxy_launch(
    *,
    proxy_name: str | None = None,
    binding: ProxyIntent | None = None,
    existing_only: bool = False,
    extra_args: Sequence[str] = (),
    replay: tuple[str, str] | None = None,
) -> tuple[CodexPreflight, CodexProxyLaunch]:
    """Resolve a new instance, or inspect only the instance pinned in a bound session."""
    from forge.proxy.proxies import ProxyRegistryStore, ProxyResolutionError
    from forge.proxy.proxy_orchestrator import (
        ProxyIdentityMismatchError,
        ProxyNotResponsesCapableError,
        ProxyUnreachableError,
        ensure_proxy,
        read_responses_listener,
    )

    if (proxy_name is None) == (binding is None):
        raise ValueError("Select either a new proxy or a recorded proxy binding.")
    explicit_model = passthrough_model(extra_args)
    if explicit_model is not None and not explicit_model.strip():
        raise ValueError("Codex needs a nonempty model slug. Supply a model or omit the model option.")
    preflight = preflight_codex(loopback_auth=True)
    if not preflight.ready:
        raise ValueError(preflight.blocking_reason or "Codex proxy launch is unavailable.")
    if not preflight.version or not preflight.version[0].isdigit():
        raise ValueError("Could not establish the Codex CLI version for managed proxy routing.")
    if blocker := codex_proxy_contract_blocker(preflight.version):
        raise ValueError(blocker)
    if binding is not None:
        if not binding.proxy_id or not binding.template or not binding.base_url:
            raise ValueError("Incomplete Codex proxy binding. Restore the original session or start a fresh session.")
        if replay is None:
            raise ValueError("Cannot establish the model to replay on this thread. Start a fresh session.")
        proxy_id, template, base_url = (
            binding.proxy_id,
            binding.template,
            binding.base_url,
        )
    else:
        assert proxy_name is not None
        if existing_only:
            entry = ProxyRegistryStore().read().proxies.get(proxy_name)
            if entry is None:
                raise ValueError(f"Proxy {proxy_name!r} is not registered. Start it and retry with its ID.")
        else:
            try:
                entry, _ = ensure_proxy(proxy_name)
            except ProxyResolutionError as error:
                raise ValueError(str(error)) from error
        proxy_id, template, base_url = entry.proxy_id, entry.template, entry.base_url
    ProxyIntent(template=template, base_url=base_url, proxy_id=proxy_id)
    try:
        listener = read_responses_listener(base_url, expected_proxy_id=proxy_id, expected_template=template)
    except (
        ProxyIdentityMismatchError,
        ProxyNotResponsesCapableError,
        ProxyUnreachableError,
    ) as error:
        raise ValueError(
            f"Could not verify Responses proxy {proxy_id!r}: {error}. Restore and start the recorded proxy "
            f"with 'forge proxy start {proxy_id}', or start a fresh session for a different route."
        ) from error

    if (
        not isinstance(listener.backend_id, str)
        or not listener.backend_id.strip()
        or listener.provider not in ("openrouter", "litellm")
    ):
        raise ValueError(f"Proxy {proxy_id!r} did not identify its Responses provider and backend.")
    selection = responses_model_selection(
        listener.default_model,
        listener.policy,
        extra_args,
        replay_model=replay[0] if replay else None,
    )
    if not selection.requested or not selection.dispatched:
        raise ValueError(
            f"Proxy {proxy_id!r} has no model configured for its default tier. Configure the proxy default."
        )
    if replay and selection.requested == replay[0] and selection.dispatched != replay[1]:
        raise ValueError(
            f"Proxy {proxy_id!r} previously dispatched {replay[1]!r} for {replay[0]!r} and now dispatches "
            f"{selection.dispatched!r}. Restore the original mapping or start a fresh session."
        )
    return replace(preflight, proxy_responses="proxy_supported"), CodexProxyLaunch(
        proxy_id,
        template,
        base_url,
        listener.backend_id,
        listener.provider,
        selection.requested,
        selection.dispatched,
        listener.policy.get("required_zdr"),
        (*selection.notices, selection.fallback_notice) if selection.fallback_notice else selection.notices,
    )


@dataclass(frozen=True)
class ResponsesModelSelection:
    default: str | None
    requested: str | None
    dispatched: str | None
    notices: tuple[str, ...]

    @property
    def fallback_notice(self) -> str | None:
        if self.requested != self.dispatched:
            return f"OpenRouter ZDR fallback: requested {self.requested}, dispatching {self.dispatched}."
        return None


def responses_model_selection(
    default_model: str | None,
    policy: Mapping[str, Any],
    extra_args: Sequence[str],
    *,
    replay_model: str | None = None,
) -> ResponsesModelSelection:
    """Keep the exact client slug independent from OpenRouter's policy-mapped destination."""
    default = policy.get("requested_default_model") or default_model
    requested = passthrough_model(extra_args) or replay_model or default
    dispatched = requested
    if requested and policy.get("required_zdr") is True:
        dispatched = policy["zdr_fallbacks"].get(strip_transport_model_suffix(requested), requested)
    notices = []
    if policy.get("messages_inspected"):
        notices.append("Messages inspection is enabled. Codex Responses requests have no body audit.")
    if policy.get("required_zdr") is False:
        notices.append("OpenRouter allow_non_zdr permits hosted tools and caller-supplied routing.")
    if policy.get("on_unreported_cost") == "allow":
        notices.append("Unreported OpenRouter account charges cannot count toward this proxy's spend caps.")
    return ResponsesModelSelection(default, requested, dispatched, tuple(notices))


def responses_policy_args(required_zdr: bool | None) -> list[str]:
    return ["-c", 'web_search="disabled"'] if required_zdr else []


def provider_overrides(base_url: str) -> list[str]:
    proxy_v1 = f"{base_url.rstrip('/')}/v1"
    return [
        "-c",
        "model_provider=forge_proxy",
        "-c",
        'model_providers.forge_proxy.name="Forge Proxy"',
        "-c",
        f"model_providers.forge_proxy.base_url={json.dumps(proxy_v1)}",
        "-c",
        'model_providers.forge_proxy.wire_api="responses"',
        "-c",
        f'model_providers.forge_proxy.env_key="{CODEX_PROXY_TOKEN_VAR}"',
    ]


def openrouter_launch_defaults(passthrough: Sequence[str], *, env: Mapping[str, str], cwd: str) -> list[str]:
    """Set standard service for this launch and opt into embedded mode on CLIs that support it."""
    defaults = ["-c", 'service_tier="default"']
    for arg in passthrough:
        if arg == "--":
            break
        if arg in ("--no-daemon", "--remote") or arg.startswith("--remote="):
            return defaults

    # Older supported Codex binaries already run embedded and reject --no-daemon.
    try:
        help_result = subprocess.run(
            ["codex", "--help"],
            env=env,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return defaults
    if help_result.returncode == 0 and b"--no-daemon" in help_result.stdout.split():
        defaults.append("--no-daemon")
    return defaults


def passthrough_model(passthrough: Sequence[str]) -> str | None:
    """Codex gives the model flag precedence over the last top-level model override."""
    option = _model_option(passthrough)
    return option.value if option is not None else None


def expand_openrouter_model_arg(args: tuple[str, ...]) -> tuple[str, ...]:
    """Give the sessionless Codex client the catalog's OpenRouter slug for a short model name."""
    option = _model_option(args)
    if option is None or "/" in option.value or not model_exists(option.value):
        return args
    routes = get_model_route_candidates(option.value)
    slug = next((route.model_ref for route in routes if route.source_id == "openrouter"), None)
    if slug is None:
        return args
    value = f"model={json.dumps(slug)}" if option.flag == "-c" else slug
    result = list(args)
    result[option.span] = [option.flag, value]
    return tuple(result)


@dataclass(frozen=True)
class _ModelOption:
    value: str
    flag: str
    span: slice


def _model_option(passthrough: Sequence[str]) -> _ModelOption | None:
    config_model = None
    args = iter(enumerate(passthrough))
    for start, arg in args:
        if arg == "--":
            break
        end = start
        if arg in ("-m", "--model", "-c", "--config"):
            flag = arg
            end, value = next(args, (start, ""))
        elif arg.startswith(("--model=", "--config=")):
            flag, _, value = arg.partition("=")
        elif arg.startswith(("-m", "-c")) and len(arg) > 2:
            flag, value = arg[:2], arg[2:].removeprefix("=")
        else:
            continue
        span = slice(start, end + 1)
        if flag in ("-m", "--model"):
            return _ModelOption(value, "-m", span)
        if end > start and value == "--":
            break
        name, sep, value = value.partition("=")
        if sep and name.strip() == "model":
            try:
                parsed = tomllib.loads(f"value = {value}")["value"]
            except tomllib.TOMLDecodeError:
                parsed = value.strip()
            config_model = _ModelOption(parsed if isinstance(parsed, str) else value.strip(), "-c", span)
    return config_model
