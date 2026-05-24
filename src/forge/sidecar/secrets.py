"""Secrets propagation for sidecar sessions.

Forward required secrets (API keys, connection values) from the host
environment into Docker containers. Secrets are template-dependent.

Resolution order: environment variable -> credential file (~/.forge/credentials.yaml).

Implementation lives in ``forge.core.auth.template_secrets``; this module
re-exports the public API for backward compatibility.
"""

from __future__ import annotations

from forge.core.auth.template_secrets import (
    TEMPLATE_ENV_VARS,
    get_secrets_for_template,
)

__all__ = ["TEMPLATE_ENV_VARS", "get_secrets_for_template"]
