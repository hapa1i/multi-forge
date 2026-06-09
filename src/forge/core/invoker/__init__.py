"""Runtime-neutral headless invocation (Phase 4d).

A :class:`HeadlessInvoker` runs already-routed ``claude -p`` jobs -- single-shot or
parallel fan-out -- owning the subprocess lifecycle (process groups, signal cleanup,
ordered fan-out, timeouts) and per-job usage emission. Phase 5 adds a
``CodexHeadlessInvoker`` behind the same protocol so callers don't change.
"""

from .claude import ClaudeHeadlessInvoker
from .codex import CodexHeadlessInvoker, prepare_codex_request
from .types import (
    Attribution,
    HeadlessInvoker,
    HeadlessRequest,
    HeadlessResult,
)

__all__ = [
    "Attribution",
    "ClaudeHeadlessInvoker",
    "CodexHeadlessInvoker",
    "HeadlessInvoker",
    "HeadlessRequest",
    "HeadlessResult",
    "prepare_codex_request",
]
