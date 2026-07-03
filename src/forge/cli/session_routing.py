"""Shared CLI routing value objects for session commands."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedRouting:
    """Resolved proxy routing for a session launch."""

    template: str | None = None
    base_url: str | None = None
    proxy_id: str | None = None
    context_limit: int | None = None

    @property
    def is_direct(self) -> bool:
        return self.base_url is None
