"""Metric-evidence attribution vocabulary shared by the telemetry and usage planes.

``Reporter`` (who supplied the metric evidence) and ``Confidence`` (how trustworthy the
cost figure is) are carried by BOTH downstream telemetry records (``downstream.py``) and
the usage ledger (``usage/vocabulary.py`` re-exports them beside ``Route`` and the named
tokens). They live here -- the lower telemetry layer, below ``downstream`` -- so both
planes import one definition without a cycle:

- ``usage`` already depends on ``telemetry`` (``usage/emit.py`` imports ``downstream``),
  so ``usage`` importing this leaf keeps the existing dependency direction.
- This module imports nothing but ``typing``, so ``downstream`` can import it mid-load
  (the ``core.telemetry`` package ``__init__`` is already running by then, no re-entry).

Deliberately thin (no I/O, no dataclasses): the neutral home ``usage/vocabulary.py`` was
meant to be, but could not, because importing it drags ``usage/__init__`` -> ``emit`` ->
``downstream``.
"""

from __future__ import annotations

from typing import Literal

# The source that supplied the metric evidence -- tokens AND/OR a cost figure, NOT
# specifically cost. So reporter="provider" can sit beside confidence="unavailable":
# the provider reported tokens, just no dollars -- not a contradiction.
# Emitted now: provider, forge_proxy, claude_code (Phase 5: a direct `claude -p`
# verb/worker self-reports cost+usage via --output-format json).
# Reserved: openrouter / litellm / codex_jsonl (Phase 2/5).
Reporter = Literal[
    "claude_code",
    "forge_proxy",
    "openrouter",
    "litellm",
    "provider",
    "codex_jsonl",
]

# Trustworthiness of the COST figure (cost_micro_usd) specifically -- NOT the tokens
# (that provenance is measurement_source). Authoritative for an event's OWN cost field
# only: a null cost is "unavailable" regardless of any cost record joined via source_refs.
#   reported           -- the route/reporter returned the dollar figure directly
#   gateway_calculated -- a gateway (OpenRouter/LiteLLM) computed it
#   inferred           -- Forge computed it from the local price catalog (an estimate)
#   unavailable        -- the route reports no cost figure (cost is None)
#   unknown            -- provenance was never recorded (legacy/default only)
Confidence = Literal[
    "reported",
    "gateway_calculated",
    "inferred",
    "unavailable",
    "unknown",
]
