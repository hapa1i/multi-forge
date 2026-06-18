"""Tests for proxy cost reporting."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from forge.cli.proxy_costs import (
    _format_usd,
    _verb_cost_reported,
    costs_group,
)
from forge.core.paths import get_forge_home
from forge.core.usage.ledger import UsageEvent, log_usage_event


def _usage_event(run_id: str, command: str) -> None:
    log_usage_event(
        UsageEvent(
            run_id=run_id,
            root_run_id=run_id,
            runtime="claude_code",
            command=command,
            status="success",
        )
    )


class TestFormatUsd:
    def test_normal_dollar_amount(self) -> None:
        assert _format_usd(1_500_000) == "$1.50"

    def test_large_amount_with_comma(self) -> None:
        assert _format_usd(1_234_567_890) == "$1,234.57"

    def test_cents(self) -> None:
        assert _format_usd(50_000) == "$0.05"

    def test_sub_cent(self) -> None:
        assert _format_usd(500) == "$0.0005"

    def test_sub_microdollar(self) -> None:
        assert _format_usd(3) == "$0.000003"

    def test_zero(self) -> None:
        assert _format_usd(0) == "$0.00"


def test_costs_json_filters_verb_records_by_proxy(monkeypatch) -> None:
    _usage_event("run_panel", "panel")
    _usage_event("run_supervisor", "supervisor")
    request_records = [
        {
            "proxy_id": "openrouter",
            "model": "anthropic/claude-sonnet-4.6",
            "cost_micros": 80_000,
            "input_tokens": 1_000,
            "output_tokens": 500,
            "forge_run_id": "run_panel",
        },
        {
            "proxy_id": "openrouter",
            "model": "anthropic/claude-sonnet-4.6",
            "cost_micros": 20_000,
            "input_tokens": 1_000,
            "output_tokens": 500,
            "forge_run_id": None,
        },
        {
            "proxy_id": "litellm-gemini",
            "model": "gemini/gemini-3.1-pro-preview",
            "cost_micros": 40_000,
            "input_tokens": 800,
            "output_tokens": 200,
            "forge_run_id": "run_supervisor",
        },
    ]

    monkeypatch.setattr("forge.proxy.cost_logger.read_cost_logs", lambda *args, **kwargs: request_records)

    result = CliRunner().invoke(costs_group, ["show", "openrouter", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["total_cost_micros"] == 100_000
    assert data["interactive_cost_micros"] == 20_000
    assert set(data["by_verb"]) == {"panel"}
    assert data["by_verb"]["panel"]["cost_micros"] == 80_000
    assert data["by_verb"]["panel"]["request_count"] == 1
    assert set(data["by_model"]) == {"anthropic/claude-sonnet-4.6"}


def test_costs_json_mixed_reported_and_unavailable(monkeypatch) -> None:
    """Legacy catalog int + new reported + new unavailable(null) aggregate cleanly.

    The present-but-null cost_micros must NOT be summed as 0 (and `sum` must not
    crash on it): it's excluded from the total and counted as unavailable.
    """
    request_records = [
        # Legacy catalog record (pre-rename: int cost, no provenance fields).
        {"proxy_id": "p", "model": "m-legacy", "cost_micros": 30_000, "input_tokens": 100, "output_tokens": 50},
        # New reported record.
        {
            "proxy_id": "p",
            "model": "m-reported",
            "cost_micros": 70_000,
            "reporter": "openrouter",
            "confidence": "reported",
            "input_tokens": 200,
            "output_tokens": 80,
        },
        # New unavailable record — cost is null.
        {
            "proxy_id": "p",
            "model": "m-unavail",
            "cost_micros": None,
            "reporter": None,
            "confidence": "unavailable",
            "input_tokens": 300,
            "output_tokens": 120,
        },
    ]
    monkeypatch.setattr("forge.proxy.cost_logger.read_cost_logs", lambda *a, **k: request_records)
    monkeypatch.setattr("forge.core.reactive.cost_tracking.read_verb_logs", lambda *a, **k: [])

    result = CliRunner().invoke(costs_group, ["show", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    # Total sums REPORTED costs only (30k + 70k); the null is excluded, not 0.
    assert data["total_cost_micros"] == 100_000
    assert data["reported_requests"] == 2
    assert data["unavailable_requests"] == 1
    assert "estimated" not in data  # clean break: provenance replaces the flag
    assert data["by_model"]["m-reported"]["reported"] is True
    assert data["by_model"]["m-unavail"]["reported"] is False


def test_costs_human_output_renders_unavailable(monkeypatch) -> None:
    """A cost-unavailable request renders 'unavailable', not $0.00, without crashing."""
    request_records = [
        {"proxy_id": "p", "model": "m-unavail", "cost_micros": None, "input_tokens": 10, "output_tokens": 5},
    ]
    monkeypatch.setattr("forge.proxy.cost_logger.read_cost_logs", lambda *a, **k: request_records)
    monkeypatch.setattr("forge.core.reactive.cost_tracking.read_verb_logs", lambda *a, **k: [])

    by_model = CliRunner().invoke(costs_group, ["show", "--by-model"])
    assert by_model.exit_code == 0, by_model.output
    assert "unavailable" in by_model.output

    by_verb = CliRunner().invoke(costs_group, ["show", "--by-verb"])
    assert by_verb.exit_code == 0, by_verb.output
    assert "cost unavailable" in by_verb.output


class TestVerbCostReported:
    """`_verb_cost_reported` reads the evidence flag, not the (always-int) total."""

    def test_evidence_flag_true_with_zero_total_is_reported(self) -> None:
        # Reported $0 (all-free models): the flag, not the total, is the signal.
        assert _verb_cost_reported({"cost_measured": True, "total_cost_micros": 0}) is True

    def test_evidence_flag_false_with_zero_total_is_unavailable(self) -> None:
        # The user's reproduction: passthrough verb, tokens but no reported cost.
        assert _verb_cost_reported({"cost_measured": False, "total_cost_micros": 0}) is False

    def test_evidence_flag_authoritative_over_positive_total(self) -> None:
        # A present flag always wins; a stray positive total cannot override it.
        assert _verb_cost_reported({"cost_measured": False, "total_cost_micros": 50_000}) is False

    def test_legacy_record_without_flag_is_unavailable(self) -> None:
        # Pre cost-evidence record (no flag): its total_cost_micros was a now-deleted
        # catalog ESTIMATE, so it reads as unavailable -- never resurrected as
        # route-reported cost (the card's "Forge is not a cost oracle" rule).
        assert _verb_cost_reported({"total_cost_micros": 50_000}) is False

    def test_legacy_record_zero_total_is_unavailable(self) -> None:
        # No flag -> unavailable regardless of the (meaningless) total.
        assert _verb_cost_reported({"total_cost_micros": 0}) is False


def test_costs_json_verb_evidence_flag_gates_reported(monkeypatch) -> None:
    """A passthrough verb (cost_measured=False, total 0) is NOT reported as $0.

    Reproduces the reported regression: numeric total_cost_micros (including 0)
    was treated as reported. The evidence flag must gate `reported`.
    """
    _usage_event("run_passthrough", "passthrough")
    _usage_event("run_freebie", "freebie")
    _usage_event("run_panel", "panel")
    request_records = [
        {"model": "m", "cost_micros": None, "forge_run_id": "run_passthrough"},
        {"model": "m", "cost_micros": 0, "forge_run_id": "run_freebie"},
        {"model": "m", "cost_micros": 15_000, "forge_run_id": "run_panel"},
    ]
    monkeypatch.setattr("forge.proxy.cost_logger.read_cost_logs", lambda *a, **k: request_records)

    result = CliRunner().invoke(costs_group, ["show", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["by_verb"]["passthrough"]["reported"] is False
    assert data["by_verb"]["passthrough"]["cost_micros"] == 0
    assert data["by_verb"]["freebie"]["reported"] is True
    assert data["by_verb"]["panel"]["reported"] is True
    assert data["by_verb"]["panel"]["cost_micros"] == 15_000


def test_costs_human_verb_evidence_flag_renders_unavailable(monkeypatch) -> None:
    """Human view shows 'unavailable' for a cost_measured=False verb, not $0.00."""
    _usage_event("run_passthrough", "passthrough")
    request_records = [{"model": "m", "cost_micros": None, "forge_run_id": "run_passthrough"}]
    monkeypatch.setattr("forge.proxy.cost_logger.read_cost_logs", lambda *a, **k: request_records)

    result = CliRunner().invoke(costs_group, ["show", "--by-verb"])

    assert result.exit_code == 0, result.output
    # The verb row reads 'unavailable'; it must not be rendered as a measured $0.00.
    assert "unavailable" in result.output


class TestCostsReset:
    """`forge proxy costs reset` wipes the three spend/usage planes plus the derived
    status-line cost cache (the autouse `isolate_forge_home` fixture gives each test its
    own FORGE_HOME)."""

    _PLANES = (("costs", "requests"), ("costs", "verbs"), ("usage", "events"))

    def _seed(self) -> list[Path]:
        home = get_forge_home()
        files = []
        for parts in self._PLANES:
            d = home.joinpath(*parts)
            d.mkdir(parents=True, exist_ok=True)
            shard = d / "2026-06_1.jsonl"
            shard.write_text('{"x": 1}\n')
            files.append(shard)
        return files

    def test_dry_run_lists_but_deletes_nothing(self) -> None:
        files = self._seed()
        result = CliRunner().invoke(costs_group, ["reset", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "dry-run" in result.output
        assert all(f.exists() for f in files)

    def test_yes_wipes_all_three_planes(self) -> None:
        files = self._seed()
        home = get_forge_home()
        result = CliRunner().invoke(costs_group, ["reset", "--yes"])
        assert result.exit_code == 0, result.output
        assert not any(f.exists() for f in files)
        for parts in self._PLANES:
            assert list(home.joinpath(*parts).glob("*.jsonl")) == []

    def test_confirmation_abort_keeps_files(self) -> None:
        files = self._seed()
        result = CliRunner().invoke(costs_group, ["reset"], input="n\n")
        assert result.exit_code != 0  # Click abort on declined confirmation
        assert all(f.exists() for f in files)

    def test_empty_is_noop(self) -> None:
        result = CliRunner().invoke(costs_group, ["reset", "--yes"])
        assert result.exit_code == 0, result.output
        assert "No cost or usage telemetry" in result.output

    def test_leaves_audit_plane_untouched(self) -> None:
        self._seed()
        home = get_forge_home()
        audit_shard = home / "audit" / "requests" / "2026-06_1.jsonl"
        audit_shard.parent.mkdir(parents=True, exist_ok=True)
        audit_shard.write_text('{"x": 1}\n')
        result = CliRunner().invoke(costs_group, ["reset", "--yes"])
        assert result.exit_code == 0, result.output
        assert audit_shard.exists()  # audit is a separate plane, intentionally NOT reset

    def test_clears_fcost_cache_but_not_cache_hit_entries(self) -> None:
        # The derived `forge +$Y` cache (fcost-*.json) would otherwise replay a stale
        # cost within its TTL after the ledger is wiped, so reset must clear it -- but the
        # unrelated transcript cache-hit entry ({digest}.json) is not cost state.
        cache = get_forge_home() / "cache" / "statusline"
        cache.mkdir(parents=True, exist_ok=True)
        fcost = cache / "fcost-deadbeef.json"
        cache_hit = cache / "deadbeef.json"
        fcost.write_text('{"version": 1, "computed_at": 0, "cost_micro_usd": 9999}\n')
        cache_hit.write_text('{"version": 1, "cache_hit_rate": 0.5}\n')
        result = CliRunner().invoke(costs_group, ["reset", "--yes"])
        assert result.exit_code == 0, result.output
        assert not fcost.exists()  # stale derived cost segment cleared
        assert cache_hit.exists()  # transcript cache-hit rate is not cost telemetry

    def test_clears_fhealth_cache_but_not_cache_hit_entries(self) -> None:
        # The derived supervisor-health cache (fhealth-*.json) would otherwise replay a
        # stale SUP!N marker within its TTL after the ledger is wiped, so reset clears it.
        # The unrelated transcript cache-hit entry ({digest}.json) is not telemetry state.
        cache = get_forge_home() / "cache" / "statusline"
        cache.mkdir(parents=True, exist_ok=True)
        fhealth = cache / "fhealth-deadbeef.json"
        cache_hit = cache / "deadbeef.json"
        fhealth.write_text(
            '{"version": 1, "computed_at": 0, "recent_failures": 3, "last_kind": "timeout", "last_seen_at": "ts"}\n'
        )
        cache_hit.write_text('{"version": 1, "cache_hit_rate": 0.5}\n')
        result = CliRunner().invoke(costs_group, ["reset", "--yes"])
        assert result.exit_code == 0, result.output
        assert not fhealth.exists()  # stale derived health marker cleared
        assert cache_hit.exists()  # transcript cache-hit rate is not telemetry

    def test_dry_run_lists_supervisor_health_cache(self) -> None:
        cache = get_forge_home() / "cache" / "statusline"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "fhealth-deadbeef.json").write_text("{}\n")
        result = CliRunner().invoke(costs_group, ["reset", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "supervisor-health" in result.output  # previewed as its own target
        assert (cache / "fhealth-deadbeef.json").exists()  # dry-run deletes nothing
