"""Runtime-neutral headless invocation interface (Phase 4d).

A :class:`HeadlessInvoker` runs already-shaped subprocess jobs -- single-shot
(:meth:`run`) or parallel fan-out (:meth:`run_parallel`) -- owning the subprocess
lifecycle (process groups, ``SIGTERM``->``SIGKILL`` cleanup, ``ThreadPoolExecutor``
ordering, per-job timeout) and usage emission.

Routing and prompt derivation stay in the caller (review domain); a request
arrives already routed (``argv`` + ``env`` resolved). This is the seam Phase 5
swaps to add a Codex runtime without touching the review/supervisor/memory-writer
callers: the lifecycle is shared, only the request-shaping differs per runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from forge.core.usage.ledger import BillingMode


@dataclass(frozen=True)
class Attribution:
    """Verb context the invoker cannot infer from ``argv`` alone.

    When a request carries one, the invoker emits a per-job :class:`UsageEvent`
    (granularity ``"worker"``). ``command`` is the verb (``"panel"`` ...);
    ``workflow``/``session`` are optional context; ``runtime`` tags the engine.
    ``billing_mode`` carries a runtime's resolved billing posture (Codex's
    :class:`CodexPreflight.billing_mode`) to the usage event -- the invoker can't
    infer it from argv, and Claude leaves it ``None`` (its mode is inferred at emit).
    """

    command: str
    workflow: str | None = None
    session: str | None = None
    runtime: str = "claude_code"
    billing_mode: BillingMode | None = None


@dataclass
class HeadlessRequest:
    """One already-routed subprocess job: full ``argv`` + stdin ``prompt`` + ``env``.

    The ``env`` is expected to already carry the run-tree identity (stamped by
    ``build_claude_env``); the invoker reads it back onto the result. ``label`` is
    echoed to the result so the caller can map outputs back to inputs (e.g. the
    review ``worker_id``); ``model`` is recorded on any emitted usage event.
    """

    argv: list[str]
    prompt: str
    env: dict[str, str]
    cwd: str | None = None
    timeout_seconds: int = 600
    label: str | None = None
    # Per-worker attribution recorded on the emitted UsageEvent: the actual routed
    # model/provider/proxy (not the caller's friendly catalog id).
    model: str | None = None
    provider: str | None = None
    proxy_id: str | None = None
    attribution: Attribution | None = None
    # Phase 5: the invoker injects `--output-format <fmt>` (capability-gated) -- callers
    # set this, NEVER a raw --output-format in argv. base_url drives cost precedence
    # (proxied -> proxy cost wins; direct -> the runtime self-report wins; see emit.py).
    output_format: str | None = "json"
    base_url: str | None = None


@dataclass
class HeadlessResult:
    """Raw outcome of one job. The invoker never raises -- spawn-level failures
    (missing binary, OS error) land in ``error``; a non-zero exit leaves ``error``
    ``None`` so the caller applies its own formatting. ``run_id``/``parent``/``root``
    are surfaced from the job's ``env`` for usage attribution."""

    label: str | None
    stdout: str
    stderr: str
    returncode: int
    duration_seconds: float
    timed_out: bool = False
    # Interrupted at/just-before spawn (cancellation), not a genuine failure: keeps
    # ``error="cancelled"`` for display but suppresses per-worker usage emission.
    cancelled: bool = False
    error: str | None = None
    run_id: str | None = None
    parent_run_id: str | None = None
    root_run_id: str | None = None
    # Phase 5: runtime-self-reported cost/usage from --output-format json (nullable;
    # cost None when the route reported none). ``envelope_parsed`` is independent of
    # cost presence. ``runtime_is_error`` (already is-error-reliable-gated) steers the
    # usage status only; ``success`` stays returncode-based (no consumer regression).
    cost_micro_usd: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    envelope_parsed: bool = False
    runtime_is_error: bool = False
    # Runtime-native resume/session id, when the runtime announces one in-band:
    # Codex fills it from the stream's `thread.started.thread_id` (the
    # `codex exec resume` id); Claude leaves it None (its session id is Forge-owned
    # via --session-id, not read back from output).
    runtime_session_id: str | None = None

    @property
    def success(self) -> bool:
        """True iff the process exited 0 without timing out or spawn error."""
        return self.returncode == 0 and not self.timed_out and self.error is None


class HeadlessInvoker(Protocol):
    """A runtime that runs headless jobs. Implementations: ``ClaudeHeadlessInvoker``
    (Phase 4d), ``CodexHeadlessInvoker`` (Phase 5)."""

    def run(self, request: HeadlessRequest) -> HeadlessResult:
        """Run one job single-shot."""
        ...

    def run_parallel(self, requests: list[HeadlessRequest]) -> list[HeadlessResult]:
        """Run jobs concurrently; return results in input order."""
        ...
