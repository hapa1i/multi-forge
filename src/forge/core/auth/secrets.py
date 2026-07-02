"""SecretsProvider protocol and implementations.

This module provides a unified interface for accessing secrets (API keys)
from multiple sources with explicit precedence.

Usage:
    from forge.core.auth import EnvSecretsProvider, ChainSecretsProvider

    # Simple env-only access
    secrets = EnvSecretsProvider()
    api_key = secrets.require("ANTHROPIC_API_KEY")

    # Chain with file-based credentials
    from forge.core.auth.secrets import FileSecretsProvider
    secrets = ChainSecretsProvider(
        EnvSecretsProvider(),           # Env wins (user can override)
        FileSecretsProvider(),          # File-based fallback
    )
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from forge.core.auth.protocols import SecretsProvider
from forge.core.llm.errors import NoApiKeyError

logger = logging.getLogger(__name__)


def _format_missing_credential_detail(
    key: str,
    *,
    profile: str | None = None,
    env_ignored: bool = False,
) -> str | None:
    """Best-effort actionable message for known credential env vars."""
    try:
        from forge.core.auth.capabilities import (
            credential_for_env_var,
            format_missing_credential_error,
        )

        credential = credential_for_env_var(key)
        if credential is None:
            return None
        return format_missing_credential_error(
            credential,
            missing_vars=[key],
            profile=profile,
            env_ignored=env_ignored,
        )
    except Exception as e:
        logger.debug("Could not format missing credential detail for %s: %s", key, e)
        return None


class EnvSecretsProvider:
    """Reads secrets from os.environ.

    Expects dotenv to already be loaded (by CLI main or config loader).
    Does NOT call load_dotenv() itself to avoid import-time side effects.

    Args:
        ignore_env: When True, all lookups return the default value.
            Used by ``auth_ignore_env`` to bypass shell env vars.
            When None (default), reads from runtime config on each call
            so config changes take effect without restarting.
    """

    def __init__(self, *, ignore_env: bool | None = None) -> None:
        self._ignore_env = ignore_env

    def _should_ignore(self) -> bool:
        if self._ignore_env is not None:
            return self._ignore_env
        try:
            from forge.runtime_config import get_runtime_config

            return get_runtime_config().auth_ignore_env
        except Exception as e:
            logger.debug("Could not read auth_ignore_env; using environment credentials: %s", e)
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Get secret from environment, returning default if not found or empty."""
        if self._should_ignore():
            return default
        value = os.environ.get(key)
        # Treat empty string as not-set (consistent with config schema defaults)
        return value if value else default

    def require(self, key: str) -> str:
        """Get required secret from environment, raising if not found or empty."""
        if self._should_ignore():
            raise NoApiKeyError(
                provider="env",
                env_var=key,
                detail=_format_missing_credential_detail(key, env_ignored=True),
            )
        value = os.environ.get(key)
        if not value:
            raise NoApiKeyError(
                provider="env",
                env_var=key,
                detail=_format_missing_credential_detail(key),
            )
        return value


class FileSecretsProvider:
    """Read secrets from ~/.forge/credentials.yaml for a named profile.

    Reads from disk on each call (no caching) — CredentialManager's TTL
    cache gates call frequency. This ensures freshly-saved credentials
    (via ``forge auth login``) are picked up without restart.
    """

    def __init__(self, profile: str | None = None, *, path: Path | None = None) -> None:
        from forge.core.auth.credentials_file import resolve_profile

        self._profile = resolve_profile(profile)
        self._path = path

    def get(self, key: str, default: Any = None) -> Any:
        """Get secret from credential file, returning default if not found or empty."""
        from forge.core.auth.credentials_file import load_profile

        secrets = load_profile(self._profile, path=self._path)
        value = secrets.get(key)
        return value if value else default

    def require(self, key: str) -> str:
        """Get required secret from credential file, raising if not found or empty."""
        value = self.get(key)
        if not value:
            raise NoApiKeyError(
                provider=f"file:{self._profile}",
                env_var=key,
                detail=_format_missing_credential_detail(key, profile=self._profile),
            )
        return value


class ChainSecretsProvider:
    """Chain of providers with explicit precedence.

    Returns the first truthy (non-empty) value found across the provider chain.
    Both None and empty string "" are treated as "not set".

    Typical usage:
        secrets = ChainSecretsProvider(
            EnvSecretsProvider(),   # Env wins
            FileSecretsProvider(),  # File-based fallback
        )

    Args:
        *providers: SecretsProvider instances in priority order (first wins)
    """

    def __init__(self, *providers: SecretsProvider) -> None:
        if not providers:
            raise ValueError("ChainSecretsProvider requires at least one provider")
        self._providers = providers

    def get(self, key: str, default: Any = None) -> Any:
        """Get secret from first provider that has a truthy value."""
        for provider in self._providers:
            value = provider.get(key)
            if value:  # Truthy check: treats "" and None as not-set
                return value
        return default

    def require(self, key: str) -> str:
        """Get required secret, raising if no provider has a truthy value."""
        value = self.get(key)
        if not value:
            raise NoApiKeyError(
                provider="chain",
                env_var=key,
                detail=_format_missing_credential_detail(key),
            )
        return value
