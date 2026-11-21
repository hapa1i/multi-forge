"""Request policy and provider diagnostics for direct OpenRouter Responses."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi.responses import JSONResponse

from forge.core.llm.clients.openai_compat import extract_reported_cost_usd
from forge.proxy.model_routes import model_for_zdr_policy


def unreported_cost_message(proxy_id: str) -> str:
    return (
        "OpenRouter Responses cost is unavailable. To allow uncounted spend, run "
        f"forge proxy set {proxy_id} costs.on_unreported_cost=allow and restart the proxy."
    )


@dataclass
class OpenRouterResponseEvidence:
    """Correlate one physical create and retain only its first terminal charge."""

    on_missing_cost: Callable[[], None] | None = None
    response_id: str | None = None
    generation_id: str | None = None
    selected_provider: str | None = None
    cost_micros: int | None = None
    terminal_seen: bool = False

    def observe_unary(self, response: dict[str, Any] | None) -> bool:
        """Check the synchronous outcome and account for ambiguous successful HTTP replies."""
        data = response or {}
        status = data.get("status")
        self.observe(data, status)
        if self.terminal_seen:
            return True
        # An active job can incur further charges and this route cannot poll it.
        # For malformed final replies retain any explicit account charge.
        self._observe_charge(None if status in ("queued", "in_progress") else data.get("usage"))
        return False

    def observe(self, response: object, status: object) -> None:
        data = response if isinstance(response, dict) else {}
        if isinstance(response_id := data.get("id"), str) and response_id:
            self.response_id = response_id
        metadata = data.get("openrouter_metadata")
        endpoints = metadata.get("endpoints") if isinstance(metadata, dict) else None
        available = endpoints.get("available") if isinstance(endpoints, dict) else None
        if isinstance(available, list):
            for route in available:
                if isinstance(route, dict) and route.get("selected") is True:
                    provider = route.get("provider")
                    if isinstance(provider, str) and provider:
                        self.selected_provider = provider
                        break
        if self.terminal_seen or status not in (
            "completed",
            "incomplete",
            "failed",
            "cancelled",
        ):
            return
        self.terminal_seen = True
        if status in ("completed", "incomplete"):
            self._observe_charge(data.get("usage"))

    def _observe_charge(self, usage: Any) -> None:
        try:
            cost = extract_reported_cost_usd(usage)
        except OverflowError:
            cost = None
        if cost is not None and cost >= 0 and math.isfinite(cost * 1_000_000):
            self.cost_micros = int((Decimal(str(cost)) * 1_000_000).to_integral_value(rounding=ROUND_HALF_UP))
        elif self.on_missing_cost:
            self.on_missing_cost()

    def provider_meta(self) -> dict[str, Any]:
        return {
            "provider": "openrouter",
            "provider_response_id": self.response_id,
            "provider_generation_id": self.generation_id,
            "selected_provider": self.selected_provider,
        }


def validate_base(base: str) -> None:
    """Validate the configured destination before resolving or attaching a bearer."""
    try:
        parsed = urlsplit(base)
        url = httpx.URL(base)
        parsed.port
    except (ValueError, httpx.InvalidURL):
        raise ValueError("OpenRouter base URL is malformed.") from None
    if (
        not parsed.hostname
        or not url.host
        or parsed.username is not None
        or parsed.scheme not in {"http", "https"}
        or any(c in base for c in ("?", "#", "\\"))
        or any(c.isspace() or ord(c) < 32 for c in base)
    ):
        raise ValueError("Configure an OpenRouter HTTP(S) base URL without credentials, query or fragment.")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Remote OpenRouter bases require HTTPS.")


def _validate_tools(tools: Any) -> None:
    if not isinstance(tools, list):
        raise ValueError("Expected a list of Responses tools.")
    for tool in tools:
        kind = tool.get("type") if isinstance(tool, dict) else None
        if kind not in ("function", "custom", "namespace"):
            raise ValueError(
                f"Tool type {kind!r} is unavailable under required ZDR. Remove it or set allow_non_zdr=true."
            )
        if kind == "namespace" or "tools" in tool:
            _validate_tools(tool.get("tools"))


def prepare_request(body: dict[str, Any], provider: Any) -> dict[str, Any]:
    """Apply the selected model, tool and identifier policies to one create."""
    result = body.copy()
    result.pop("client_metadata", None)
    result.pop("prompt_cache_key", None)
    model = result.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Supply an OpenRouter model slug.")
    if body.get("background"):
        raise ValueError("Background Responses require polling. This proxy supports synchronous creates and streaming.")
    if provider.allow_non_zdr:
        return result
    if "tools" in body:
        _validate_tools(body["tools"])
    items = body.get("input")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("type") == "additional_tools":
                _validate_tools(item.get("tools"))
    routing = result.get("provider", {})
    if not isinstance(routing, dict):
        raise ValueError("The OpenRouter provider field must be an object.")
    result["provider"] = {**routing, "zdr": True}
    result["model"] = model_for_zdr_policy(model, provider="openrouter", provider_config=provider)
    alternatives = body.get("models", [])
    if not isinstance(alternatives, list) or any(not isinstance(slug, str) for slug in alternatives):
        raise ValueError("Expected a list of alternative OpenRouter model slugs.")
    if any("online" in slug.strip().lower().split(":")[1:] for slug in (model, result["model"], *alternatives)):
        raise ValueError("Online model variants enable hosted search. Remove the variant or set allow_non_zdr=true.")
    result["plugins"] = _disabled_plugins(body.get("plugins", []))
    return result


def _disabled_plugins(plugins: Any) -> list[dict]:
    if not isinstance(plugins, list):
        raise ValueError("Expected a list of OpenRouter plugins.")
    disabled = []
    for plugin in plugins:
        if not isinstance(plugin, dict) or not isinstance(plugin.get("id"), str) or plugin.get("enabled") is not False:
            raise ValueError(
                "Hosted plugins are unavailable under required ZDR. Disable them or set allow_non_zdr=true."
            )
        disabled.append({"id": plugin["id"], "enabled": False})
    # Omission inherits the account's web plugin default.
    if not any(plugin["id"] == "web" for plugin in disabled):
        disabled.append({"id": "web", "enabled": False})
    return disabled


def refusal(code: str, message: str, request_id: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": {"type": "invalid_request_error", "code": code, "message": message}},
        status_code=status,
        headers={"X-Request-ID": request_id},
    )


def zdr_refusal(status: int, content: bytes, model: str, request_id: str) -> JSONResponse | None:
    if status != 404:
        return None
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeError):
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return None
    metadata = error.get("metadata")
    reasons = metadata.get("ineligibility_reasons") if isinstance(metadata, dict) else None
    if isinstance(reasons, list) and any(
        isinstance(reason, dict) and reason.get("reason") == "zdr-violation-by-account" for reason in reasons
    ):
        message = f"OpenRouter account ZDR excludes {model}. Choose a ZDR-eligible model or review https://openrouter.ai/settings/privacy."
    elif (
        str(error.get("message", ""))
        .lower()
        .startswith("no endpoints found matching your data policy (zero data retention)")
    ):
        message = (
            f"OpenRouter found no ZDR-eligible endpoint for {model}. Choose a ZDR-eligible model. "
            "If account and guardrail policies permit, allow_non_zdr=true relaxes this proxy's ZDR requirement."
        )
    else:
        return None
    return refusal("zdr_unavailable", message, request_id)
