"""Wave 5 closeout guards for review claims refuted by current behavior."""

from __future__ import annotations

import json
from pathlib import Path

import dacite
import pytest
from click.testing import CliRunner

from forge.cli.hooks.commands import hooks
from forge.core.ops import usage_summary
from forge.core.ops.usage_summary import CommandUsage, SessionActivitySummary
from forge.core.run_id import derive_provider_session_id
from forge.core.telemetry.downstream import DownstreamReadResult, DownstreamRecord
from forge.session.effective import compute_effective_intent
from forge.session.models import VerificationConfig, create_session_state
from forge.session.store import SessionStore


def test_d033_cancel_verification_survives_malformed_unrelated_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The escape hatch falls back to raw intent when effective intent is malformed."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORGE_SESSION", "test-session")
    (tmp_path / ".claude").mkdir()

    manifest = create_session_state("test-session")
    manifest.intent.verification = VerificationConfig(promise="done", bypass=False)
    manifest.overrides = {"memory": {"tags": "not-a-list"}}
    with pytest.raises(dacite.DaciteError):
        compute_effective_intent(manifest, strict=False)

    store = SessionStore(str(tmp_path), "test-session")
    store.write(manifest)

    result = CliRunner().invoke(
        hooks,
        ["user-prompt-submit"],
        input=json.dumps({"prompt": "%cancel-verification"}),
    )

    assert result.exit_code == 0
    assert result.exception is None
    assert "bypass enabled" in json.loads(result.output)["reason"].lower()
    assert store.read().overrides["verification"]["bypass"] is True


def test_o020_model_pane_keeps_non_proxy_event_cost_with_downstream_rows(monkeypatch) -> None:
    """Adding downstream evidence does not replace event-backed command totals."""
    summary = SessionActivitySummary(
        session="planner",
        commands=[
            CommandUsage(command="direct-supervisor", calls=1, cost_micro_usd=700),
            CommandUsage(command="proxied-panel", calls=1, cost_micro_usd=300),
        ],
        total_cost_micro_usd=1_000,
        cost_estimated=False,
    )

    monkeypatch.setattr(usage_summary, "read_upstream_outcomes", lambda **_kwargs: [])
    monkeypatch.setattr(
        usage_summary,
        "read_downstream_records_with_stats",
        lambda **_kwargs: DownstreamReadResult(
            records=[
                DownstreamRecord(
                    kind="attempt",
                    downstream_event_id="ds_proxy_only",
                    provider_command="proxy-only",
                    provider_session_id=derive_provider_session_id("planner", root_run_id="", role=None),
                    cost_micros=200,
                )
            ]
        ),
    )

    usage_summary._build_activity_panes(summary, "planner", since=None, events=[])

    assert {row.command for row in summary.downstream.rows} == {
        "direct-supervisor",
        "proxied-panel",
        "proxy-only",
    }
    assert summary.downstream.total_cost_micro_usd == 1_200
    assert summary.total_cost_micro_usd == 1_200
