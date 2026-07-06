"""Dependency-light lane runtime ids, shared by the catalog and the lane layer.

The lane runtime axis is ``{CORE_LLM_RUNTIME} | RUNTIMES`` -- the in-process
single-shot runtime plus the agent runtimes in ``forge.core.runtime.registry``.
That registry is the capability matrix, but importing it drags the whole
``forge.core.runtime`` package (``codex_preflight`` -> ``core.auth`` ->
``template_secrets`` -> ``forge.backend.sources``), so the catalog cannot depend on
it without a cycle. This module carries only the id *vocabulary*, import-cheap like
``forge.core.provider_types``, so ``forge.backend.sources`` can validate
``reachable_via`` pins at import.

``AGENT_RUNTIME_IDS`` mirrors ``RUNTIMES`` keys; the two are drift-guarded by
``test_lane_runtime_vocab_matches_registry``.
"""

from __future__ import annotations

# The in-process single-shot runtime (``forge.core.llm``); deliberately NOT a
# ``RUNTIMES`` entry (that table is the agent registry iterated by list_runtimes()).
CORE_LLM_RUNTIME = "core_llm"

# Agent runtime ids; kept in sync with ``RUNTIMES`` keys in core.runtime.registry.
AGENT_RUNTIME_IDS: tuple[str, ...] = ("claude_code", "codex")

# Every runtime a Lane can carry -- the axis reachable_via pins are matched against.
LANE_RUNTIME_IDS = frozenset(AGENT_RUNTIME_IDS) | {CORE_LLM_RUNTIME}

__all__ = ["AGENT_RUNTIME_IDS", "CORE_LLM_RUNTIME", "LANE_RUNTIME_IDS"]
