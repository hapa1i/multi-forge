"""OpenRouter request-policy helpers shared by direct and proxied calls."""

from __future__ import annotations

from forge.core.llm.types import ModelHyperparameters


def with_openrouter_zdr(hyperparams: ModelHyperparameters | None) -> ModelHyperparameters:
    """Return hyperparameters that require an OpenRouter ZDR endpoint.

    The requirement is authoritative, so it replaces a caller-provided false
    value while preserving sibling OpenRouter routing options. The caller's
    hyperparameters are never mutated.
    """
    base = hyperparams.model_copy(deep=True) if hyperparams is not None else ModelHyperparameters()
    openai_extra = dict(base.extra.get("openai", {}))
    extra_body = dict(openai_extra.get("extra_body", {}))
    provider = dict(extra_body.get("provider", {}))
    provider["zdr"] = True
    extra_body["provider"] = provider
    openai_extra["extra_body"] = extra_body
    base.extra = {**base.extra, "openai": openai_extra}
    return base
