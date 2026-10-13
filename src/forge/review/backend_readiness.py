"""Read-only model-inventory checks for workflow LiteLLM routes."""

from __future__ import annotations

import os
import re
import ssl
from urllib.parse import urlparse

import httpx

from forge.config.loader import load_proxy_instance_config
from forge.core.auth.template_secrets import resolve_env_or_credential
from forge.core.llm.detection import detect_provider
from forge.core.reactive.routing import RoutingResult


class WorkflowBackendReadiness:
    """Cache loaded backend inventories for one readiness check or invocation."""

    def __init__(self, timeout_s: float = 1.0) -> None:
        self._timeout_s = timeout_s
        self._inventories: dict[tuple[str, str], tuple[str, ...] | str] = {}

    def error_for(self, result: RoutingResult) -> str | None:
        """Return recovery guidance when a selected LiteLLM deployment is unavailable."""
        route = result.route
        if route is None or route.provider != "litellm":
            return None

        proxy_id = result.proxy_id
        if not proxy_id:
            return None
        try:
            instance = load_proxy_instance_config(proxy_id)
        except Exception:
            return f"Cannot read saved configuration for proxy '{proxy_id}'; inspect it with 'forge proxy show {proxy_id}'."
        if instance is None:
            # Sidecar-injected and external proxies need not mount host-owned snapshots.
            # Their existing route checks remain valid, but cannot attest backend inventory.
            return None
        if instance.provider != "litellm":
            return f"Proxy '{proxy_id}' no longer has a LiteLLM configuration; inspect it with 'forge proxy show {proxy_id}'."

        base_url = instance.upstream_base_url.rstrip("/")
        try:
            hostname = urlparse(base_url).hostname
        except ValueError:
            return f"Proxy '{proxy_id}' has an invalid upstream URL; inspect it with 'forge proxy show {proxy_id}'."
        local = detect_provider(route.model_ref) == "litellm_local" or hostname in {
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "::1",
        }
        credential_var = "LITELLM_LOCAL_API_KEY" if local else "LITELLM_API_KEY"
        api_key = resolve_env_or_credential(credential_var) or ("not-needed" if local else "")
        if not api_key:
            return f"Cannot inspect proxy '{proxy_id}' backend models: {credential_var} is not configured."
        endpoint = f"{base_url}/models"
        cache_key = (endpoint, api_key)
        if cache_key not in self._inventories:
            self._inventories[cache_key] = self._read_inventory(endpoint, api_key)
        inventory = self._inventories[cache_key]
        if isinstance(inventory, str):
            return (
                f"Cannot verify model '{route.model_ref}' through proxy '{proxy_id}': {inventory}. "
                "Check the backend endpoint and credentials with 'forge model backend test-auth <source-id>', then retry."
            )
        if any(re.fullmatch(re.escape(model).replace(r"\*", ".*"), route.model_ref) for model in inventory):
            return None

        return (
            f"LiteLLM backend for proxy '{proxy_id}' does not advertise model '{route.model_ref}'. "
            "Add the complete deployment entry, including model_info, to the backend's saved configuration, then restart "
            "that backend and retry 'forge workflow list-models --available'. Upgrading Forge or restarting only the "
            "Forge proxy does not update a saved backend. For remote LiteLLM, ask its operator to add the deployment."
        )

    def _read_inventory(self, endpoint: str, api_key: str) -> tuple[str, ...] | str:
        """Read only caller-visible deployments, including LiteLLM wildcard routes."""
        try:
            cert_path = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
            verify: bool | ssl.SSLContext = ssl.create_default_context(cafile=cert_path) if cert_path else True
            with httpx.Client(timeout=httpx.Timeout(self._timeout_s), verify=verify) as client:
                response = client.get(
                    endpoint,
                    params={"return_wildcard_routes": "true"},
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            if response.status_code != 200:
                return f"backend model inventory returned HTTP {response.status_code}"
            payload = response.json()
            rows = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or any(
                not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] for row in rows
            ):
                return "backend model inventory is malformed"
            return tuple(row["id"] for row in rows)
        except (httpx.RequestError, httpx.InvalidURL, ValueError, OSError):
            # Provider response bodies and exception strings can contain credentials.
            return "backend model inventory could not be read"
