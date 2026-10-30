"""Dependency-light records for Forge's resolved and outbound reasoning effort."""

from dataclasses import dataclass
from typing import Literal

EffortSource = Literal["explicit", "client", "thinking", "floor", "passthrough", "override"]


@dataclass(frozen=True, slots=True)
class EffortResolution:
    """Explain request resolution without claiming what a provider ultimately executes."""

    requested: str | None
    thinking: str | None
    opt_in: bool
    client_applicable: bool
    derived: str | None
    floor: str | None
    pre_clamp: str | None
    supported: tuple[str, ...] | None
    resolved: str | None
    source: EffortSource


@dataclass(frozen=True, slots=True)
class AppliedEffort:
    """The effort parameter present in Forge's final outbound request."""

    applied: str | None
    wire: str | None
    note: str | None = None
