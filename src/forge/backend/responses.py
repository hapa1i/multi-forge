"""Responses endpoint eligibility for saved proxy instances and running listeners."""

from urllib.parse import urlsplit

import httpx

from forge.backend.sources import (
    ModelSource,
    ModelSourceNotFoundError,
    get_model_source,
)
from forge.core.wire_shapes import OPENAI_RESPONSES_PASSTHROUGH


def validate_base(base: str) -> None:
    """Validate the configured destination before resolving or attaching a bearer."""
    if not isinstance(base, str):
        raise ValueError("OpenRouter base URL must be a string.")
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


def resolve_responses_source(backend: str, provider: str, wire_shape: str, base_url: str) -> ModelSource | None:
    """Resolve the endpoint's source, raising ValueError for an invalid direct destination."""
    if provider == "openrouter":
        if backend not in ("", "openrouter"):
            return None
        validate_base(base_url)
        backend = "openrouter"
    elif provider != "litellm" or backend == "openrouter" or wire_shape != OPENAI_RESPONSES_PASSTHROUGH:
        return None

    try:
        source = get_model_source(backend)
    except ModelSourceNotFoundError:
        return None
    return source if source.capabilities.responses_ingress else None


def available_responses_source(backend: str, provider: str, wire_shape: str, base_url: str) -> ModelSource | None:
    """Describe readiness without disrupting Messages on an ineligible snapshot."""
    try:
        return resolve_responses_source(backend, provider, wire_shape, base_url)
    except ValueError:
        return None
