"""Production-shaped telemetry producers used only by reader tests."""

from __future__ import annotations

from typing import Any

from forge.core.telemetry.downstream import write_downstream_record
from forge.proxy.cost_logger import build_request_cost_record


def write_request_cost_record(**values: Any) -> None:
    """Build and persist one request-cost record through the canonical seams."""
    write_downstream_record(build_request_cost_record(**values))
