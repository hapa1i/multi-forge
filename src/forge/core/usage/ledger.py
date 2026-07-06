"""PID-sharded JSONL usage-attribution ledger (Phase 4).

The canonical *attribution* plane: "which run/workflow/session invoked which
runtime/provider/model via which route, and consumed what." Modeled on
``audit_logger.py`` (versioned, strictly read). During the downstream clean cut,
model-call evidence and redacted audit facts live in one downstream plane while
usage attribution stays separate and is joined by run ids or proxy ``request_id``:

- ``telemetry/downstream/*.jsonl`` -- model attempts plus redacted audit/drift/mutation facts
- ``usage/events/*.jsonl`` -- THIS plane: attribution, referencing downstream via
  nullable ``source_refs`` (``{cost_request_id, audit_request_id}``). Native-runtime
  events (Codex/Gemini) carry units directly and leave ``source_refs`` null.

Location: ``~/.forge/usage/events/YYYY-MM_<pid>.jsonl`` (owner-only, 0600). PID-sharded
like its siblings so concurrent writers (e.g. review workers across processes) never
contend on a single file.
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import dacite

from forge.core.paths import get_forge_home
from forge.core.state import decode_json_object, utc_timestamp_z
from forge.core.telemetry.jsonl_io import append_jsonl_record
from forge.core.usage.vocabulary import Confidence, Reporter, Route

logger = logging.getLogger(__name__)

USAGE_SCHEMA_VERSION = 1

_lock = threading.Lock()

# One-time warning latch for records written by a newer Forge.
_warned_newer_schema = False

# How the cost/token figures on an event were obtained. Never inferred or faked --
# an event that lacks an exact figure says so rather than guessing.
MeasurementSource = Literal[
    # Read-time provenance label only (Slice 4g): a stored event keeps
    # verb_snapshot_estimated, but the read surface recomputes a proxied run tree's
    # exact cost from the cost plane (sum of cost records by forge_root_run_id) and
    # labels that figure proxy_request_exact. Never written onto a stored event.
    "proxy_request_exact",
    "verb_snapshot_estimated",  # track_verb_cost snapshot delta (estimated; shared-proxy)
    "provider_usage_exact",  # in-band exact tokens: a direct core.llm call, OR a direct
    # `claude -p` envelope with usage but no cost (Phase 5, e.g. OAuth: tokens, no dollars)
    "runtime_native",  # a runtime self-reported its own cost+usage: a direct `claude -p
    # --output-format json` run (Phase 5, claude_code) or a native codex/gemini runtime
    "unattributed",  # no cost/token figure available (e.g. per-worker proxied claude -p)
]

AttributionGranularity = Literal["worker", "verb", "session"]

# How the work was billed. ``unknown`` is the honest default where the signal is
# ambiguous (Phase 4c infers this conservatively; it is never guessed).
BillingMode = Literal[
    "api",
    "subscription_interactive",
    "subscription_headless_credit",
    "subscription_quota",
    "unknown",
]


def _mint_event_id() -> str:
    """Mint a ledger event id (distinct from run ids; for dedupe/debugging)."""
    return f"evt_{uuid.uuid4().hex[:12]}"


@dataclass
class SourceRefs:
    """Back-references into the cost/audit planes by shared proxy ``request_id``.

    Null on native-runtime events (no proxy is involved) and on ``claude -p`` traffic
    until per-request correlation ships (Phase 4g) -- the event is still useful without
    them (run/model/billing_mode/tokens), it just lacks the exact wire back-reference.
    """

    cost_request_id: str | None = None
    audit_request_id: str | None = None


@dataclass
class UsageEvent:
    """One attribution record: a Forge-spawned unit of work and what it consumed.

    The required core identifies the actor (run/runtime/command + outcome). Everything
    else is defaulted so a record stays loadable as the schema grows, and
    ``schema_version``/``event_id``/``ts`` are auto-stamped so callers set only the
    meaningful fields.
    """

    # Required attribution core.
    run_id: str
    root_run_id: str
    runtime: str  # "claude_code" | "codex" | "gemini" | ...
    command: str  # verb/origin: "panel" | "memory-writer" | "supervisor" | "tagger" | ...
    status: str  # "success" | "error" | "timeout" | "skipped"

    # Optional attribution context.
    parent_run_id: str | None = None
    session: str | None = None
    workflow: str | None = None
    provider: str | None = None  # "anthropic" | "openai" | "vertex_ai" | "google" | ...
    model: str | None = None
    proxy_id: str | None = None

    # Billing + measurement provenance (provenance is explicit, never faked).
    billing_mode: BillingMode = "unknown"
    measurement_source: MeasurementSource = "unattributed"
    attribution_granularity: AttributionGranularity = "verb"
    # How the work reached the model, who supplied the metric evidence, and how
    # trustworthy the COST figure is. `confidence` is scoped to this event's own
    # cost_micro_usd ONLY (token provenance is measurement_source); a null cost is
    # "unavailable" regardless of any source_refs-joined cost record.
    route: Route | None = None
    reporter: Reporter | None = None
    confidence: Confidence = "unknown"

    # Consumption (nullable: not always knowable, e.g. per-worker claude -p).
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    latency_ms: float | None = None
    failure_type: str | None = None
    cost_micro_usd: int | None = None
    source_refs: SourceRefs | None = None

    # Auto-stamped envelope (defaulted, so they come last per dataclass ordering).
    schema_version: int = USAGE_SCHEMA_VERSION
    event_id: str = field(default_factory=_mint_event_id)
    ts: str = field(default_factory=utc_timestamp_z)


def _events_dir() -> Path:
    return get_forge_home() / "usage" / "events"


def _current_log_path() -> Path:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return _events_dir() / f"{month}_{os.getpid()}.jsonl"


# --- Write path (best-effort; never raises) ----------------------------------


def log_usage_event(event: UsageEvent) -> None:
    """Append a usage event to the PID-sharded JSONL ledger.

    Best-effort: write failures are logged at warning and swallowed -- attribution
    telemetry must never break the work it measures.
    """
    record = asdict(event)
    log_path = _current_log_path()
    append_jsonl_record(
        log_path,
        record,
        # Owner-only on both `usage/` and `usage/events/` so neither the records nor the
        # file-name timestamps leak to other local users (mirrors audit_logger).
        secure_dirs=(_events_dir().parent, _events_dir()),
        lock=_lock,
        logger=logger,
        warning_message="Failed to write usage event: %s",
    )


# --- Read path ---------------------------------------------------------------


def read_usage_events(
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    *,
    run_id: str | None = None,
    root_run_id: str | None = None,
    runtime: str | None = None,
    command: str | None = None,
    session: str | None = None,
) -> list[UsageEvent]:
    """Read and merge usage events across PID shards, sorted by timestamp.

    Skips, with a warning, lines that are malformed JSON, written by a newer Forge
    (``schema_version`` > ``USAGE_SCHEMA_VERSION``, surfaced once), or that fail strict
    shape validation (unknown fields are corruption, not forward-compat). Filters are
    applied to the raw record before the typed build, so a non-matching shard line costs
    no deserialization.
    """
    events_dir = _events_dir()
    if not events_dir.is_dir():
        return []

    global _warned_newer_schema
    events: list[UsageEvent] = []
    # Strict on shape AND value type: an unknown field is corruption, and so is an invalid
    # Literal (e.g. a bogus measurement_source) or a wrong nested type (source_refs=5). dacite
    # already accepts an int for a `float | None` field, so a 0ms latency still loads cleanly.
    config = dacite.Config(strict=True)
    for path in sorted(events_dir.glob("*.jsonl")):
        try:
            with open(path) as f:
                for line in f:
                    record = decode_json_object(line)
                    if record is None:
                        continue

                    ver = record.get("schema_version")
                    if isinstance(ver, int) and ver > USAGE_SCHEMA_VERSION:
                        if not _warned_newer_schema:
                            logger.warning(
                                "Skipping usage events written by a newer Forge (schema_version=%s); upgrade Forge",
                                ver,
                            )
                            _warned_newer_schema = True
                        continue

                    if run_id and record.get("run_id") != run_id:
                        continue
                    if root_run_id and record.get("root_run_id") != root_run_id:
                        continue
                    if runtime and record.get("runtime") != runtime:
                        continue
                    if command and record.get("command") != command:
                        continue
                    if session and record.get("session") != session:
                        continue

                    if period_start or period_end:
                        ts_str = record.get("ts", "")
                        try:
                            ts = datetime.fromisoformat(ts_str.rstrip("Z").removesuffix("+00:00") + "+00:00")
                        except (ValueError, TypeError, AttributeError):
                            continue
                        if period_start and ts < period_start:
                            continue
                        if period_end and ts >= period_end:
                            continue

                    try:
                        events.append(dacite.from_dict(UsageEvent, record, config=config))
                    except (dacite.DaciteError, TypeError, KeyError, ValueError) as e:
                        logger.warning("Skipping malformed usage event in %s: %s", path.name, e)
                        continue
        except OSError as e:
            logger.warning("Failed to read usage log %s: %s", path, e)

    events.sort(key=lambda e: e.ts)
    return events
