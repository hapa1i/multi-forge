"""Metric-evidence vocabulary shared across Forge's cost/usage planes.

Plain, closed vocabularies for *what route* produced a metric, *who reported* it, and
*how trustworthy the cost figure is*. Deliberately a thin module (no I/O, no dataclasses)
so both the usage ledger (``ledger.py``) and -- later -- the cost plane
(``proxy/cost_logger.py``, Phase 2) can import these terms without coupling to either
plane's read/write machinery.

North star (the ``metric_evidence_simplification`` card): Forge is not a cost oracle.
``confidence`` exists to record "this dollar figure was *reported*" vs "*inferred* from a
local catalog" vs "*unavailable*", so an estimate is never presented as truth.
"""

from __future__ import annotations

from typing import Literal

# How the work reached a model/runtime (the invocation channel).
# Emitted now: claude_p, core_llm (plus None on an aggregate spanning mixed routes).
# Reserved (declared up front, like the ledger's unemitted subscription_* billing modes):
# forge_proxy -- emitted now as a Reporter, NOT yet as a Route (it sits in both literals) --
# plus claude_interactive (Phase 4 status line) and codex_exec / gemini_headless (Phase 5).
Route = Literal[
    "claude_interactive",
    "claude_p",
    "forge_proxy",
    "core_llm",
    "codex_exec",
    "gemini_headless",
]

# The source that supplied the metric evidence -- tokens AND/OR a cost figure, NOT
# specifically cost. So reporter="provider" can sit beside confidence="unavailable":
# the provider reported tokens, just no dollars -- not a contradiction.
# Emitted now: provider, forge_proxy. Reserved: claude_code (Phase 4),
# openrouter / litellm / codex_jsonl (Phase 2/5).
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
