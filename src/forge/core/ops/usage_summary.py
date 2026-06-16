"""Per-session Forge activity summary (command-core).

Aggregates two already-captured planes into one view a human can read:

- the usage-attribution ledger (``usage/events``) -> per-command run/error counts,
  tokens, and reported-or-estimated cost. Uncapped and reliable; the authoritative
  source for "how many times did the supervisor run, and how many failed".
- the session manifest's ``confirmed.policy.decisions`` -> supervisor allow/warn/deny
  and warning text. Capped at ``MAX_DECISION_LOG`` (so ``log_capped`` is surfaced).

The two planes measure related-but-distinct things and are kept separate on purpose
(a cached supervisor verdict is a policy *decision* with no ledger event; a failed
``claude -p`` is a ledger *error* the decision log may record as a fail-open allow).

Pure logic (no Click, no printing), per design §3.12: returns a
:class:`SessionActivitySummary`. Rendered by ``forge activity`` (table) and the
session-end launcher line (:func:`render_summary_line`). The manifest is **re-read
fresh from disk** because hooks mutate ``confirmed.*`` during the run, after the
launcher's in-memory copy was taken.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from forge.core.usage.ledger import UsageEvent, read_usage_events
from forge.core.usage.vocabulary import ROUTE_CLAUDE_INTERACTIVE, Confidence

logger = logging.getLogger(__name__)

_SUPERVISOR_POLICY_ID = "semantic.supervisor"
_PLAN_CHECK_POLICY_ID = "semantic.plan_check"
_ERROR_STATUSES = {"error", "timeout"}
_WORKFLOW_COMMANDS = {"panel", "analyze", "debate", "consensus"}
_MAX_RECENT_WARNINGS = 5
# Confidences whose dollar figure is trustworthy enough to count toward Forge-added
# spend (`forge +$Y`): a directly-reported figure or a gateway-computed one.
# `inferred` (a local estimate), `unavailable`, and `unknown` never contribute -- the
# north star is to sum what a route reported, never an estimate.
_FORGE_ADDED_COST_CONFIDENCES: frozenset[Confidence] = frozenset({"reported", "gateway_calculated"})


@dataclass
class CommandUsage:
    """Ledger-derived rollup for one command (supervisor, memory-writer, panel, ...)."""

    command: str
    # Logical invocations: verb/session-granularity events only. A workflow fan-out
    # (panel/debate/...) emits ONE verb-aggregate event plus N per-worker leaf events,
    # all sharing this command -- counting the leaves here would report one 4-worker
    # panel as 5 calls/workflows, so worker events are split into `workers` below.
    calls: int = 0
    errors: int = 0  # status in {error, timeout}, among `calls` (worker errors are not counted here)
    # Per-display-kind split of `errors` (generic, keyed by the `_failure_kind` vocab:
    # "timeout"/"error"). `errors == sum(error_kinds.values())` for ledger-derived rows.
    # This is generic error data -- NOT "fail-open": the supervisor formatter is the only
    # caller that interprets it as failing open (a memory-writer/panel error is not one).
    error_kinds: dict[str, int] = field(default_factory=dict)
    workers: int = 0  # per-worker fan-out leaf events (claude -p); not part of `calls`
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_micro_usd: int | None = None  # sum where measured; None if no event carried cost
    # False when no verb-snapshot estimate is mixed into this command's figure -- i.e. it
    # is entirely cost-plane-exact (4g root-join) and/or runtime-reported (runtime_native)
    # -> rendered without the `~` estimate marker. Defaults True: the safe caveat for
    # hand-built summaries (see SessionActivitySummary.cost_estimated).
    cost_estimated: bool = True


@dataclass
class PolicyActivity:
    """Decision-log-derived supervisor + plan-check activity (capped at MAX_DECISION_LOG).

    The plan-check counters come from the decision log, not the usage ledger, so
    cached tier-1 allows ARE counted (a cached allow is logged but emits no ledger
    event). Short-circuit rate = plan_check_allow vs plan_check_needs_review; the
    supervisor counters are the resolver runs (a tier-1 needs_review co-occurring
    with a deterministic deny skips the resolver, so needs_review can exceed
    supervisor checks).
    """

    supervisor_allow: int = 0
    supervisor_warn: int = 0
    supervisor_deny: int = 0
    plan_check_allow: int = 0
    plan_check_needs_review: int = 0
    total_warnings: int = 0
    recent_warnings: list[str] = field(default_factory=list)
    log_capped: bool = False

    @property
    def has_content(self) -> bool:
        return bool(
            self.supervisor_allow
            or self.supervisor_warn
            or self.supervisor_deny
            or self.plan_check_allow
            or self.plan_check_needs_review
            or self.total_warnings
        )


@dataclass
class ShadowActivity:
    """Supervisor shadow-sampling audit results, read from the session's shadow dir.

    Counts come from the candidate *records* (not the ledger): a ``.done`` record
    carries a terminal ``status``; ``*.json``/``.processing`` records are captured but
    not yet drained. ``disagree`` is the headline -- a fresh tier-1 allow the frontier
    would have *blocked* (the cascade's measured false-aligned rate). Per-check spend
    is the separate ``supervisor-shadow`` ledger row (in ``commands``), not here.
    """

    checked: int = 0  # terminal (.done) records
    agree: int = 0
    disagree: int = 0
    inconclusive: int = 0
    error: int = 0
    pending: int = 0  # captured but not yet drained (*.json + .processing)

    @property
    def has_content(self) -> bool:
        return bool(self.checked or self.pending)


@dataclass
class SessionActivitySummary:
    """What a Forge session did: per-command usage + supervisor/policy activity."""

    session: str
    since: str | None = None  # ISO8601 lower bound, or None for lifetime
    commands: list[CommandUsage] = field(default_factory=list)
    total_cost_micro_usd: int | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_events: int = 0
    policy: PolicyActivity | None = None
    shadow: ShadowActivity | None = None
    subagents: int = 0
    # Explicit coverage flags (JSON-friendly) so a sparse summary reads honestly.
    cost_partial: bool = False  # some in-scope events lacked a measured cost
    # False when no verb-snapshot estimate is mixed into the shown total -- the figure is
    # entirely cost-plane-exact (4g root-join) and/or runtime-reported (runtime_native) ->
    # rendered without the `~` marker. Defaults True so a hand-built summary stays honestly
    # approximate until the builder proves it (same safe-caveat rationale as
    # session_tagging_partial below).
    cost_estimated: bool = True
    # Some Forge LLM calls (e.g. the action tagger) never tag a session, so a per-session
    # view can undercount. The builder sets this True only when the session has activity
    # (an empty summary has nothing to be partial about); the default True is the safe
    # caveat for hand-built summaries.
    session_tagging_partial: bool = True

    @property
    def is_empty(self) -> bool:
        return (
            not self.commands
            and (self.policy is None or not self.policy.has_content)
            and (self.shadow is None or not self.shadow.has_content)
            and self.subagents == 0
        )


def build_session_activity_summary(
    session_name: str,
    forge_root: str | None,
    *,
    since: datetime | None = None,
) -> SessionActivitySummary:
    """Aggregate ledger + manifest into a :class:`SessionActivitySummary`.

    ``since`` bounds both planes (ledger by event ``ts``, decisions by
    ``evaluated_at``). Best-effort: a missing manifest or unreadable ledger yields a
    valid, partial summary rather than raising.
    """
    summary = SessionActivitySummary(session=session_name, since=since.isoformat() if since else None)

    _aggregate_ledger(summary, session_name, since)

    manifest = _load_manifest(session_name, forge_root)
    if manifest is not None:
        summary.policy = _policy_activity(manifest, since)
        subagents = manifest.confirmed.subagents
        if subagents is not None:
            summary.subagents = int(subagents.total_count)

    summary.shadow = _shadow_activity(forge_root, session_name, since)

    # Untagged emitters (e.g. the action tagger) never tag a session, so a per-session
    # view can undercount -- but only flag that once the session has activity to
    # contextualize it; claiming partial coverage of an empty summary is noise.
    summary.session_tagging_partial = not summary.is_empty
    return summary


def format_failing_open(cmd: CommandUsage | None) -> str | None:
    """Return a supervisor fail-open clause from a command's ``error_kinds``, or ``None``.

    Gated on ``error_kinds`` (not ``errors``): real ledger rows always co-populate both,
    so an ``errors > 0`` row with empty ``error_kinds`` is a hand-built/internal summary
    -- callers fall back to the plain ``errors`` count rather than fabricate kinds. The
    "failing open" framing is supervisor-specific; only the supervisor render calls this.

    An empty *or* all-zero ``error_kinds`` (e.g. a hand-built ``{"timeout": 0}``) yields
    ``None``, never a content-less ``"failing open: "`` -- the value count, not just the
    dict's presence, decides whether there is a clause to render.
    """
    if cmd is None or not any(cmd.error_kinds.values()):
        return None
    order = ("timeout", "error")
    parts = [f"{cmd.error_kinds[k]} {k}" for k in order if cmd.error_kinds.get(k)]
    # Defensive: surface any unexpected kind outside the canonical timeout/error vocab.
    parts += [f"{n} {k}" for k, n in cmd.error_kinds.items() if k not in order and n]
    return "failing open: " + ", ".join(parts)


def render_summary_line(summary: SessionActivitySummary) -> str | None:
    """Return a one-line session-end summary, or None when there is nothing to show.

    Pure formatter (no printing) so the launcher and tests share it.
    """
    parts: list[str] = []

    sup_cmd = next((c for c in summary.commands if c.command == "supervisor"), None)
    sup_errors = sup_cmd.errors if sup_cmd else 0
    # The error clause: the per-kind fail-open breakdown when the ledger recorded kinds
    # (real data), else the plain count for a hand-built summary (error_kinds empty). The
    # `or` fallback is load-bearing -- it must never silently drop a known error count.
    failing = format_failing_open(sup_cmd) or (f"{sup_errors} errors" if sup_errors else None)
    pol = summary.policy
    if pol and pol.has_content:
        if pol.plan_check_allow or pol.plan_check_needs_review:
            parts.append(f"plan-check: {pol.plan_check_allow} allow, {pol.plan_check_needs_review} needs-review")
        # `checks` (allow+warn+deny) is the capped decision-log count; `sup_errors` is the
        # uncapped ledger count -- different planes. A supervisor error fails open to an
        # `allow`, so normally errors <= checks; only decision-log eviction breaks that. So
        # when the log is at capacity render `checks` as a floor ("12+"), otherwise a capped
        # 100 checks beside 120 ledger errors reads as a contradiction instead of eviction.
        checks = pol.supervisor_allow + pol.supervisor_warn + pol.supervisor_deny
        if checks or sup_errors:
            # An all-short-circuit cascade session has plan-check content but zero
            # supervisor checks -- "supervisor: 0 checks" would be noise, skip it.
            checks_label = f"{checks}+" if pol.log_capped else str(checks)
            seg = f"supervisor: {checks_label} checks ({pol.supervisor_warn} warn, {pol.supervisor_deny} block"
            seg += f", {failing})" if failing else ")"
            parts.append(seg)
    elif sup_cmd is not None:
        seg = f"supervisor: {sup_cmd.calls} runs"
        if failing:
            seg += f" ({failing})"
        parts.append(seg)

    sh = summary.shadow
    if sh is not None and sh.has_content:
        # At session end the candidates were just enqueued (drain runs on a LATER CLI
        # invocation), so `pending` is the usual case; a later `forge activity` shows
        # `audited`. Lead with the disagree headline once any are checked.
        if sh.checked:
            seg = f"shadow: {sh.checked} audited ({sh.disagree} disagree"
            seg += f", {sh.error} error)" if sh.error else ")"
            parts.append(seg)
        elif sh.pending:
            parts.append(f"shadow: {sh.pending} queued")

    if summary.total_cost_micro_usd is not None:
        # `~` flags the figure as approximate (the aggregate mixes route-reported cost with
        # verb-snapshot estimates); when no snapshot estimate is mixed in (cost-plane-exact
        # and/or runtime-reported) it is dropped. `forge proxy costs show` stays authoritative.
        prefix = "~" if summary.cost_estimated else ""
        parts.append(f"{prefix}${summary.total_cost_micro_usd / 1_000_000:.2f}")

    tokens = summary.total_input_tokens + summary.total_output_tokens
    if tokens:
        parts.append(f"{_fmt_tokens(tokens)} tok")

    workflows = sum(c.calls for c in summary.commands if c.command in _WORKFLOW_COMMANDS)
    if workflows:
        parts.append(f"{workflows} workflow{'s' if workflows != 1 else ''}")

    if summary.subagents:
        parts.append(f"{summary.subagents} subagent{'s' if summary.subagents != 1 else ''}")

    if not parts:
        return None
    return "Forge this session — " + " · ".join(parts)


def sum_forge_added_cost(session: str, *, since: datetime | None = None) -> int | None:
    """Sum reported Forge-added LLM cost (micro-USD) for one session.

    "Forge-added" = LLM spend Forge originated on the session's behalf (memory
    writer, supervisor, review fan-out), **excluding the main interactive harness**
    (``route="claude_interactive"``). The harness exclusion is load-bearing, not
    cosmetic: the card forbids blending observed main-harness traffic into "Forge
    additional cost" (a future MITM scenario where such events land in the ledger).

    Only reported or gateway-calculated cost events contribute (the north star:
    record what a route reported, never estimate); ``inferred``/``unavailable`` rows
    add nothing. Returns the summed
    micro-USD, or ``None`` when no in-scope event carried a reported cost — distinct
    from a measured $0. A ledger read error propagates (the throttle decides whether
    to cache or skip); this function never fabricates a value.

    ``since`` bounds the scan to events at/after the session's start (pass the
    manifest ``created_at``) so the status-line poll does not re-glob and re-parse
    the whole uncapped, PID-sharded ledger each time. Omitting it scans every shard
    (correct, just slower) — an event can never predate its session's creation, so
    the bound is loss-free.

    Known limitation (matches ``build_session_activity_summary``): the ledger is
    filtered by session NAME only — ``UsageEvent`` carries no forge-root identity, so
    two same-named sessions in different forge roots would share this total. The
    status-line throttle cache key is root-scoped, but the ledger query is not.
    Adding root/session identity to the ledger schema is deferred to a future card.
    """
    events = read_usage_events(session=session, period_start=since)
    return _join_session_cost(events, since, exclude_interactive=True, trusted_only=True).total


@dataclass
class SupervisorHealth:
    """Recent fail-open health of the frontier supervisor, read from the usage ledger.

    ``recent_failures`` is the newest-first contiguous run of ``error``/``timeout``
    supervisor events (reset by the first ``success``); ``last_kind`` is the display
    kind of the newest failure (``"timeout"`` | ``"error"``) and ``last_seen_at`` its
    ``ts``. Empty (``0``/``None``/``None``) means the most recent supervisor run
    succeeded -- or none ran.

    v1 covers only the timeout/subprocess fail-opens the ledger records as a
    non-``success`` ``status``; parse fail-opens (logged ``success``) and auth/proxy
    fail-opens (no event) are out of scope (deferred to ``upstream_downstream_ledgers``).
    """

    recent_failures: int = 0
    last_kind: str | None = None
    last_seen_at: str | None = None


def _failure_kind(failure_type: str | None) -> str:
    """Map a ledger ``failure_type`` to a display kind: ``timeout`` (exact) or ``error``.

    The single source of the kind vocabulary, shared by :func:`read_supervisor_health`
    (the status-line consecutive streak) and :func:`_aggregate_ledger` (the activity
    window count). ``None``/subprocess/exit/runtime failures all map to ``error``.
    """
    return "timeout" if failure_type == "timeout" else "error"


def read_supervisor_health(session: str, *, since: datetime | None = None) -> SupervisorHealth:
    """Return the recent consecutive frontier-supervisor fail-open run for ``session``.

    Reads ``command="supervisor"`` events newest-first (the ledger sorts ascending by
    ``ts``) and counts the contiguous ``status in {"error","timeout"}`` prefix, breaking
    at the first non-failure. ``last_kind`` maps the newest failure's ``failure_type`` to
    ``"timeout"`` (exact) or ``"error"`` (everything else: subprocess/exit/runtime).

    Frontier-only: ``command="supervisor"`` excludes ``"supervisor-shadow"`` and
    ``"plan-check"`` by exact match. ``since`` bounds the scan to events at/after session
    creation (an event cannot predate it), mirroring :func:`sum_forge_added_cost`. An
    unexpected read error propagates (the throttle decides whether to cache or skip); the
    common corruption -- malformed lines and per-shard ``OSError`` -- is swallowed by
    ``read_usage_events``, so a readable-but-corrupt ledger yields empty health.

    Ordering invariant at the success/failure boundary: ``read_usage_events`` *stable*-sorts
    by ``ts``, and ``ts`` is seconds-granularity, so same-second events are NOT disambiguated
    by ``ts`` -- their order is the stable sort preserving each shard's chronological append
    order. The frontier supervisor is a single sequential hook in one Claude Code process
    (one PID shard), so its same-second events stay correctly ordered. A future multi-process
    supervisor emitting same-second events across shards could mis-order a success/failure
    boundary and miscount the streak by one; sub-second ``ts`` resolution would remove the
    dependency.
    """
    events = read_usage_events(session=session, command="supervisor", period_start=since)
    count = 0
    last_kind: str | None = None
    last_seen_at: str | None = None
    for event in reversed(events):  # newest-first (read_usage_events sorts ascending by ts)
        if event.status not in _ERROR_STATUSES:
            break  # the first non-failure (a success) ends the recent fail-open run
        if count == 0:  # the newest failure defines the displayed kind + timestamp
            last_kind = _failure_kind(event.failure_type)
            last_seen_at = event.ts
        count += 1
    if count == 0:
        return SupervisorHealth()
    return SupervisorHealth(recent_failures=count, last_kind=last_kind, last_seen_at=last_seen_at)


# --- internals ---------------------------------------------------------------


@dataclass
class _CostJoin:
    """Result of :func:`_join_session_cost`: the session's cost with provenance flags."""

    total: int | None  # summed micro-USD, or None when nothing in scope carried cost
    partial: bool  # some in-scope run/event carried no usable cost (incomplete coverage)
    by_command: dict[str, int]  # per-command micro-USD
    estimated: bool  # the total mixes in at least one verb-snapshot estimate (-> `~`)
    estimated_commands: set[str]  # commands whose figure includes a snapshot estimate


def _join_session_cost(
    events: list[UsageEvent],
    since: datetime | None,
    *,
    exclude_interactive: bool,
    trusted_only: bool,
) -> _CostJoin:
    """Authoritative session cost (micro-USD) via the 4g root-join, with event fallback.

    Proxied ``claude -p`` runs that flowed through a Forge proxy take their cost from
    the **cost plane** (exact, summed by ``forge_root_run_id``) and their event
    snapshots are **suppressed** so nothing double-counts; direct (``runtime_native``)
    and pre-4g runs keep their event-sourced cost. The split is race-free: the cost
    plane is read at query time, long after every request flushed its record.

    Suppression is **per-run-subtree**, not whole-root: a snapshot is superseded only
    when its OWN run produced cost records, or it is a verb whose DIRECT children did
    (fan-out). Keying on the whole root would silently drop the snapshot of a
    correctly-unstamped sibling (e.g. a supervisor routed off-Forge) that shares the
    session root with a stamped run -- an undercount with no exact figure to replace it.
    Known edge: a verb whose workers were ALL cancelled (no worker events) can't have
    its fan-out parentage reconstructed; in practice that run also skips its own emit,
    so no orphaned snapshot survives to double-count.

    ``exclude_interactive`` drops the harness channel (``route="claude_interactive"``)
    -- the load-bearing no-blend rule for ``forge +$Y``. ``trusted_only`` keeps only
    ``reported``/``gateway_calculated`` event cost (``forge +$Y``); the activity table
    passes False to preserve its "reported-or-estimated, best-effort" semantics. The
    cost-plane figures are always reported (the writer only sums reported micros).
    """
    roots = {e.root_run_id for e in events if e.root_run_id}
    per_run: dict[str, int] = {}
    runs_with_records: set[str] = set()
    if roots:
        try:
            from forge.proxy.cost_logger import sum_reported_cost_by_root

            join = sum_reported_cost_by_root(roots, since=since)
            per_run = join.per_run
            runs_with_records = join.runs_with_records
        except Exception as e:  # best-effort: a cost-plane read failure falls back to event cost
            logger.debug("4g cost-plane root join failed; using event cost: %s", e)

    run_to_command = {e.run_id: e.command for e in events if e.run_id}
    # Fan-out parentage: a verb whose DIRECT children produced cost records is superseded
    # by those exact records. Derived from worker events (parent_run_id == the verb's run,
    # set by build_claude_env and threaded onto the worker event), so suppression stays
    # per-subtree -- never whole-root.
    producer_parents = {e.parent_run_id for e in events if e.run_id in runs_with_records and e.parent_run_id}

    by_command: dict[str, int] = {}
    estimated_commands: set[str] = set()
    total = 0
    any_cost = False
    estimated = False
    # A run that reached the proxy but reported no dollars (records present, not in
    # per_run -- e.g. anthropic-passthrough) is accounted (snapshot suppressed) yet
    # priceless: the figure shown is incomplete -> partial.
    partial = bool(runs_with_records - set(per_run))

    # Exact cost-plane cost (proxied 4g), attributed per run -> command.
    for run_id, micros in per_run.items():
        total += micros
        any_cost = True
        cmd = run_to_command.get(run_id)
        if cmd is not None:
            by_command[cmd] = by_command.get(cmd, 0) + micros

    # Event-sourced residual for runs the cost plane did NOT supersede.
    for event in events:
        if exclude_interactive and event.route == ROUTE_CLAUDE_INTERACTIVE:
            continue
        superseded = event.run_id in runs_with_records or (
            event.measurement_source == "verb_snapshot_estimated" and event.run_id in producer_parents
        )
        if superseded:
            continue  # cost comes from the cost plane (exact), not this event's snapshot
        ev_micros = event.cost_micro_usd
        if trusted_only and event.confidence not in _FORGE_ADDED_COST_CONFIDENCES:
            ev_micros = None
        if ev_micros is not None:
            total += ev_micros
            any_cost = True
            by_command[event.command] = by_command.get(event.command, 0) + ev_micros
            if event.measurement_source == "verb_snapshot_estimated":
                estimated = True  # a snapshot estimate, not an exact cost-plane figure
                estimated_commands.add(event.command)
        else:
            partial = True

    return _CostJoin(
        total=total if any_cost else None,
        partial=any_cost and partial,
        by_command=by_command,
        estimated=estimated,
        estimated_commands=estimated_commands,
    )


def _aggregate_ledger(summary: SessionActivitySummary, session_name: str, since: datetime | None) -> None:
    try:
        events = read_usage_events(period_start=since, session=session_name)
    except Exception as e:  # best-effort: telemetry read must not break the summary
        logger.debug("usage summary: ledger read failed for %s: %s", session_name, e)
        return

    summary.total_events = len(events)
    by_command: dict[str, CommandUsage] = {}

    # Counts + tokens come straight off the events. Cost is computed separately by the
    # 4g root-join below (proxied claude -p exact, snapshot-suppressed) -- summing
    # event cost inline here would double-count a fan-out (verb snapshot + exact workers).
    for event in events:
        cu = by_command.setdefault(event.command, CommandUsage(command=event.command))
        # A fan-out's per-worker leaves share the verb's command; count them apart so
        # `calls` (and the workflow tally derived from it) stays one-per-invocation.
        if event.attribution_granularity == "worker":
            cu.workers += 1
        else:
            cu.calls += 1
            if event.status in _ERROR_STATUSES:
                cu.errors += 1
                # Generic per-kind split (uniform over all commands; only the supervisor
                # render interprets it as "failing open"). Real error events always carry
                # a kind, so `errors == sum(error_kinds.values())` for ledger-derived rows.
                kind = _failure_kind(event.failure_type)
                cu.error_kinds[kind] = cu.error_kinds.get(kind, 0) + 1
        if event.input_tokens:
            cu.input_tokens += event.input_tokens
            summary.total_input_tokens += event.input_tokens
        if event.output_tokens:
            cu.output_tokens += event.output_tokens
            summary.total_output_tokens += event.output_tokens
        if event.cached_tokens:
            cu.cached_tokens += event.cached_tokens

    cost = _join_session_cost(events, since, exclude_interactive=True, trusted_only=False)
    for cmd, micros in cost.by_command.items():
        cu = by_command.setdefault(cmd, CommandUsage(command=cmd))
        cu.cost_micro_usd = micros
        cu.cost_estimated = cmd in cost.estimated_commands  # exact (cost-plane) -> no `~`

    summary.commands = sorted(by_command.values(), key=lambda c: (c.calls + c.workers, c.calls), reverse=True)
    summary.total_cost_micro_usd = cost.total
    summary.cost_partial = cost.partial
    summary.cost_estimated = cost.estimated


def _load_manifest(session_name: str, forge_root: str | None):  # type: ignore[no-untyped-def]
    """Re-read the session manifest from disk (fresh hook-written state). None on failure."""
    try:
        from forge.session import SessionManager, SessionStore

        if forge_root:
            return SessionStore(forge_root, session_name).read()
        return SessionManager().get_session(session_name)
    except Exception as e:  # best-effort: a missing/locked manifest just drops the policy half
        logger.debug("usage summary: manifest load failed for %s: %s", session_name, e)
        return None


def _policy_activity(manifest, since: datetime | None) -> PolicyActivity | None:  # type: ignore[no-untyped-def]
    try:
        decisions = manifest.confirmed.policy.decisions
    except Exception:
        return None
    if not decisions:
        return None

    from forge.policy.store import MAX_DECISION_LOG

    # "At capacity", not "definitely truncated": the store caps the log to the last
    # MAX_DECISION_LOG on write, so at read time a naturally-exactly-full log is
    # indistinguishable from a truncated one -- treat at-capacity as "older may be evicted".
    activity = PolicyActivity(log_capped=len(decisions) >= MAX_DECISION_LOG)
    warnings: list[str] = []

    for entry in decisions:
        if not isinstance(entry, dict):
            continue
        if since is not None and not _entry_in_window(entry.get("evaluated_at"), since):
            continue

        # Count and collect warnings from the supervisor's OWN sub-decision only. The
        # entry-level `warnings` is the composite across every policy in that PreToolUse
        # evaluation (engine.py accumulates `all_warnings.extend(d.warnings)`), so a
        # deterministic policy (e.g. TDD permissive) warning would otherwise render as
        # phantom supervisor activity. Plan-check (cascade tier-1) sub-decisions are
        # counted separately: allow = short-circuit, needs_review = tier-1 requested
        # review (the resolver may still be skipped when a deterministic policy denied).
        for sub in entry.get("decisions") or ():
            if not isinstance(sub, dict):
                continue
            policy_id = sub.get("policy_id")
            decision = sub.get("decision")
            if policy_id == _PLAN_CHECK_POLICY_ID:
                if decision == "allow":
                    activity.plan_check_allow += 1
                elif decision == "needs_review":
                    activity.plan_check_needs_review += 1
                continue
            if policy_id != _SUPERVISOR_POLICY_ID:
                continue
            if decision == "allow":
                activity.supervisor_allow += 1
            elif decision == "warn":
                activity.supervisor_warn += 1
            elif decision == "deny":
                activity.supervisor_deny += 1
            sub_warnings = sub.get("warnings")
            if isinstance(sub_warnings, list):
                warnings.extend(str(w) for w in sub_warnings)

    activity.total_warnings = len(warnings)
    activity.recent_warnings = warnings[-_MAX_RECENT_WARNINGS:]
    # PolicyActivity is *semantic-tier* activity (supervisor + plan-check); if neither
    # took part in an in-window decision there is nothing to show (and a deterministic
    # policy warning must not surface a phantom "supervisor: 0 checks" section).
    return activity if activity.has_content else None


def _shadow_activity(forge_root: str | None, session_name: str, since: datetime | None) -> ShadowActivity | None:
    """Count shadow candidates from the session's shadow dir (best-effort).

    Reads ``.done`` terminal status and pending (``*.json``/``.processing``) records,
    windowing on each record's ``captured_at``. Best-effort: an unreadable record is
    skipped, a missing dir yields None (shadow sampling off or nothing captured).
    The cap bounds the dir to ``shadow_max_per_session`` records, so the per-call
    parse cost is negligible.
    """
    if not forge_root:
        return None
    try:
        from forge.session.artifacts import get_artifact_paths

        directory = get_artifact_paths(Path(forge_root), session_name).shadow_abs
    except Exception:
        return None
    if not directory.is_dir():
        return None

    from forge.policy.semantic.shadow_runner import (
        STATUS_AGREE,
        STATUS_DISAGREE,
        STATUS_INCONCLUSIVE,
    )

    activity = ShadowActivity()
    for entry in directory.iterdir():
        name = entry.name
        if name.endswith(".plan.md"):
            continue  # frozen-plan sidecar, not a record
        is_done = name.endswith(".done")
        is_pending = name.endswith(".json") or name.endswith(".processing")
        if not (is_done or is_pending):
            continue
        try:
            data = json.loads(entry.read_text())
        except Exception:
            continue
        if since is not None and not _entry_in_window(data.get("captured_at"), since):
            continue
        if not is_done:
            activity.pending += 1
            continue
        activity.checked += 1
        status = data.get("status")
        if status == STATUS_AGREE:
            activity.agree += 1
        elif status == STATUS_DISAGREE:
            activity.disagree += 1
        elif status == STATUS_INCONCLUSIVE:
            activity.inconclusive += 1
        else:  # STATUS_ERROR or any unrecognized terminal status
            activity.error += 1

    return activity if activity.has_content else None


def _entry_in_window(evaluated_at: object, since: datetime) -> bool:
    """Whether a decision entry is at/after ``since``. Undateable entries are kept."""
    if not isinstance(evaluated_at, str) or not evaluated_at:
        return True
    try:
        ts = datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    bound = since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)
    return ts >= bound


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)
