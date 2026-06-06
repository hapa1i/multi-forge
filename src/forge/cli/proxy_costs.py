"""CLI command: forge proxy costs.

Shows cost breakdowns from persistent JSONL cost logs. Reads both
per-request logs (model/tier analysis) and per-verb logs (functional
attribution). "Interactive" cost is computed as the residual.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import click
from rich.console import Console
from rich.table import Table

console = Console(stderr=True)


def _local_period_bounds(period: str) -> tuple[datetime, datetime]:
    """Compute UTC start/end for a named period using local timezone."""
    now_local = datetime.now().astimezone()
    now_utc = datetime.now(timezone.utc)

    if period == "today":
        local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start = local_midnight.astimezone(timezone.utc)
        return start, now_utc
    elif period == "week":
        local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = local_midnight - timedelta(days=local_midnight.weekday())
        start = week_start.astimezone(timezone.utc)
        return start, now_utc
    elif period == "month":
        local_month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start = local_month_start.astimezone(timezone.utc)
        return start, now_utc
    else:
        return datetime.min.replace(tzinfo=timezone.utc), now_utc


def _format_usd(micros: int) -> str:
    usd = micros / 1_000_000
    if usd >= 1.0:
        return f"${usd:,.2f}"
    if usd >= 0.01:
        return f"${usd:.2f}"
    if usd >= 0.0001:
        return f"${usd:.4f}"
    if usd > 0:
        return f"${usd:.6f}"
    return "$0.00"


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _reported_micros(record: dict, key: str = "cost_micros") -> int | None:
    """Reported cost in micros, or ``None`` when unavailable.

    ``record.get(key, 0)`` is unsafe here: a present-but-null value (cost
    unavailable) returns ``None``, which must never be summed as ``0`` (and would
    crash ``sum``). An ``int`` (including a reported ``0`` — genuinely free) is
    reported; ``None`` / missing / non-int is unavailable. ``bool`` is excluded
    because ``isinstance(True, int)`` is True.
    """
    val = record.get(key)
    if isinstance(val, bool):
        return None
    return val if isinstance(val, int) else None


def _verb_cost_reported(record: dict) -> bool:
    """Whether a verb invocation has reported-cost evidence.

    ``cost_measured`` is the sole evidence: true only when the measurement window had
    a route-reported-cost request. A verb record's ``total_cost_micros`` is a plain
    int (0 for a passthrough window), so presence-of-number is NOT evidence -- the
    unknown-as-zero trap. A legacy record (pre cost-evidence) lacks the flag; its
    ``total_cost_micros`` was a now-deleted local-catalog ESTIMATE, so it reads as
    unavailable rather than resurrecting that estimate as route-reported cost.
    """
    return bool(record.get("cost_measured", False))


@click.command("costs")
@click.argument("proxy_id", required=False, default=None)
@click.option(
    "--period",
    type=click.Choice(["today", "week", "month", "all"]),
    default="today",
    help="Time period to show (default: today)",
)
@click.option("--by-model", is_flag=True, help="Breakdown by model")
@click.option("--by-verb", is_flag=True, help="Breakdown by verb (default view)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def costs_cmd(
    proxy_id: str | None,
    period: str,
    by_model: bool,
    by_verb: bool,
    as_json: bool,
) -> None:
    """Show cost summary from proxy cost logs.

    \b
    Examples:
        forge proxy costs                    # Today's costs, by verb
        forge proxy costs --by-model         # Today's costs, by model
        forge proxy costs --period week      # This week
        forge proxy costs --period all       # All time
        forge proxy costs openrouter         # Filter by proxy

    \b
    Tip: pair with 'forge proxy set <id> costs.caps.per_month=<amount>' to keep
    metered provider usage within a monthly budget.
    """
    from forge.core.reactive.cost_tracking import read_verb_logs
    from forge.proxy.cost_logger import read_cost_logs

    start, end = _local_period_bounds(period)
    if period == "all":
        request_records = read_cost_logs()
        verb_records = read_verb_logs()
    else:
        request_records = read_cost_logs(period_start=start, period_end=end)
        verb_records = read_verb_logs(period_start=start, period_end=end)

    if proxy_id:
        request_records = [r for r in request_records if r.get("proxy_id") == proxy_id]
        verb_records = _scope_verb_records_to_proxy(verb_records, _lookup_proxy_base_url(proxy_id))

    if as_json:
        _output_json(request_records, verb_records, period, proxy_id)
        return

    if by_model:
        _display_by_model(request_records, period, proxy_id)
    else:
        _display_by_verb(request_records, verb_records, period, proxy_id)


def _lookup_proxy_base_url(proxy_id: str) -> str | None:
    """Resolve a proxy id for filtering verb cost records."""
    try:
        from forge.core.reactive.proxy import lookup_proxy_base_url

        return lookup_proxy_base_url(proxy_id)
    except Exception:
        return None


def _normalize_base_url(base_url: str | None) -> str | None:
    if not base_url:
        return None
    normalized = base_url.strip()
    if not normalized:
        return None
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized.rstrip("/")


def _sum_proxy_field(proxies: list[dict], field: str) -> int:
    return sum(int(p.get(field, 0) or 0) for p in proxies)


def _scope_verb_records_to_proxy(verb_records: list[dict], proxy_base_url: str | None) -> list[dict]:
    """Keep only the per-proxy deltas matching the requested proxy base URL."""
    target = _normalize_base_url(proxy_base_url)
    if not target:
        return []

    scoped: list[dict] = []
    for record in verb_records:
        per_proxy = record.get("per_proxy", [])
        if not isinstance(per_proxy, list):
            continue

        matching = [
            proxy_delta
            for proxy_delta in per_proxy
            if isinstance(proxy_delta, dict) and _normalize_base_url(proxy_delta.get("base_url")) == target
        ]
        if not matching:
            continue

        scoped_record = dict(record)
        scoped_record["per_proxy"] = matching
        scoped_record["total_cost_micros"] = _sum_proxy_field(matching, "cost_micros")
        scoped_record["input_tokens"] = _sum_proxy_field(matching, "input_tokens")
        scoped_record["output_tokens"] = _sum_proxy_field(matching, "output_tokens")
        scoped_record["cached_tokens"] = _sum_proxy_field(matching, "cached_tokens")
        scoped_record["request_count"] = _sum_proxy_field(matching, "request_count")
        # Re-derive cost-evidence for the scoped subset: the unscoped record's
        # cost_measured covers all proxies, but a single-proxy view may have no
        # reported-cost request. Trust the per-proxy counter when present; a legacy
        # delta lacks it, so it reads as cost-unavailable (no resurrected estimate).
        if any("reported_request_count" in p for p in matching):
            scoped_record["cost_measured"] = _sum_proxy_field(matching, "reported_request_count") > 0
        else:
            scoped_record["cost_measured"] = False
        scoped.append(scoped_record)

    return scoped


def _request_cost_totals(request_records: list[dict]) -> tuple[int, int]:
    """Return (summed reported cost micros, count of cost-unavailable requests).

    Reported cost only -- a null/unavailable cost is counted in the second value,
    never summed as $0 into the first (the "not a cost oracle" rule). Shared by the
    table and JSON surfaces so the two cannot drift.
    """
    total_cost = sum(c for r in request_records if (c := _reported_micros(r)) is not None)
    unavailable_requests = sum(1 for r in request_records if _reported_micros(r) is None)
    return total_cost, unavailable_requests


def _aggregate_by_verb(verb_records: list[dict]) -> dict[str, dict]:
    """Fold verb cost records into per-verb totals (cost-evidence aware).

    ``reported`` flips True only when a record carries measured cost
    (:func:`_verb_cost_reported`); an unmeasured window contributes invocations and
    request counts but never a fabricated $0. Shared by table + JSON surfaces.
    """
    verb_costs: dict[str, dict] = {}
    for v in verb_records:
        verb = v.get("verb", "unknown")
        if verb not in verb_costs:
            verb_costs[verb] = {"cost_micros": 0, "reported": False, "request_count": 0, "invocations": 0}
        if _verb_cost_reported(v):
            verb_costs[verb]["cost_micros"] += _reported_micros(v, "total_cost_micros") or 0
            verb_costs[verb]["reported"] = True
        verb_costs[verb]["request_count"] += v.get("request_count", 0)
        verb_costs[verb]["invocations"] += 1
    return verb_costs


def _aggregate_by_model(request_records: list[dict]) -> dict[str, dict]:
    """Fold request records into per-model totals (cost-evidence aware).

    ``reported`` flips True only for a request whose cost the route reported; a
    null-cost request still contributes tokens and a request count. Shared by
    table + JSON surfaces so they cannot drift.
    """
    model_costs: dict[str, dict] = {}
    for r in request_records:
        model = r.get("model", "unknown")
        if model not in model_costs:
            model_costs[model] = {
                "cost_micros": 0,
                "reported": False,
                "input_tokens": 0,
                "output_tokens": 0,
                "requests": 0,
            }
        rc = _reported_micros(r)
        if rc is not None:
            model_costs[model]["cost_micros"] += rc
            model_costs[model]["reported"] = True
        model_costs[model]["input_tokens"] += r.get("input_tokens", 0)
        model_costs[model]["output_tokens"] += r.get("output_tokens", 0)
        model_costs[model]["requests"] += 1
    return model_costs


def _display_by_verb(
    request_records: list[dict],
    verb_records: list[dict],
    period: str,
    proxy_id: str | None,
) -> None:
    total_cost, unavailable_requests = _request_cost_totals(request_records)
    total_requests = len(request_records)

    verb_costs = _aggregate_by_verb(verb_records)
    verb_total = sum(v["cost_micros"] for v in verb_costs.values())
    interactive_cost = max(0, total_cost - verb_total)

    if total_cost == 0 and unavailable_requests == 0 and not verb_costs:
        scope = f" ({proxy_id})" if proxy_id else ""
        console.print(f"[dim]No cost data for {period}{scope}.[/dim]")
        return

    scope = f" ({proxy_id})" if proxy_id else ""
    console.print(f"\n[bold]Cost Summary ({period}{scope}):[/bold]")

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Source", style="cyan")
    table.add_column("Cost", justify="right")
    table.add_column("Detail", style="dim")
    table.add_column("", style="dim")

    total_detail = f"{total_requests} requests"
    if unavailable_requests:
        total_detail += f" ({unavailable_requests} cost unavailable)"
    table.add_row("Total", _format_usd(total_cost), total_detail, "")
    table.add_row(
        "Interactive",
        _format_usd(interactive_cost),
        "unattributed",
        "~",
    )

    for verb in sorted(verb_costs):
        info = verb_costs[verb]
        detail = f"{info['invocations']} run{'s' if info['invocations'] != 1 else ''}"
        if info["request_count"]:
            detail += f", {info['request_count']} reqs"
        cost_cell = _format_usd(info["cost_micros"]) if info["reported"] else "unavailable"
        table.add_row(verb, cost_cell, detail, "~" if info["reported"] else "")

    console.print(table)
    console.print()


def _display_by_model(
    request_records: list[dict],
    period: str,
    proxy_id: str | None,
) -> None:
    model_costs = _aggregate_by_model(request_records)

    if not model_costs:
        scope = f" ({proxy_id})" if proxy_id else ""
        console.print(f"[dim]No cost data for {period}{scope}.[/dim]")
        return

    scope = f" ({proxy_id})" if proxy_id else ""
    console.print(f"\n[bold]By Model ({period}{scope}):[/bold]")

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Model", style="cyan")
    table.add_column("Cost", justify="right")
    table.add_column("Tokens", style="dim")

    for model in sorted(model_costs, key=lambda m: model_costs[m]["cost_micros"], reverse=True):
        info = model_costs[model]
        tokens = f"{_format_tokens(info['input_tokens'])} in, {_format_tokens(info['output_tokens'])} out"
        cost_cell = _format_usd(info["cost_micros"]) if info["reported"] else "unavailable"
        table.add_row(model, cost_cell, tokens)

    console.print(table)
    console.print()


def _output_json(
    request_records: list[dict],
    verb_records: list[dict],
    period: str,
    proxy_id: str | None,
) -> None:
    total_cost, unavailable_requests = _request_cost_totals(request_records)

    verb_summary = _aggregate_by_verb(verb_records)
    model_summary = _aggregate_by_model(request_records)

    verb_total = sum(v["cost_micros"] for v in verb_summary.values())

    output = {
        "period": period,
        "proxy_id": proxy_id,
        # total_cost_* sums reported cost only; unavailable requests are excluded
        # (never summed as $0). reported/unavailable counts give cost-evidence scope.
        "total_cost_micros": total_cost,
        "total_cost_usd": round(total_cost / 1_000_000, 6),
        "total_requests": len(request_records),
        "reported_requests": len(request_records) - unavailable_requests,
        "unavailable_requests": unavailable_requests,
        "interactive_cost_micros": max(0, total_cost - verb_total),
        "by_verb": verb_summary,
        "by_model": model_summary,
    }
    click.echo(json.dumps(output, indent=2))
