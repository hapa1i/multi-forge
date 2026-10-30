"""Present the last outbound effort without claiming provider-side execution."""

from __future__ import annotations

from typing import Any

from forge.core.models.model_reference import strip_transport_model_suffix


def observation_label(
    record: dict[str, Any] | None,
    *,
    requested: str | None,
    model_id: str | None,
    route_model: str | None,
) -> tuple[str, bool]:
    """Return an annotation and warning posture from a validated runtime record."""
    if record is None:
        return "unknown", False
    dropped = record["wire"] == "dropped"
    applied = "dropped" if dropped else record["applied"] or "unknown"
    stale = (
        (requested is not None and requested != record["requested"])
        or (
            model_id is not None
            and strip_transport_model_suffix(model_id) != strip_transport_model_suffix(record["client_model"])
        )
        or (
            route_model is not None
            and strip_transport_model_suffix(route_model) != strip_transport_model_suffix(record["mapped_model"])
        )
    )
    if stale:
        return f"{applied} (stale)", dropped
    if applied != "unknown" and record["requested"] is not None and applied != record["requested"]:
        return f"{applied}<-{record['requested']}", dropped
    return applied, dropped
