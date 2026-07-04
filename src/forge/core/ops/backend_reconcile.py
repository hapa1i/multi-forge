"""Backend remote reconciliation (command-core op).

Joins LOCAL downstream telemetry evidence to REMOTE account-side evidence for one backend
instance. MVP: single-id lookup.

- ``--request-id`` (local-anchored): the local downstream trace under this backend -> its
  ``provider_generation_id`` -> the backend's remote record -> one joined entry.
- ``--remote-id`` (single-sided): a raw backend record id -> remote lookup, with no local side.

Generic over any backend with a registered remote adapter (``backend.remote``); OpenRouter is
the first. The bucket taxonomy is **comparative**: ``missing-remote`` / ``missing-local`` need
BOTH a local anchor and a remote answer, so a single-sided lookup yields only ``remote`` /
``not-queryable``. The coarse bucket plus a precise per-entry ``remote_outcome`` means no reason
is lost when outcomes share a bucket. Local and remote cost/tokens are kept separate with
provenance -- a remote figure never overwrites a locally observed one.

Remote/network failures are renderable data (``not-queryable``), never raised. ``ForgeOpError``
is reserved for an unknown backend, a backend with no adapter, and (request-id mode) no local
record at all -- never for a queryable-but-empty result.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from forge.backend.remote import get_remote_adapter
from forge.backend.remote.base import (
    BackendRemoteAdapter,
    KeyClass,
    RemoteAdapterNotFoundError,
    RemoteOutcome,
)
from forge.backend.sources import (
    BackendInstanceResolutionError,
    resolve_backend_instance_id,
)
from forge.core.telemetry.downstream import read_downstream_records

from .context import ExecutionContext
from .session import ForgeOpError

_log = logging.getLogger(__name__)

ReconcileMode = Literal["request-id", "remote-id"]
ReconcileBucket = Literal["local", "remote", "joined", "missing-local", "missing-remote", "not-queryable"]


@dataclass(frozen=True)
class ReconcileEntry:
    """One reconciliation row: local evidence and/or remote evidence, side by side.

    ``bucket`` is the coarse comparative classification; ``remote_outcome`` is the precise remote
    result (``None`` when no remote lookup was performed, e.g. a local trace with no generation
    id). Local fields are never overwritten by remote ones.
    """

    bucket: ReconcileBucket
    remote_outcome: RemoteOutcome | None
    request_id: str | None = None
    remote_id: str | None = None
    # Local evidence (provenance: local proxy-observed downstream record).
    local_cost_micros: int | None = None
    local_input_tokens: int | None = None
    local_output_tokens: int | None = None
    local_proxy_id: str | None = None
    # Remote evidence (provenance: the backend's account-side record).
    remote_cost_micros: int | None = None
    remote_input_tokens: int | None = None
    remote_output_tokens: int | None = None
    remote_provider: str | None = None
    remote_cancelled: bool | None = None
    remote_http_status: int | None = None
    detail: str | None = None


@dataclass(frozen=True)
class ReconcileResult:
    backend_instance_id: str
    mode: ReconcileMode
    entries: list[ReconcileEntry] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    needs_credential_id: str | None = None
    needs_key_class: str | None = None


def reconcile_generation(
    *,
    ctx: ExecutionContext,
    backend_instance_id: str,
    request_id: str | None = None,
    remote_id: str | None = None,
    timeout_s: float = 5.0,
) -> ReconcileResult:
    """Reconcile one local request id OR one raw remote id against a backend instance.

    Exactly one of ``request_id`` / ``remote_id`` must be given. Raises ``ForgeOpError`` for an
    unknown backend, a backend with no remote adapter, or (request-id mode) no local record.
    """
    _log.debug(
        "reconcile_generation: cwd=%s backend=%s req=%s remote=%s",
        ctx.cwd,
        backend_instance_id,
        request_id,
        remote_id,
    )
    # Treat empty strings as absent so the xor guard (truthiness) and the mode dispatch (below) agree;
    # otherwise --request-id "" would slip past the guard yet enter request-id mode via `is not None`.
    request_id = request_id or None
    remote_id = remote_id or None
    if bool(request_id) == bool(remote_id):
        raise ForgeOpError("Provide exactly one of --request-id or --remote-id")

    # Resolve template aliases (e.g. openrouter-anthropic) to the canonical backend instance id, like the
    # other `forge model backend` subcommands; the canonical id keys both the adapter and downstream reads.
    try:
        backend_instance_id = resolve_backend_instance_id(backend_instance_id)
    except BackendInstanceResolutionError as e:
        raise ForgeOpError(str(e)) from None
    try:
        adapter = get_remote_adapter(backend_instance_id)
    except RemoteAdapterNotFoundError:
        raise ForgeOpError(f"Backend '{backend_instance_id}' has no remote reconciliation adapter") from None

    if request_id is not None:
        mode: ReconcileMode = "request-id"
        entry = _reconcile_by_request_id(
            adapter=adapter,
            backend_instance_id=backend_instance_id,
            request_id=request_id,
            timeout_s=timeout_s,
        )
    else:
        assert remote_id is not None  # guaranteed by the xor check above
        mode = "remote-id"
        entry = _reconcile_by_remote_id(adapter=adapter, remote_id=remote_id, timeout_s=timeout_s)

    entries = [entry]
    # Counter[str] keeps the bucket Literals from narrowing counts to dict[ReconcileBucket, int].
    bucket_counts: Counter[str] = Counter(e.bucket for e in entries)
    counts: dict[str, int] = dict(bucket_counts)
    needs_credential_id, needs_key_class = _credential_hint(adapter, entries)
    return ReconcileResult(
        backend_instance_id=backend_instance_id,
        mode=mode,
        entries=entries,
        counts=counts,
        needs_credential_id=needs_credential_id,
        needs_key_class=needs_key_class,
    )


def _reconcile_by_request_id(
    *,
    adapter: BackendRemoteAdapter,
    backend_instance_id: str,
    request_id: str,
    timeout_s: float,
) -> ReconcileEntry:
    # Scope the read to THIS backend instance so an id that belongs to another backend cannot false-join.
    records = read_downstream_records(kind="attempt", backend_id=backend_instance_id, request_id=request_id)
    if not records:
        raise ForgeOpError(
            f"No local downstream record for request '{request_id}' under backend '{backend_instance_id}'. "
            "The id may belong to another backend."
        )
    latest = records[-1]  # read_downstream_records sorts ascending by ts -> last is newest
    local_cost = latest.reported_cost_micros if latest.reported_cost_micros is not None else latest.cost_micros

    gen_id = latest.provider_generation_id
    if not gen_id:
        # Queryable-but-empty local trace: renders the local evidence, never errors.
        return ReconcileEntry(
            bucket="not-queryable",
            remote_outcome=None,
            request_id=request_id,
            remote_id=None,
            local_cost_micros=local_cost,
            local_input_tokens=latest.input_tokens,
            local_output_tokens=latest.output_tokens,
            local_proxy_id=latest.proxy_id,
            detail="local trace has no provider generation id",
        )

    rec = adapter.lookup_remote_record(gen_id, timeout_s=timeout_s)
    return ReconcileEntry(
        bucket=_bucket_for_request_id_mode(rec.outcome),
        remote_outcome=rec.outcome,
        request_id=request_id,
        remote_id=rec.remote_id or gen_id,
        local_cost_micros=local_cost,
        local_input_tokens=latest.input_tokens,
        local_output_tokens=latest.output_tokens,
        local_proxy_id=latest.proxy_id,
        remote_cost_micros=rec.remote_cost_micros,
        remote_input_tokens=rec.remote_input_tokens,
        remote_output_tokens=rec.remote_output_tokens,
        remote_provider=rec.remote_provider,
        remote_cancelled=rec.cancelled,
        remote_http_status=rec.http_status,
        detail=rec.detail,
    )


def _reconcile_by_remote_id(*, adapter: BackendRemoteAdapter, remote_id: str, timeout_s: float) -> ReconcileEntry:
    rec = adapter.lookup_remote_record(remote_id, timeout_s=timeout_s)
    # Single-sided: no local anchor to be "missing" against, so anything but found is not-queryable.
    bucket: ReconcileBucket = "remote" if rec.outcome == "found" else "not-queryable"
    return ReconcileEntry(
        bucket=bucket,
        remote_outcome=rec.outcome,
        remote_id=rec.remote_id or remote_id,
        remote_cost_micros=rec.remote_cost_micros,
        remote_input_tokens=rec.remote_input_tokens,
        remote_output_tokens=rec.remote_output_tokens,
        remote_provider=rec.remote_provider,
        remote_cancelled=rec.cancelled,
        remote_http_status=rec.http_status,
        detail=rec.detail,
    )


def _bucket_for_request_id_mode(outcome: RemoteOutcome) -> ReconcileBucket:
    if outcome == "found":
        return "joined"  # local + remote present (cancelled or not -> still remote evidence)
    if outcome == "not_found":
        return "missing-remote"  # the incident: present locally, absent remotely (an aborted stream 404s)
    return "not-queryable"  # unavailable / not_authorized -> we could not get a remote answer


def _credential_hint(
    adapter: BackendRemoteAdapter, entries: list[ReconcileEntry]
) -> tuple[str | None, KeyClass | None]:
    if any(e.remote_outcome == "not_authorized" for e in entries):
        caps = adapter.capabilities()
        return caps.single_lookup_credential_id, caps.single_lookup_key
    return None, None


def render_reconcile_lines(result: ReconcileResult) -> list[str]:
    """Render a reconciliation result as stable plain text (no Rich, no secrets, no content)."""
    lines = [f"Backend reconcile: backend={result.backend_instance_id} mode={result.mode}"]
    if result.counts:
        lines.append("  buckets: " + ", ".join(f"{k}={v}" for k, v in sorted(result.counts.items())))
    for e in result.entries:
        ident = e.request_id or e.remote_id or "?"
        head = f"  [{e.bucket}] {ident}"
        if e.remote_outcome:
            status = f" {e.remote_http_status}" if e.remote_http_status is not None else ""
            head += f" (remote: {e.remote_outcome}{status})"
        lines.append(head)
        if e.local_cost_micros is not None or e.local_input_tokens is not None or e.local_output_tokens is not None:
            lines.append(
                f"    local : {_fmt_cost(e.local_cost_micros)}"
                f" in={_fmt_int(e.local_input_tokens)} out={_fmt_int(e.local_output_tokens)}"
            )
        if e.remote_outcome == "found":
            cancelled = "" if e.remote_cancelled is None else f" cancelled={e.remote_cancelled}"
            provider = f" provider={e.remote_provider}" if e.remote_provider else ""
            lines.append(
                f"    remote: {_fmt_cost(e.remote_cost_micros)}"
                f" in={_fmt_int(e.remote_input_tokens)} out={_fmt_int(e.remote_output_tokens)}{provider}{cancelled}"
            )
        if e.detail:
            lines.append(f"    note  : {e.detail}")
    if result.needs_credential_id:
        key = f" ({result.needs_key_class} key)" if result.needs_key_class else ""
        lines.append(f"  credential '{result.needs_credential_id}'{key} is required for this lookup.")
    return lines


def _fmt_cost(micros: int | None) -> str:
    return "cost=n/a" if micros is None else f"cost=${micros / 1_000_000:.6f}"


def _fmt_int(value: int | None) -> str:
    return "n/a" if value is None else str(value)
