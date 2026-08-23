"""Neutral facts shared by status-line acquisition and rendering."""

from __future__ import annotations

from typing import NamedTuple

from forge.proxy.runtime_truth import ProxyRuntimeTruth

__all__ = ["ProxyRuntimeTruth", "TranscriptStats"]


class TranscriptStats(NamedTuple):
    """Results from one transcript scan."""

    has_thinking: bool = False
    user_count: int = 0
    tool_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
