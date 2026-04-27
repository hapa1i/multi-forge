"""Secrets propagation for sidecar sessions.

Forward required secrets (API keys) from the host environment into Docker
containers. Secrets are template-dependent.

Resolution order: environment variable → credential file (~/.forge/credentials.yaml).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Template to required secrets mapping
# Keys are template name prefixes, values are lists of env var names
TEMPLATE_SECRETS: dict[str, list[str]] = {
    # LiteLLM remote templates need API key + base URL
    "litellm-openai": ["LITELLM_API_KEY", "LITELLM_BASE_URL"],
    "litellm-gemini": ["LITELLM_API_KEY", "LITELLM_BASE_URL"],
    "litellm-anthropic": ["LITELLM_API_KEY", "LITELLM_BASE_URL"],
    # LiteLLM local with personal Gemini API key (dev and test templates)
    "litellm-gemini-local": ["GEMINI_API_KEY"],
    "litellm-gemini-test": ["GEMINI_API_KEY"],
    # LiteLLM local with personal Gemini Flash API key
    "litellm-gemini-flash-local": ["GEMINI_API_KEY"],
    # LiteLLM local with personal OpenAI API key
    "litellm-openai-local": ["OPENAI_API_KEY"],
    "litellm-openai-codex-local": ["OPENAI_API_KEY"],
    # LiteLLM local with personal Anthropic API key
    "litellm-anthropic-local": ["ANTHROPIC_API_KEY"],
}


def _get_file_secrets() -> dict[str, str]:
    """Load secrets from the credential file for the active profile.

    Returns empty dict on any error (missing file, corrupt YAML, etc.)
    so sidecar propagation never fails due to credential file issues.
    """
    try:
        from forge.core.auth.credentials_file import load_profile, resolve_profile

        profile = resolve_profile()
        return load_profile(profile)
    except Exception as e:
        # Logged broad catch: load_profile can raise CredentialVersionError,
        # OSError, ValueError, etc. Sidecar launch must never fail on credentials.
        logger.debug("Credential file load failed (non-critical): %s", e)
        return {}


def get_secrets_for_template(template: str) -> dict[str, str]:
    """Get secrets required by a template.

    Resolves each key from environment first, then falls back to the
    credential file (~/.forge/credentials.yaml). Only includes secrets
    that resolve to non-empty values.

    Args:
        template: Template name (e.g., "litellm-openai", "litellm-gemini").

    Returns:
        Dict of {env_var_name: value} for secrets that are resolved.
        Empty dict if template has no required secrets or none are found.
    """
    secrets: dict[str, str] = {}

    required = TEMPLATE_SECRETS.get(template, [])
    if not required:
        return secrets

    # Lazy-load file secrets only when needed
    file_secrets: dict[str, str] | None = None

    for key in required:
        # Env wins
        value = os.environ.get(key)
        if value:
            secrets[key] = value
            continue

        # Fall back to credential file
        if file_secrets is None:
            file_secrets = _get_file_secrets()
        value = file_secrets.get(key)
        if value:
            logger.debug("Sidecar secret %s resolved from credential file", key)
            secrets[key] = value

    return secrets
