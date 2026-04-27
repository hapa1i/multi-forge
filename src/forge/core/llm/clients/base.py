"""Base helpers for LLM client implementations."""

import logging

from ..errors import UnsupportedParamError
from ..types import ModelHyperparameters

logger = logging.getLogger(__name__)


def merge_hyperparams(
    defaults: ModelHyperparameters | None,
    call_time: ModelHyperparameters | None,
) -> ModelHyperparameters:
    """Merge default hyperparameters with call-time overrides.

    Call-time values take precedence, but only for fields explicitly set by
    the caller. Default values on ModelHyperparameters do not override client
    defaults (uses exclude_unset, not exclude_none).

    Args:
        defaults: Default hyperparameters (from client initialization).
        call_time: Call-time hyperparameters (from complete/stream call).

    Returns:
        Merged hyperparameters.
    """
    if defaults is None and call_time is None:
        return ModelHyperparameters()
    if defaults is None:
        return call_time or ModelHyperparameters()
    if call_time is None:
        return defaults

    # Merge: only explicitly-set call_time values override defaults
    merged_data = defaults.model_dump()
    call_data = call_time.model_dump(exclude_unset=True)

    # Special handling for nested dicts (extra)
    if "extra" in call_data:
        merged_extra = merged_data.get("extra", {}).copy()
        for namespace, params in call_data["extra"].items():
            if namespace in merged_extra:
                merged_extra[namespace] = {**merged_extra[namespace], **params}
            else:
                merged_extra[namespace] = params
        call_data["extra"] = merged_extra

    merged_data.update(call_data)
    return ModelHyperparameters(**merged_data)


def handle_unsupported_param(
    param: str,
    value: object,
    provider: str,
    strict: bool,
) -> None:
    """Handle an unsupported parameter.

    In strict mode, raises UnsupportedParamError.
    Otherwise, logs a warning and continues.

    Args:
        param: Parameter name that is not supported.
        value: The value that was provided.
        provider: Provider that doesn't support this parameter.
        strict: Whether to raise an error (True) or warn (False).

    Raises:
        UnsupportedParamError: If strict mode is enabled.
    """
    if strict:
        raise UnsupportedParamError(param, provider)
    else:
        logger.warning(f"Parameter '{param}' with value '{value}' not supported by {provider}, ignoring")


def estimate_tokens_simple(text: str) -> int:
    """Simple token estimation (4 chars per token).

    This is a conservative estimate for when provider-specific
    tokenization is not available.

    Args:
        text: Text to estimate tokens for.

    Returns:
        Estimated token count.
    """
    return len(text) // 4 + 1


def estimate_message_tokens(messages: list[dict[str, object]]) -> int:
    """Estimate tokens for a list of messages.

    Args:
        messages: List of message dicts with 'content' field.

    Returns:
        Estimated total token count.
    """
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens_simple(content)
        elif isinstance(content, list):
            # Multimodal content - estimate text parts only
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += estimate_tokens_simple(str(part.get("text", "")))
        # Add overhead per message
        total += 10
    return total
