"""Template-to-credential mapping and credential resolution.

Maps proxy templates to required environment variable names and provides
``resolve_env_or_credential()`` — the single lookup that checks os.environ
first, then falls back to ``~/.forge/credentials.yaml``.

Extracted from ``forge.sidecar.secrets`` so proxy orchestration, review
engine, and sidecar can all share the same resolution logic.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

TEMPLATE_ENV_VARS: dict[str, list[str]] = {
    "litellm-openai": ["LITELLM_API_KEY", "LITELLM_BASE_URL"],
    "litellm-gemini": ["LITELLM_API_KEY", "LITELLM_BASE_URL"],
    "litellm-anthropic": ["LITELLM_API_KEY", "LITELLM_BASE_URL"],
    "litellm-gemini-local": ["GEMINI_API_KEY"],
    "litellm-gemini-test": ["GEMINI_API_KEY"],
    "litellm-gemini-flash-local": ["GEMINI_API_KEY"],
    "litellm-openai-local": ["OPENAI_API_KEY"],
    "litellm-openai-codex-local": ["OPENAI_API_KEY"],
    "litellm-anthropic-local": ["ANTHROPIC_API_KEY"],
    "anthropic-passthrough": ["ANTHROPIC_API_KEY"],
    "openrouter-anthropic": ["OPENROUTER_API_KEY"],
    "openrouter-openai": ["OPENROUTER_API_KEY"],
    "openrouter-gemini": ["OPENROUTER_API_KEY"],
    "openrouter-openai-codex": ["OPENROUTER_API_KEY"],
    "openrouter-gemini-flash": ["OPENROUTER_API_KEY"],
    "openrouter-deepseek": ["OPENROUTER_API_KEY"],
    "openrouter-kimi": ["OPENROUTER_API_KEY"],
    "openrouter-glm": ["OPENROUTER_API_KEY"],
    "openrouter-minimax": ["OPENROUTER_API_KEY"],
    "openrouter-qwen": ["OPENROUTER_API_KEY"],
}


def _get_file_secrets() -> dict[str, str]:
    """Load all secrets from the credential file for the active profile.

    Returns empty dict on any error so callers never fail due to
    credential file issues.
    """
    try:
        from forge.core.auth.credentials_file import load_profile, resolve_profile

        profile = resolve_profile()
        return load_profile(profile)
    except Exception as e:
        logger.debug("Credential file load failed (non-critical): %s", e)
        return {}


def _auth_ignore_env() -> bool:
    """Check if auth_ignore_env is active (lazy import to avoid cycles)."""
    try:
        from forge.runtime_config import get_runtime_config

        return get_runtime_config().auth_ignore_env
    except Exception as e:
        logger.debug("Could not read auth_ignore_env; using environment credentials: %s", e)
        return False


def resolve_env_or_credential_with_source(var_name: str) -> tuple[str | None, str]:
    """Resolve a value and report which source supplied it.

    Source is ``"env"`` (shell environment), ``"credential_file"`` (the Forge
    credential file), or ``"none"`` (unresolved). When ``auth_ignore_env`` is
    active the shell environment is skipped, so a value present in both places is
    reported as ``credential_file`` -- the source the child actually uses. Callers
    recording provenance (e.g. interactive launch metadata) must use this rather
    than re-deriving the branch, which would drift from the value actually chosen.
    """
    if not _auth_ignore_env():
        value = os.environ.get(var_name)
        if value:
            return value, "env"
    file_value = _get_file_secrets().get(var_name) or None
    if file_value:
        return file_value, "credential_file"
    return None, "none"


def resolve_env_or_credential(var_name: str) -> str | None:
    """Resolve a single value from environment, then credential file.

    When ``auth_ignore_env`` is active, skips os.environ and reads from
    the credential file only. Returns the first truthy (non-empty) value, or None.
    """
    return resolve_env_or_credential_with_source(var_name)[0]


def get_secrets_for_template(template: str) -> dict[str, str]:
    """Get credentials required by a template.

    Resolves each key from environment first, then falls back to the
    credential file. When ``auth_ignore_env`` is active, skips environment.
    Only includes values that resolve to non-empty strings.
    """
    required = TEMPLATE_ENV_VARS.get(template, [])
    if not required:
        return {}

    ignore_env = _auth_ignore_env()
    secrets: dict[str, str] = {}
    file_secrets: dict[str, str] | None = None

    for var_name in required:
        if not ignore_env:
            value = os.environ.get(var_name)
            if value:
                secrets[var_name] = value
                continue

        if file_secrets is None:
            file_secrets = _get_file_secrets()
        value = file_secrets.get(var_name)
        if value:
            logger.debug("Credential %s resolved from credential file", var_name)
            secrets[var_name] = value

    return secrets
