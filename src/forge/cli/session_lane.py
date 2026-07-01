"""``forge session lane`` -- per-consumer lane placement (session-owned intent).

A *consumer lane* binds a unit of Forge LLM-work -- the semantic supervisor,
memory writer, shadow curation, or team supervisor -- to a
``(runtime, backend, model)`` lane. The choice is recorded in the session
manifest's ``intent.consumer_lanes`` and frozen into ``confirmed`` at first
dispatch (epic consumer_lanes). Placement is session-scoped, so the canonical
surface lives here under ``forge session``; ``forge policy supervisor set
--runtime/--backend`` stays as the supervisor-specific convenience (same
``intent`` slot, same helpers -- no second storage path).
"""

from __future__ import annotations

import json
import sys

import click

from forge.cli.output import err_console, print_error, print_tip
from forge.cli.session import console
from forge.core.lanes import Consumer, LaneError
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import ForgeOpError, ResolveSessionResult, resolve_session
from forge.session.consumer_lanes import (
    clear_intent_lane,
    confirmed_lane,
    intent_lane,
    lane_record_for,
    lane_record_for_runtime,
    set_intent_lane,
)
from forge.session.models import LaneRecord, SessionState


class _LaneFrozen(Exception):
    """Signals (inside the store mutate) that a *different* lane is already frozen."""

    def __init__(self, record: LaneRecord) -> None:
        super().__init__()
        self.record = record


def _consumer_registry() -> dict[str, Consumer]:
    """Map consumer id -> ``Consumer`` constant.

    Lazy-imported: the four constants live in their feature modules (supervisor,
    memory writer, shadow curation, team supervisor), so importing them at module
    load would pull heavy policy/session modules into CLI startup and risk cycles.
    """
    from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER
    from forge.policy.team.handlers import TEAM_SUPERVISOR_CONSUMER
    from forge.session.memory_writer import MEMORY_WRITER_CONSUMER
    from forge.session.shadow_curation import SHADOW_CURATION_CONSUMER

    consumers = (SUPERVISOR_CONSUMER, MEMORY_WRITER_CONSUMER, SHADOW_CURATION_CONSUMER, TEAM_SUPERVISOR_CONSUMER)
    return {c.id: c for c in consumers}


def _resolve_consumer(raw: str) -> Consumer:
    """Resolve a ``--consumer`` value to a ``Consumer`` (hyphens accepted), or exit(1)."""
    registry = _consumer_registry()
    consumer = registry.get(raw.replace("-", "_"))
    if consumer is None:
        print_error(f"Unknown consumer {raw!r}.", console=err_console)
        print_tip("Choose one of: " + ", ".join(sorted(registry)), blank_before=False, console=err_console)
        sys.exit(1)
    return consumer


def _resolve_session_or_exit(session_name: str | None) -> ResolveSessionResult:
    """Resolve the target session as (store, state), or exit(1) with an actionable error."""
    try:
        ctx = ExecutionContext.from_cwd()
        return resolve_session(ctx=ctx, session_name=session_name)
    except ForgeOpError as e:
        print_error(str(e), console=err_console)
        sys.exit(1)


def _lane_str(record: LaneRecord) -> str:
    return f"runtime={record.runtime_id} backend={record.backend_id} model={record.model}"


def _reject_frozen(consumer: Consumer, frozen: LaneRecord) -> None:
    print_error(f"Lane for {consumer.id!r} is frozen for this session ({_lane_str(frozen)}).", console=err_console)
    print_tip(
        "The binding is immutable once a run freezes it; it resets next session.",
        blank_before=False,
        console=err_console,
    )
    sys.exit(1)


_SESSION_OPTION = click.option(
    "--session", "-s", "session_name", default=None, help="Target session (default: ambient $FORGE_SESSION)."
)


@click.group("lane")
def session_lane() -> None:
    """Bind a consumer's LLM-work to a (runtime, backend, model) lane for the session.

    Lanes are session-owned intent, frozen at first dispatch. The supervisor also
    accepts 'forge policy supervisor set --runtime/--backend' (same storage).

    \b
    Examples:
        forge session lane set --consumer memory_writer --backend claude-max
        forge session lane show
        forge session lane clear --consumer memory_writer
    """


@session_lane.command("set")
@click.option(
    "--consumer",
    "consumer_id",
    required=True,
    help="Consumer id (memory_writer, shadow_curation, team_supervisor, supervisor).",
)
@click.option("--runtime", "runtime", default=None, help="Lane runtime (e.g. claude_code).")
@click.option("--backend", "backend", default=None, help="Lane backend (e.g. claude-max for the Max subscription).")
@_SESSION_OPTION
def set_cmd(consumer_id: str, runtime: str | None, backend: str | None, session_name: str | None) -> None:
    """Record a consumer's requested lane in the session's ``intent``.

    Frozen into ``confirmed`` at the consumer's first dispatch; changing it to a
    different lane is rejected once frozen (immutable for the session).
    """
    consumer = _resolve_consumer(consumer_id)

    # A backend constraint selects the unique lane (claude-max vs the default
    # anthropic-direct, both on claude_code); runtime alone keeps the first match.
    try:
        if backend is not None:
            lane_record = lane_record_for(consumer, runtime=runtime, backend=backend)
        elif runtime is not None:
            lane_record = lane_record_for_runtime(consumer, runtime)
        else:
            print_error("Specify a lane with --runtime and/or --backend.", console=err_console)
            sys.exit(1)
    except LaneError as e:
        print_error(str(e), console=err_console)
        sys.exit(1)

    result = _resolve_session_or_exit(session_name)

    # Pre-check the freeze on the unlocked read (fast fail before the lock); the
    # authoritative guard is the under-lock re-check (a dispatch hook may freeze
    # between this read and the write -- the supervisor-set TOCTOU pattern).
    frozen = confirmed_lane(result.state, consumer)
    if frozen is not None and frozen != lane_record:
        _reject_frozen(consumer, frozen)

    def _apply(m: SessionState) -> None:
        current = confirmed_lane(m, consumer)
        if current is not None and current != lane_record:
            raise _LaneFrozen(current)
        set_intent_lane(m, consumer, lane_record)
        # T7: re-pinning the supervisor's lane is the "topped up, retry codex" signal -- clear
        # any sticky degrade so the next check dispatches the requested lane, not the default.
        # (Supervisor-only; other consumers have no degrade overlay.)
        from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER
        from forge.policy.supervisor_lane_degrade import clear_supervisor_degrade

        if consumer.id == SUPERVISOR_CONSUMER.id:
            clear_supervisor_degrade(m)

    try:
        result.store.update(timeout_s=5.0, mutate=_apply)
    except _LaneFrozen as exc:
        _reject_frozen(consumer, exc.record)

    console.print(f"Lane for [cyan]{consumer.id}[/cyan]: {_lane_str(lane_record)} (freezes on first dispatch).")


@session_lane.command("clear")
@click.option("--consumer", "consumer_id", required=True, help="Consumer id to clear.")
@_SESSION_OPTION
def clear_cmd(consumer_id: str, session_name: str | None) -> None:
    """Remove a consumer's requested (``intent``) lane.

    Leaves any already-frozen ``confirmed`` binding intact (immutable for the
    session) -- clearing before the freeze drops the request (back to default);
    clearing after surfaces as drift in ``show`` and resets next session.
    """
    consumer = _resolve_consumer(consumer_id)
    result = _resolve_session_or_exit(session_name)
    frozen = confirmed_lane(result.state, consumer)

    result.store.update(timeout_s=5.0, mutate=lambda m: clear_intent_lane(m, consumer))

    if frozen is not None:
        console.print(
            f"Cleared the requested lane for [cyan]{consumer.id}[/cyan]; "
            f"a frozen binding ({_lane_str(frozen)}) remains for this session."
        )
    else:
        console.print(f"Cleared the lane for [cyan]{consumer.id}[/cyan] (back to its default).")


@session_lane.command("show")
@_SESSION_OPTION
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit JSON.")
def show_cmd(session_name: str | None, as_json: bool) -> None:
    """Show each consumer's requested (``intent``) and frozen (``confirmed``) lane."""
    result = _resolve_session_or_exit(session_name)
    state = result.state
    registry = _consumer_registry()

    # T7: the supervisor's bound (frozen) codex lane can be degraded to the default this session --
    # flag it so `frozen: codex` is not read as "still dispatching codex". Supervisor-only overlay.
    from forge.policy.semantic.supervisor import SUPERVISOR_CONSUMER
    from forge.policy.supervisor_lane_degrade import is_supervisor_degraded

    sup_degraded = is_supervisor_degraded(state)

    json_rows: list[dict[str, object]] = []
    table_rows: list[tuple[str, LaneRecord | None, LaneRecord | None, bool, bool]] = []
    for cid in sorted(registry):
        consumer = registry[cid]
        requested = intent_lane(state, consumer)
        frozen = confirmed_lane(state, consumer)
        drift = requested is not None and frozen is not None and requested != frozen
        degraded = cid == SUPERVISOR_CONSUMER.id and sup_degraded
        json_rows.append(
            {
                "consumer": cid,
                "requested": _record_dict(requested),
                "frozen": _record_dict(frozen),
                "drift": drift,
                "degraded": degraded,
            }
        )
        table_rows.append((cid, requested, frozen, drift, degraded))

    if as_json:
        click.echo(json.dumps({"consumers": json_rows}, indent=2))
        return

    from rich.table import Table

    table = Table(show_header=True, header_style="bold")
    table.add_column("Consumer", style="cyan")
    table.add_column("Requested (intent)")
    table.add_column("Frozen (confirmed)")
    for cid, requested, frozen, drift, degraded in table_rows:
        frozen_cell = "[dim](not frozen)[/dim]" if frozen is None else _lane_cell(frozen)
        if drift:
            frozen_cell += " [yellow](drift)[/yellow]"
        if degraded:
            frozen_cell += " [yellow](degraded -> default)[/yellow]"
        table.add_row(cid, _lane_cell(requested), frozen_cell)
    console.print(table)


def _record_dict(record: LaneRecord | None) -> dict[str, str] | None:
    if record is None:
        return None
    return {"runtime": record.runtime_id, "backend": record.backend_id, "model": record.model}


def _lane_cell(record: LaneRecord | None) -> str:
    if record is None:
        return "[dim](default)[/dim]"
    return f"{record.runtime_id} / {record.backend_id} / {record.model}"
