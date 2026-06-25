"""Pure consumer-lane resolution (epic consumer_lanes, ticket T1a).

A *lane* is a concrete ``(runtime, backend, model)`` placement for a *consumer*
-- a unit of Forge LLM-work. This module is the pure, side-effect-free core of
that model: it classifies runtime execution capability, validates lanes against
the code-defined runtime and backend catalogs, and resolves a consumer to its
chosen lane.

Out of scope here, by design:

- **Transport** (direct vs proxy / ``base_url``): I/O-bound (proxy registry +
  health probes via ``resolve_subprocess_routing``); derived at dispatch (T3).
- **Persistence** of a consumer's chosen lane: the session-manifest binding (T1b).
- **Model-catalog membership**: ``model`` is validated as a non-empty id only, so
  the whole module stays I/O-free; full validation lands when a consumer is wired.

See ``docs/board/doing/epic_consumer_lanes/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from forge.backend.sources import ModelSourceNotFoundError, resolve_model_source_id
from forge.core.runtime.registry import RUNTIMES

ExecutionKind = Literal["single_shot", "tool_agent"]
CapabilityFloor = ExecutionKind

# The in-process single-shot runtime (``forge.core.llm``). It is deliberately NOT
# an entry in ``RUNTIMES`` -- that table is the *agent* runtime registry, iterated
# by ``list_runtimes()`` / ``installed_runtimes()``; a non-agent entry would
# pollute every caller. The lane runtime axis adds it here instead.
CORE_LLM_RUNTIME = "core_llm"

_FLOOR_RANK: dict[ExecutionKind, int] = {"single_shot": 0, "tool_agent": 1}


class LaneError(ValueError):
    """Raised when a lane or consumer is structurally invalid."""


@dataclass(frozen=True)
class Lane:
    """A concrete ``(runtime, backend, model)`` placement.

    Transport is intentionally absent (derived at dispatch). Construction
    validates the runtime (``RUNTIMES`` / ``core_llm``) and normalizes
    ``backend_id`` to its canonical ``ModelSource`` id (template aliases are
    accepted), so alias and canonical lanes compare equal. ``model`` must be
    non-empty; anything unknown raises ``LaneError``.
    """

    runtime_id: str
    backend_id: str
    model: str

    def __post_init__(self) -> None:
        runtime_execution(self.runtime_id)  # raises LaneError on unknown runtime
        try:
            canonical_backend = resolve_model_source_id(self.backend_id)
        except ModelSourceNotFoundError as e:
            raise LaneError(str(e)) from e
        # Store the canonical ModelSource id: resolve_model_source_id also accepts
        # template aliases, so normalizing keeps backend_id a real id, makes
        # alias/canonical lanes compare equal, and lets downstream
        # get_model_source(lane.backend_id) resolve.
        object.__setattr__(self, "backend_id", canonical_backend)
        if not self.model:
            raise LaneError("Lane requires a non-empty model id")


@dataclass(frozen=True)
class Consumer:
    """A unit of Forge LLM-work bound to a lane.

    Declares a capability ``capability_floor``, a ``default_lane``, and an
    optional small set of ``allowed_lanes`` (override candidates). The default
    must itself pass the floor + reachability gates, so an invalid default cannot
    be constructed and can never bypass the checks an override must pass.
    """

    id: str
    capability_floor: CapabilityFloor
    default_lane: Lane
    allowed_lanes: tuple[Lane, ...] = ()

    def __post_init__(self) -> None:
        if self.capability_floor not in _FLOOR_RANK:
            raise LaneError(f"Unknown capability_floor: {self.capability_floor!r}")
        if self.default_lane not in valid_lanes(self):
            raise LaneError(
                f"Consumer {self.id!r} default_lane {self.default_lane} fails its "
                f"floor {self.capability_floor!r} or reachability"
            )


def runtime_execution(runtime_id: str) -> ExecutionKind:
    """Return a lane runtime's execution capability.

    ``core_llm`` is ``single_shot``; every agent runtime in ``RUNTIMES`` is a
    ``tool_agent``. Raises ``LaneError`` for an unknown runtime.
    """
    if runtime_id == CORE_LLM_RUNTIME:
        return "single_shot"
    if runtime_id not in RUNTIMES:
        raise LaneError(f"Unknown runtime: {runtime_id!r}")
    return "tool_agent"


def valid_lanes(consumer: Consumer) -> tuple[Lane, ...]:
    """Return the consumer's declared candidate lanes that pass the gates.

    Candidates are ``default_lane`` plus ``allowed_lanes`` (de-duplicated, order
    preserved). A candidate is valid when its runtime satisfies the consumer's
    capability floor and its ``(runtime, backend)`` pair is reachable. This is a
    *filtered declared set*, never an enumerated ``runtime x backend x model``
    cross-product. For validation and option-listing, not failover.
    """
    result: list[Lane] = []
    seen: set[Lane] = set()
    for lane in (consumer.default_lane, *consumer.allowed_lanes):
        if lane in seen:
            continue
        seen.add(lane)
        if _satisfies_floor(lane.runtime_id, consumer.capability_floor) and _reachable(
            lane.runtime_id, lane.backend_id
        ):
            result.append(lane)
    return tuple(result)


def resolve_lane(consumer: Consumer, *, override: Lane | None = None) -> Lane:
    """Resolve a consumer to its chosen lane.

    Returns ``override`` when it is one of the consumer's valid lanes, else the
    ``default_lane`` (guaranteed valid by ``Consumer`` construction). Raises
    ``LaneError`` when an override is supplied but not valid. Pure -- no proxy,
    registry, network, or subprocess I/O.
    """
    if override is None:
        return consumer.default_lane
    if override in valid_lanes(consumer):
        return override
    raise LaneError(f"Override lane {override} is not valid for consumer {consumer.id!r}")


def _satisfies_floor(runtime_id: str, floor: CapabilityFloor) -> bool:
    return _FLOOR_RANK[runtime_execution(runtime_id)] >= _FLOOR_RANK[floor]


def _reachable(runtime_id: str, backend_id: str) -> bool:
    # T1a has no hard (runtime, backend) pins -- any catalog backend is reachable
    # by any lane runtime, and the capability floor does the filtering. T2 adds
    # subscription pins here (e.g. claude-max -> claude only, chatgpt -> codex).
    del runtime_id, backend_id  # intentionally unused until T2 introduces pins
    return True
