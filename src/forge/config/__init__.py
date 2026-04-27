"""Unified configuration system for Claude Forge.

This module provides a type-safe configuration system with three sources:

    1. Proxy file: ~/.forge/proxies/{id}/proxy.yaml (user owns full config)
    2. Template: defaults/templates/{t}.yaml (for proxy creation only)
    3. Secrets: .env + env vars (*_API_KEY, *_AUTH_URL, FORGE_HOME)

Schema defaults in dataclasses handle missing fields.

Usage:
    from forge.config import config

    # Access configuration
    model = config.proxy.litellm.tiers.opus
    overrides = config.proxy.litellm.tier_overrides.get("opus")

    # Load with specific proxy
    from forge.config import load_config
    config = load_config(proxy_id="my-proxy")

    # Load template (for proxy creation)
    config = load_config(template="litellm-gemini")

    # Reload configuration
    from forge.config import reload
    reload(proxy_id="my-proxy")
"""

from forge.config.loader import load_config, reload_config
from forge.config.schema import (
    OPENAI_MODELS,
    ForgeConfig,
    ProviderConfig,
    ProxyConfig,
    SessionConfig,
    TierModels,
    TierOverride,
    TierOverrides,
    is_openai_model,
)

__all__ = [
    # Main config instance
    "config",
    # Functions
    "load_config",
    "reload",
    "get_config",
    "init_config",
    # Helper functions
    "is_openai_model",
    # Constants
    "OPENAI_MODELS",
    # Schema classes (for type hints)
    "ForgeConfig",
    "ProxyConfig",
    "SessionConfig",
    "ProviderConfig",
    "TierModels",
    "TierOverride",
    "TierOverrides",
]

# Global config instance (singleton)
_config: ForgeConfig | None = None


def get_config() -> ForgeConfig:
    """Get the global config instance, loading if necessary."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload(*, template: str | None = None, proxy_id: str | None = None) -> ForgeConfig:
    """Reload configuration from all sources."""
    global _config
    if _config is not None:
        _config = reload_config(_config, template=template, proxy_id=proxy_id)
    else:
        _config = load_config(template=template, proxy_id=proxy_id)
    return _config


def init_config(*, template: str | None = None, proxy_id: str | None = None) -> ForgeConfig:
    """Initialize configuration with optional template/proxy.

    Call this at application startup to load config with a specific template.
    Subsequent calls to get_config() will return this instance.
    """
    global _config
    _config = load_config(template=template, proxy_id=proxy_id)
    return _config


# Lazy-loaded config property
class _ConfigProxy:
    """Proxy that lazily loads config on first access."""

    def __getattr__(self, name: str):
        return getattr(get_config(), name)

    def __repr__(self) -> str:
        return repr(get_config())


# Export lazy config proxy as 'config'
config: ForgeConfig = _ConfigProxy()  # type: ignore[assignment]  # _ConfigProxy delegates to ForgeConfig at runtime
