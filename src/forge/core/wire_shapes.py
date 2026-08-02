"""Wire-shape vocabulary shared by config, proxy, session, and runtime consumers.

Dependency-light leaf (typing only), like core/tiers.py and core/provider_types.py:
config/schema validation, both loader hops, the proxy ingresses, launch env
derivation, model pinning, and the codex preflight all compare against these
values, so the vocabulary must sit below every one of those packages.
"""

from typing import Literal

WireShape = Literal["openai_translated", "anthropic_passthrough", "openai_responses_passthrough"]

OPENAI_TRANSLATED: WireShape = "openai_translated"
ANTHROPIC_PASSTHROUGH: WireShape = "anthropic_passthrough"
OPENAI_RESPONSES_PASSTHROUGH: WireShape = "openai_responses_passthrough"

VALID_WIRE_SHAPES: tuple[WireShape, ...] = (
    OPENAI_TRANSLATED,
    ANTHROPIC_PASSTHROUGH,
    OPENAI_RESPONSES_PASSTHROUGH,
)

# Byte-faithful shapes: raw bodies forwarded unchanged, so signed reasoning
# (Anthropic thinking blocks / Responses reasoning items) survives.
PASSTHROUGH_WIRE_SHAPES: tuple[WireShape, ...] = (
    ANTHROPIC_PASSTHROUGH,
    OPENAI_RESPONSES_PASSTHROUGH,
)

DEFAULT_WIRE_SHAPE: WireShape = OPENAI_TRANSLATED
