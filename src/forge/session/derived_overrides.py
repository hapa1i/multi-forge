"""Read-only admission of parent overrides before any child creation effects."""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from shlex import quote
from typing import Any

import dacite

from .effective import compute_effective_intent
from .exceptions import (
    ForgeSessionError,
    InvalidDerivedSessionOverridesError,
    InvalidOverrideValueError,
)
from .models import SessionState
from .overrides import clear_overrides, delete_override

_LIFECYCLE_PATHS = (
    "launch.runtime",
    "launch.model_route",
    "authority",
    "consumer_lanes",
    "policy.supervisor.native_source",
)


def validate_derived_session_overrides(state: SessionState) -> None:
    """Reject invalid stored overrides without changing state or admitting a reviewer.

    Call after the strict manifest read and before route realization or child
    preparation. Only a refusal computes recovery, using the existing reset
    transition rules; valid parents need no supervisor, source or auth lookup.
    """
    key = _lifecycle_override(state.overrides)
    if key is not None:
        reason = "this field is owned by its lifecycle command"
    else:
        try:
            compute_effective_intent(state)
        except InvalidOverrideValueError as error:
            key = _invalid_path(state, error)
            reason = str(error.__cause__ or error)
        else:
            return
    raise InvalidDerivedSessionOverridesError(state.name, key, reason, _recovery(state, key))


def _lifecycle_override(overrides: dict[str, Any]) -> str | None:
    for path in _LIFECYCLE_PATHS:
        current: Any = overrides
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                break
            current = current[part]
        else:
            return path
    return None


def _invalid_path(state: SessionState, error: InvalidOverrideValueError) -> str:
    cause = error.__cause__
    field_path = getattr(cause, "field_path", None)
    if isinstance(field_path, str) and field_path:
        return field_path

    # Dacite preserves type-error paths, but not constructor ValueErrors. Find
    # the smallest supplied value that reproduces that failure against the
    # baseline. Interacting values retain their containing object's exact path.
    for path, value in _override_nodes(state.overrides):
        candidate = deepcopy(state)
        isolated: Any = value
        for part in reversed(path.split(".")):
            isolated = {part: isolated}
        candidate.overrides = isolated
        try:
            compute_effective_intent(candidate)
        except InvalidOverrideValueError as isolated_error:
            isolated_cause = isolated_error.__cause__
            if type(isolated_cause) is type(cause) and str(isolated_cause) == str(cause):
                return path
    return "overrides"


def _override_nodes(overrides: dict[str, Any], prefix: str = "") -> Iterator[tuple[str, Any]]:
    for key, value in overrides.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and value:
            yield from _override_nodes(value, path)
        yield path, value


def _valid_overrides(state: SessionState) -> bool:
    if _lifecycle_override(state.overrides) is not None:
        return False
    try:
        compute_effective_intent(state)
    except InvalidOverrideValueError:
        return False
    return True


def _reset_is_safe(state: SessionState, key: str | None) -> bool:
    from forge.policy.semantic.identity import (
        snapshot_supervisor_options,
        validate_supervisor_transition,
    )

    candidate = deepcopy(state)
    try:
        old = snapshot_supervisor_options(candidate)
    except AttributeError:
        # Dacite expects an object at this snapshot boundary; a truthy scalar
        # or list supervisor reaches data.keys() before its typed errors.
        return False
    except (dacite.DaciteError, TypeError, ValueError):
        return False
    try:
        if key is None:
            clear_overrides(candidate.overrides)
        elif not delete_override(candidate.overrides, key):
            return False
        if old and (key is None or key.split(".", 1)[0] in {"policy", "launch", "*"}):
            validate_supervisor_transition(candidate, old, compute_effective_intent(candidate))
        return _valid_overrides(candidate)
    except (dacite.DaciteError, ForgeSessionError, TypeError, ValueError):
        return False


def _recovery(state: SessionState, key: str) -> str:
    session = quote(state.name)
    reset = f"forge session reset --session {session}"
    if _reset_is_safe(state, key):
        return f"Run '{reset} {key}' before retrying."
    if _reset_is_safe(state, None):
        return f"Run '{reset} --all' before retrying. This clears all live overrides, including unrelated settings."

    if state.intent.policy and state.intent.policy.supervisor:
        from forge.policy.semantic.identity import SUPERVISOR_CONSUMER
        from forge.session.consumer_lanes import clear_consumer_lane

        candidate = deepcopy(state)
        assert candidate.intent.policy is not None
        candidate.intent.policy.supervisor = None
        delete_override(candidate.overrides, "policy.supervisor")
        clear_consumer_lane(candidate, SUPERVISOR_CONSUMER)
        remove = f"forge policy supervisor remove --session {session}"
        if _valid_overrides(candidate):
            return f"Run '{remove}' and reconfigure the supervisor before retrying."
        if _reset_is_safe(candidate, None):
            return (
                f"Run '{remove}', then '{reset} --all', and reconfigure the supervisor before retrying. "
                "This clears all live overrides, including unrelated settings."
            )

    return (
        f"Repair or restore the overrides in session '{state.name}' manifest before retrying; reset is not applicable."
    )
