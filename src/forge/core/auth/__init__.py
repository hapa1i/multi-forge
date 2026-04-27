"""Consolidated authentication module for Claude Forge.

This package provides:
1. SecretsProvider - unified interface for accessing secrets from env/config
2. Error types - re-exported from core.llm.errors for convenience

Usage:
    from forge.core.auth import (
        EnvSecretsProvider,
        ChainSecretsProvider,
        NoApiKeyError,
    )

    # Simple env-only secrets
    secrets = EnvSecretsProvider()
    api_key = secrets.require("ANTHROPIC_API_KEY")
"""

from forge.core.auth.credentials_file import CredentialVersionError
from forge.core.auth.protocols import SecretsProvider
from forge.core.auth.secrets import (
    ChainSecretsProvider,
    ConfigSecretsProvider,
    EnvSecretsProvider,
    FileSecretsProvider,
)

# Re-export errors from core.llm.errors (no new types)
from forge.core.llm.errors import AuthenticationError, NoApiKeyError

__all__ = [
    # SecretsProvider protocol and implementations
    "SecretsProvider",
    "EnvSecretsProvider",
    "ConfigSecretsProvider",
    "FileSecretsProvider",
    "ChainSecretsProvider",
    # Credential file errors
    "CredentialVersionError",
    # Re-exported errors (canonical source: core.llm.errors)
    "AuthenticationError",
    "NoApiKeyError",
]
