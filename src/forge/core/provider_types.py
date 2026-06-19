"""Dependency-light provider vocabulary shared across Forge core modules."""

from __future__ import annotations

from typing import Literal

ProviderType = Literal["litellm_remote", "litellm_local", "anthropic", "openrouter"]

__all__ = ["ProviderType"]
