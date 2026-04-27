"""Default configuration values for forge session.

These defaults can be overridden via environment variables:
- FORGE_DEFAULT_PROXY_TEMPLATE
- FORGE_DEFAULT_PROXY_BASE_URL
"""

from __future__ import annotations

import os
from pathlib import Path

# Proxy defaults (configurable via env vars)
DEFAULT_PROXY_TEMPLATE = os.environ.get("FORGE_DEFAULT_PROXY_TEMPLATE", "litellm-openai")
DEFAULT_PROXY_BASE_URL = os.environ.get("FORGE_DEFAULT_PROXY_BASE_URL", "http://localhost:8085")

# Launch mode constants
LAUNCH_MODE_HOST = "host"
LAUNCH_MODE_SIDECAR = "sidecar"

# Sidecar sessions always talk to the proxy on the container-local loopback.
SIDECAR_RUNTIME_BASE_URL = "http://localhost:8085"


def _discover_templates() -> tuple[str, ...]:
    """Derive valid proxy templates from the templates directory."""
    templates_dir = Path(__file__).parent.parent / "config" / "defaults" / "templates"
    if not templates_dir.is_dir():
        return ()
    return tuple(sorted(p.stem for p in templates_dir.glob("*.yaml")))


# Valid proxy templates (derived from templates directory)
VALID_PROXY_TEMPLATES: tuple[str, ...] = _discover_templates()
