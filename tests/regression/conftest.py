"""Fixtures shared by regression reproductions."""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def responses_provider_traces(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture Responses provider-trace writes without touching durable telemetry."""
    import forge.proxy.responses_passthrough as responses_passthrough

    traces: list[dict[str, Any]] = []

    def _record(**kwargs: Any) -> None:
        traces.append(kwargs)

    monkeypatch.setattr(responses_passthrough, "record_provider_trace", _record)
    return traces
