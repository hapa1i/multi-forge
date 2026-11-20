"""Request policy and provider diagnostics for direct OpenRouter Responses."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi.responses import JSONResponse

from forge.proxy.model_routes import model_for_zdr_policy


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
    return result


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
        message = f"OpenRouter found no ZDR-eligible endpoint for {model}. Choose a ZDR-eligible model."
    else:
        return None
    return refusal("zdr_unavailable", message, request_id)
