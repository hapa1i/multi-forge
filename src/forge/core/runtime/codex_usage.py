"""Translate native Codex cumulative token counters into per-launch usage."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CodexUsageBaseline:
    """Source event token_count totals, never the post-compaction thread counter."""

    input_tokens: int
    output_tokens: int
    cached_tokens: int

    @classmethod
    def from_total_usage(cls, usage: object) -> CodexUsageBaseline | None:
        if not isinstance(usage, dict):
            return None
        values = [
            value
            for key in ("input_tokens", "output_tokens", "cached_input_tokens")
            if type(value := usage.get(key)) is int and value >= 0
        ]
        return cls(*values) if len(values) == 3 else None

    def as_dict(self) -> dict[str, int | None]:
        return dict(input_tokens=self.input_tokens, output_tokens=self.output_tokens, cached_tokens=self.cached_tokens)


def continued_usage_delta(
    baseline: CodexUsageBaseline | None, terminal: dict[str, int | None]
) -> dict[str, int | None]:
    """Report unknown rather than charge inherited or incomparable counters."""
    unknown = dict.fromkeys(terminal)
    if baseline is None:
        return unknown
    before = baseline.as_dict()
    if any(type(value) is not int or value < 0 for value in (*before.values(), *terminal.values())):
        return unknown
    # The checks above narrow at runtime; explicit assertions keep arithmetic typed.
    delta: dict[str, int | None] = {}
    for name, value in terminal.items():
        previous = before[name]
        assert value is not None and previous is not None
        if value < previous:
            return unknown
        delta[name] = value - previous
    if (delta["cached_tokens"] or 0) > (delta["input_tokens"] or 0):
        return unknown
    return delta
