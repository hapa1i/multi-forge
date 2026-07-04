"""Backend remote-reconciliation: adapter protocol, registry, and generic DTOs.

A backend's *remote* side answers "what did the account see?" for one of the backend's own
record ids (metadata only). This is the read / account-side sibling of ``backend.adapters``
(which owns local lifecycle): a source is **remote-reconcile capable iff it has a registered
adapter here** -- NOT via a ``ModelSourceCapabilities`` flag. A flag could drift from the code
that actually implements the lookup; registry presence is the single source of truth and keeps
an account-side read concern out of the proxy-write-path capability struct.

Error-vs-data rule: expected remote/network failures (timeout, connection error, 4xx, 5xx) are
returned as a renderable ``RemoteRecord(outcome=...)`` -- never raised -- so one bad lookup
cannot abort a reconciliation. ``RemoteAdapterError`` is reserved for adapter bugs / config
faults (e.g. no base URL) and never embeds an API key or a raw response body.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

RemoteOutcome = Literal["found", "not_found", "not_authorized", "unavailable"]
KeyClass = Literal["normal", "management"]


class RemoteAdapterError(RuntimeError):
    """An adapter bug or configuration fault (e.g. missing base URL).

    NOT for expected remote/network failures -- those are returned as a renderable
    ``RemoteRecord(outcome=...)``. Must never embed an API key or raw response body.
    """


class RemoteAdapterNotFoundError(LookupError):
    """Raised when a backend instance id has no registered remote-reconciliation adapter."""


@dataclass(frozen=True)
class RemoteCapability:
    """What a backend's remote side can answer, and which credential each path needs.

    Adapters declare a credential id **per path** so the op can emit one consistent setup hint
    without knowing provider specifics. The ``window_*`` fields declare the deferred
    windowed-activity follow-on seam; the MVP single-id path uses only ``single_lookup*``.
    """

    single_lookup: bool = False
    window_activity: bool = False
    window_analytics: bool = False
    single_lookup_key: KeyClass = "normal"
    single_lookup_credential_id: str | None = None
    window_key: KeyClass = "management"
    window_credential_id: str | None = None


@dataclass(frozen=True)
class RemoteRecord:
    """One backend-side record, metadata-only. Every HTTP/network result maps to an outcome.

    ``detail`` is a sanitized human string (status note / error class) -- never a key or a raw
    body. Token/cost fields are the backend's reported figures, kept separate from local
    evidence so the op never overwrites a locally observed cost with a remote one.
    """

    remote_id: str | None
    outcome: RemoteOutcome
    endpoint: str
    key_class: KeyClass = "normal"
    http_status: int | None = None
    remote_input_tokens: int | None = None
    remote_output_tokens: int | None = None
    remote_cost_micros: int | None = None
    remote_provider: str | None = None
    cancelled: bool | None = None
    remote_request_id: str | None = None
    detail: str | None = None


@runtime_checkable
class BackendRemoteAdapter(Protocol):
    """The read/account-side adapter for one backend instance.

    ``source_id`` is the internal registry key and matches the backend instance catalog id (e.g. ``"openrouter"``).
    ``fetch_activity`` is the windowed follow-on seam; MVP adapters may raise
    ``RemoteAdapterError`` from it (the single-id op never calls it).
    """

    source_id: str

    def capabilities(self) -> RemoteCapability: ...

    def lookup_remote_record(self, remote_id: str, *, timeout_s: float = 5.0) -> RemoteRecord: ...

    def fetch_activity(
        self, *, period_start: datetime | None, period_end: datetime | None, timeout_s: float = 5.0
    ) -> list[RemoteRecord]: ...


# Registry: mirrors backend.sources._SOURCE_BY_ID / backend.adapters.get_adapter. Populated by
# backend.remote.__init__ to keep this leaf import-light (no provider client imports here).
_REMOTE_ADAPTERS: dict[str, BackendRemoteAdapter] = {}


def register_remote_adapter(adapter: BackendRemoteAdapter) -> None:
    """Register an adapter under its ``source_id`` (last registration wins)."""
    _REMOTE_ADAPTERS[adapter.source_id] = adapter


def get_remote_adapter(source_id: str) -> BackendRemoteAdapter:
    """Return the remote adapter for a source id, or raise ``RemoteAdapterNotFoundError``."""
    try:
        return _REMOTE_ADAPTERS[source_id]
    except KeyError:
        raise RemoteAdapterNotFoundError(f"Backend '{source_id}' has no remote-reconciliation adapter") from None


def has_remote_adapter(source_id: str) -> bool:
    """Return whether a source id has a registered remote adapter."""
    return source_id in _REMOTE_ADAPTERS


def list_remote_adapter_ids() -> list[str]:
    """Return the sorted source ids that have a registered remote adapter."""
    return sorted(_REMOTE_ADAPTERS)
