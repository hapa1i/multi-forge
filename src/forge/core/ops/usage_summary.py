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

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from forge.core.usage.ledger import UsageEvent, read_usage_events
from forge.core.usage.vocabulary import ROUTE_CLAUDE_INTERACTIVE, Confidence

logger = logging.getLogger(__name__)

_SUPERVISOR_POLICY_ID = "semantic.supervisor"
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
    workers: int = 0  # per-worker fan-out leaf events (claude -p); not part of `calls`
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_micro_usd: int | None = None  # sum where measured; None if no event carried cost


@dataclass
class PolicyActivity:
    """Decision-log-derived supervisor activity (capped at MAX_DECISION_LOG)."""

    supervisor_allow: int = 0
    supervisor_warn: int = 0
    supervisor_deny: int = 0
    total_warnings: int = 0
    recent_warnings: list[str] = field(default_factory=list)
    log_capped: bool = False

    @property
    def has_content(self) -> bool:
        return bool(self.supervisor_allow or self.supervisor_warn or self.supervisor_deny or self.total_warnings)


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
    subagents: int = 0
    # Explicit coverage flags (JSON-friendly) so a sparse summary reads honestly.
    cost_partial: bool = False  # some in-scope events lacked a measured cost
    # Some Forge LLM calls (e.g. the action tagger) never tag a session, so a per-session
    # view can undercount. The builder sets this True only when the session has activity
    # (an empty summary has nothing to be partial about); the default True is the safe
    # caveat for hand-built summaries.
    session_tagging_partial: bool = True

    @property
    def is_empty(self) -> bool:
        return not self.commands and (self.policy is None or not self.policy.has_content) and self.subagents == 0


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

    # Untagged emitters (e.g. the action tagger) never tag a session, so a per-session
    # view can undercount -- but only flag that once the session has activity to
    # contextualize it; claiming partial coverage of an empty summary is noise.
    summary.session_tagging_partial = not summary.is_empty
    return summary


def render_summary_line(summary: SessionActivitySummary) -> str | None:
    """Return a one-line session-end summary, or None when there is nothing to show.

    Pure formatter (no printing) so the launcher and tests share it.
    """
    parts: list[str] = []

    sup_errors = next((c.errors for c in summary.commands if c.command == "supervisor"), 0)
    pol = summary.policy
    if pol and pol.has_content:
        # `checks` (allow+warn+deny) is the capped decision-log count; `sup_errors` is the
        # uncapped ledger count -- different planes. A supervisor error fails open to an
        # `allow`, so normally errors <= checks; only decision-log eviction breaks that. So
        # when the log is at capacity render `checks` as a floor ("12+"), otherwise a capped
        # 100 checks beside 120 ledger errors reads as a contradiction instead of eviction.
        checks = pol.supervisor_allow + pol.supervisor_warn + pol.supervisor_deny
        checks_label = f"{checks}+" if pol.log_capped else str(checks)
        seg = f"supervisor: {checks_label} checks ({pol.supervisor_warn} warn, {pol.supervisor_deny} block"
        seg += f", {sup_errors} errors)" if sup_errors else ")"
        parts.append(seg)
    else:
        sup = next((c for c in summary.commands if c.command == "supervisor"), None)
        if sup is not None:
            seg = f"supervisor: {sup.calls} runs"
            if sup.errors:
                seg += f" ({sup.errors} errors)"
            parts.append(seg)

    if summary.total_cost_micro_usd is not None:
        # `~` flags the figure as approximate/best-effort (the aggregate mixes route-reported
        # cost with verb-snapshot estimates); `forge proxy costs show` is the authoritative view.
        parts.append(f"~${summary.total_cost_micro_usd / 1_000_000:.2f}")

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
    total = 0
    any_cost = False
    for event in events:
        micros = _forge_added_cost_micros(event)
        if micros is not None:
            total += micros
            any_cost = True
    return total if any_cost else None


# --- internals ---------------------------------------------------------------


def _forge_added_cost_micros(event: UsageEvent) -> int | None:
    """The event's cost in micro-USD if it counts as Forge-added spend, else None.

    Excludes the main interactive-harness channel (``route="claude_interactive"``) --
    the load-bearing no-blend rule: "Forge-added" is what Forge spends ON TOP of the
    session the human drives, never the session itself -- and any event whose cost
    figure is not trustworthy (only ``reported``/``gateway_calculated`` count).
    """
    if event.route == ROUTE_CLAUDE_INTERACTIVE:
        return None
    if event.confidence not in _FORGE_ADDED_COST_CONFIDENCES:
        return None
    return event.cost_micro_usd  # int | None -- None when the route reported no figure


def _aggregate_ledger(summary: SessionActivitySummary, session_name: str, since: datetime | None) -> None:
    try:
        events = read_usage_events(period_start=since, session=session_name)
    except Exception as e:  # best-effort: telemetry read must not break the summary
        logger.debug("usage summary: ledger read failed for %s: %s", session_name, e)
        return

    summary.total_events = len(events)
    by_command: dict[str, CommandUsage] = {}
    total_cost = 0
    any_cost = False
    missing_cost = False

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
        if event.input_tokens:
            cu.input_tokens += event.input_tokens
            summary.total_input_tokens += event.input_tokens
        if event.output_tokens:
            cu.output_tokens += event.output_tokens
            summary.total_output_tokens += event.output_tokens
        if event.cached_tokens:
            cu.cached_tokens += event.cached_tokens
        if event.cost_micro_usd is not None:
            cu.cost_micro_usd = (cu.cost_micro_usd or 0) + event.cost_micro_usd
            total_cost += event.cost_micro_usd
            any_cost = True
        else:
            missing_cost = True

    summary.commands = sorted(by_command.values(), key=lambda c: (c.calls + c.workers, c.calls), reverse=True)
    summary.total_cost_micro_usd = total_cost if any_cost else None
    summary.cost_partial = any_cost and missing_cost


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
        # phantom supervisor activity.
        for sub in entry.get("decisions") or ():
            if not isinstance(sub, dict) or sub.get("policy_id") != _SUPERVISOR_POLICY_ID:
                continue
            decision = sub.get("decision")
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
    # PolicyActivity is *supervisor* activity; if the supervisor took part in no in-window
    # decision there is nothing to show (and a non-supervisor warning must not surface a
    # phantom "supervisor: 0 checks" section). has_content is supervisor-only now.
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
