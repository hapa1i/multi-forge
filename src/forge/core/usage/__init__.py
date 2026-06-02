"""Usage-attribution ledger (Phase 4).

The canonical attribution plane (``~/.forge/usage/events/``), joined to the cost and
audit planes by a shared proxy ``request_id`` via nullable ``source_refs``. See
``ledger`` for the schema and read/write contract.
"""

from .billing import infer_billing_mode
from .correlation import mint_request_id, target_is_forge_proxy, with_forge_request_id
from .emit import emit_direct_llm_usage, emit_usage_for_session_result
from .ledger import (
    USAGE_SCHEMA_VERSION,
    AttributionGranularity,
    BillingMode,
    MeasurementSource,
    SourceRefs,
    UsageEvent,
    log_usage_event,
    prune_usage_events,
    read_usage_events,
)

__all__ = [
    "USAGE_SCHEMA_VERSION",
    "AttributionGranularity",
    "BillingMode",
    "MeasurementSource",
    "SourceRefs",
    "UsageEvent",
    "emit_direct_llm_usage",
    "emit_usage_for_session_result",
    "infer_billing_mode",
    "log_usage_event",
    "mint_request_id",
    "prune_usage_events",
    "read_usage_events",
    "target_is_forge_proxy",
    "with_forge_request_id",
]
