"""Metric-evidence vocabulary shared across Forge's cost/usage planes.

Plain, closed vocabularies for *what route* produced a metric, *who reported* it, and
*how trustworthy the cost figure is*. ``Route`` and its named tokens live here.
``Reporter``/``Confidence`` are defined in the neutral telemetry leaf
(``core/telemetry/vocabulary.py``): the downstream plane carries them too, and hosting
them below ``downstream`` avoids a usage<->telemetry import cycle. They are re-exported
here so usage-side callers keep a single import site.

North star (the ``metric_evidence_simplification`` card): Forge is not a cost oracle.
``confidence`` exists to record "this dollar figure was *reported*" vs "*inferred* from a
local catalog" vs "*unavailable*", so an estimate is never presented as truth.
"""

from __future__ import annotations

from typing import Literal

from forge.core.telemetry.vocabulary import Confidence, Reporter

# Public surface: the usage-owned Route vocabulary plus the re-exported telemetry-leaf
# literals, so usage-side callers keep a single import site (also marks the re-exports used).
__all__ = ["ROUTE_CLAUDE_INTERACTIVE", "Confidence", "Reporter", "Route"]

# How the work reached a model/runtime (the invocation channel).
# Emitted now: claude_p, core_llm, codex_exec (plus None on an aggregate spanning
# mixed routes). Reserved here: forge_proxy -- emitted now as a Reporter, NOT yet as
# a Route (it sits in both literals) -- plus claude_interactive (Phase 4 status line).
Route = Literal[
    "claude_interactive",
    "claude_p",
    "forge_proxy",
    "core_llm",
    "codex_exec",
]

# --- named tokens referenced in code (typed against ``Route`` above) ---

# The main interactive-harness channel, as a named token. Referenced by
# ``sum_forge_added_cost``'s load-bearing exclusion (the no-blend rule); naming it
# here -- typed ``Route`` -- makes a typo a type error instead of a silently-stale
# string compare against a bare literal.
ROUTE_CLAUDE_INTERACTIVE: Route = "claude_interactive"
