"""Status-line segment names — neutral constants.

Deliberately import-free (no rendering, CLI, or config code) so that both the
renderer (``registry.py``) and the config CLI (``config_cmd.py``) can reference
the canonical segment names without a circular or heavyweight import. In
particular ``runtime_config`` does NOT import this module: segment-name validity
is owned by the renderer (drops unknown names) and ``forge config set``/``edit``
(rejects unknown names), never by the config dataclass.

``SEGMENT_NAMES`` is exactly the set of segments that render *today*: every name
here has a producer in ``registry.py`` and an equality test enforces the
two-way sync. There are no reserved-but-unimplemented names — a name must land
with its producer in the same change, so ``forge config set`` never accepts a
segment that silently renders nothing.
"""

from __future__ import annotations

# Renderable segment names (== registry producer names). Order is not
# significant here (this is the allowlist, not the render order).
SEGMENT_NAMES: tuple[str, ...] = (
    # Always-available (Claude Code stdin / git / session manifest):
    "path",
    "branch",
    "breadcrumb",
    "model",
    "cost",
    "rate_limits",
    "lines",
    "tokens",
    "think",
    "loop",
    "sidecar",
    # Opt-in (off by default; not in DEFAULT_ORDER):
    "cache_hit",
    # Forge-unique opt-in (off by default):
    "supervisor",
    "policy",
    "audit",
    "drift",
    "spend_cap",
)

# Default render order — reproduces the pre-enhancement status line exactly.
# Notably EXCLUDES ``rate_limits`` (it was gated off by default via the old
# ``show_rate_limits`` flag) and every opt-in segment. An empty configured
# ``segments`` list falls back to this order.
DEFAULT_ORDER: tuple[str, ...] = (
    "path",
    "branch",
    "breadcrumb",
    "model",
    "cost",
    "lines",
    "tokens",
    "think",
    "loop",
    "sidecar",
)
