"""Read effort from final SDK kwargs without changing the outbound request."""

from typing import Any

from forge.core.effort_observation import AppliedEffort


def applied_effort(kwargs: dict[str, Any], wire: str) -> AppliedEffort:
    """Match the SDK's shallow body merge, where extra_body wins duplicate keys."""
    body = dict(kwargs)
    extra_body = kwargs.get("extra_body")
    if isinstance(extra_body, dict):
        body.update(extra_body)
    value: Any = body
    for field in wire.split("."):
        value = value.get(field) if isinstance(value, dict) else None
    if isinstance(value, str):
        return AppliedEffort(applied=value, wire=wire)
    return AppliedEffort(applied=None, wire=None)
