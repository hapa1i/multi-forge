"""Model ID normalization for proxy requests.

This module handles the flexible model ID scheme:
- provider/vendor/model → explicit provider
- vendor/model → default_provider
- model → default_provider + inferred vendor

The proxy owns this normalization logic as orchestration concern.
core.llm stays strict and requires explicit (provider, model_id) tuples.
"""

from typing import cast

from forge.core.llm.detection import ProviderType

# Known providers - these can appear as first segment
KNOWN_PROVIDERS = frozenset({"litellm_remote", "litellm_local"})

# Known vendors - these appear as vendor/ prefix before model name
KNOWN_VENDORS = frozenset(
    {
        "openai",
        "anthropic",
        "vertex_ai",
        "gemini",
        "bedrock",
        "replicate",
        "together_ai",
    }
)


def _infer_vendor(model_name: str) -> str:
    """Infer vendor from model name patterns.

    Args:
        model_name: Model name without any vendor prefix (e.g., "gpt-5.5")

    Returns:
        Inferred vendor prefix.

    Raises:
        ValueError: If vendor cannot be inferred from model name.

    Examples:
        >>> _infer_vendor("gpt-5.5")
        'openai'
        >>> _infer_vendor("claude-sonnet-4.6")
        'anthropic'
        >>> _infer_vendor("gemini-3.1-pro")
        'vertex_ai'
    """
    name = model_name.lower()

    # OpenAI models: gpt-*, o1*, o3*, o4*
    if name.startswith("gpt-") or name.startswith(("o1", "o3", "o4")):
        return "openai"

    # Anthropic models: claude-*
    if name.startswith("claude-"):
        return "anthropic"

    # Google models: gemini-* → vertex_ai for remote routing
    if name.startswith("gemini-"):
        return "vertex_ai"

    raise ValueError(
        f"Cannot infer vendor for model '{model_name}'. "
        f"Use explicit vendor prefix like 'openai/{model_name}' or 'anthropic/{model_name}'."
    )


def normalize_model_spec(
    input_spec: str,
    default_provider: ProviderType = "litellm_remote",
) -> tuple[ProviderType, str]:
    """Parse model spec and return (provider, vendor/model).

    Supports progressive fallback:
      - provider/vendor/model → explicit provider (e.g., "litellm_local/gemini/gemini-3.1")
      - vendor/model → default_provider (e.g., "openai/gpt-5.5")
      - model → default_provider + inferred vendor (e.g., "gpt-5.5" → "openai/gpt-5.5")

    Args:
        input_spec: Model specification in any supported format.
        default_provider: Provider to use when not explicitly specified.

    Returns:
        Tuple of (provider, model_id) where model_id is vendor/model format.

    Raises:
        ValueError: If the spec is malformed or cannot be parsed.

    Examples:
        >>> normalize_model_spec("litellm_remote/openai/gpt-5.5")
        ('litellm_remote', 'openai/gpt-5.5')
        >>> normalize_model_spec("openai/gpt-5.5")
        ('litellm_remote', 'openai/gpt-5.5')
        >>> normalize_model_spec("gpt-5.5")
        ('litellm_remote', 'openai/gpt-5.5')
        >>> normalize_model_spec("litellm_remote/openai/gpt-5.5")
        ('litellm_remote', 'openai/gpt-5.5')
    """
    if not input_spec or not input_spec.strip():
        raise ValueError("Model spec cannot be empty")

    parts = input_spec.strip().split("/")

    if len(parts) == 1:
        # Single segment: model only → infer vendor, use default provider
        model_name = parts[0]
        vendor = _infer_vendor(model_name)
        return (default_provider, f"{vendor}/{model_name}")

    if len(parts) == 2:
        first, second = parts

        # Check if first segment is a known provider (ambiguous case)
        if first in KNOWN_PROVIDERS:
            # This looks like provider/something, but we need vendor/model
            raise ValueError(
                f"Ambiguous model spec '{input_spec}': '{first}' looks like a provider "
                f"but missing vendor segment. Use '{first}/openai/{second}' format."
            )

        # Standard vendor/model format
        if first not in KNOWN_VENDORS:
            raise ValueError(
                f"Unknown vendor '{first}' in model spec '{input_spec}'. "
                f"Known vendors: {', '.join(sorted(KNOWN_VENDORS))}"
            )

        return (default_provider, input_spec)

    if len(parts) == 3:
        provider, vendor, model = parts

        # Validate provider
        if provider not in KNOWN_PROVIDERS:
            raise ValueError(
                f"Unknown provider '{provider}' in model spec '{input_spec}'. "
                f"Known providers: {', '.join(sorted(KNOWN_PROVIDERS))}"
            )

        # Validate vendor
        if vendor not in KNOWN_VENDORS:
            raise ValueError(
                f"Unknown vendor '{vendor}' in model spec '{input_spec}'. "
                f"Known vendors: {', '.join(sorted(KNOWN_VENDORS))}"
            )

        return (cast(ProviderType, provider), f"{vendor}/{model}")

    # 4+ segments: invalid
    raise ValueError(
        f"Invalid model spec '{input_spec}': too many segments. "
        f"Use 'provider/vendor/model', 'vendor/model', or 'model' format."
    )
