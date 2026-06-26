"""Dependency-light provider vocabulary shared across Forge core modules."""

from __future__ import annotations

from typing import Literal

# "openai" is a *catalog/source* provider only -- e.g. the ChatGPT subscription
# source reached via codex (a runtime_native backend). It is NOT a core.llm
# routing target: detect_provider() maps "openai/<model>" to litellm_remote, so
# core.llm never resolves provider == "openai" (see core/llm/detection.py).
ProviderType = Literal["litellm_remote", "litellm_local", "anthropic", "openrouter", "openai"]

__all__ = ["ProviderType"]
