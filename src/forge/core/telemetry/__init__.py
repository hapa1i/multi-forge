"""Forge upstream/downstream telemetry primitives."""

from .downstream import (
    DOWNSTREAM_SCHEMA_VERSION,
    DownstreamRecord,
    read_downstream_records,
    write_downstream_record,
)
from .upstream import (
    UPSTREAM_SCHEMA_VERSION,
    UpstreamOutcome,
    read_upstream_outcomes,
    record_upstream_operation,
    should_record_upstream_outcome,
    write_upstream_outcome,
)

__all__ = [
    "DOWNSTREAM_SCHEMA_VERSION",
    "UPSTREAM_SCHEMA_VERSION",
    "DownstreamRecord",
    "UpstreamOutcome",
    "read_downstream_records",
    "read_upstream_outcomes",
    "record_upstream_operation",
    "should_record_upstream_outcome",
    "write_downstream_record",
    "write_upstream_outcome",
]
