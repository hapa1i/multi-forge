"""Unmeasured Codex launches used to disappear into the activity row's token totals."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from forge.cli import activity
from forge.cli.main import main
from forge.core.ops.usage_summary import build_session_activity_summary
from forge.core.usage.emit import emit_codex_usage

pytestmark = pytest.mark.regression


def test_activity_counts_successful_and_failed_launches_with_unknown_tokens(monkeypatch):
    monkeypatch.setattr(activity, "resolve_session_identifier", lambda name: (name, None))
    monkeypatch.setattr(activity.console, "_width", 200)
    for run, status, tokens in [
        ("run_measured", "success", (18, 4, 2)),
        ("run_unverified", "success", (None, None, None)),
        ("run_failed", "error", (None, None, None)),
    ]:
        tokens_in, cached, tokens_out = tokens
        emit_codex_usage(
            command="codex-resume",
            session="test",
            run_id=run,
            status=status,
            input_tokens=tokens_in,
            cached_tokens=cached,
            output_tokens=tokens_out,
        )
    emit_codex_usage(
        command="codex-bridge",
        session="test",
        run_id="run_zero",
        status="success",
        input_tokens=0,
        cached_tokens=0,
        output_tokens=0,
    )
    emit_codex_usage(command="panel", session="test", run_id="run_proxied", status="success", proxy_id="proxy")

    args = ["telemetry", "activity", "test", "--period", "all"]
    runner = CliRunner()
    machine = runner.invoke(main, [*args, "--json"])
    assert machine.exit_code == 0
    rows = {row["command"]: row for row in json.loads(machine.output)["downstream"]["rows"]}
    resume = rows["codex-resume"]
    assert (resume["attempts"], resume["unknown_token_launches"]) == (3, 2)
    assert (resume["input_tokens"], resume["cached_tokens"], resume["output_tokens"]) == (18, 4, 2)
    assert rows["codex-bridge"]["unknown_token_launches"] == 0
    assert rows["panel"]["unknown_token_launches"] is None

    human = runner.invoke(main, args)
    assert human.exit_code == 0
    assert "18/2*" in human.output
    assert "0/0" in human.output
    assert "Token totals omit unknown counts from 2 codex-resume launches." in human.output


def test_partially_reported_launch_preserves_available_counts():
    emit_codex_usage(
        command="codex-resume",
        session="test",
        run_id="run_partial",
        status="success",
        input_tokens=19,
        output_tokens=2,
    )

    (row,) = build_session_activity_summary("test", forge_root=None).downstream.rows
    assert row.unknown_token_launches == 1
    assert (row.input_tokens, row.output_tokens) == (19, 2)


@pytest.mark.parametrize(
    ("cached", "proxy", "cell", "unknown"),
    [
        (0, None, "0/0*", 1),
        (None, None, "0/0*", 2),
        (0, "proxy", "-*", 1),
    ],
)
def test_zero_subtotal_alongside_unknown_launch(monkeypatch, cached, proxy, cell, unknown):
    monkeypatch.setattr(activity, "resolve_session_identifier", lambda name: (name, None))
    monkeypatch.setattr(activity.console, "_width", 200)
    emit_codex_usage(command="codex-resume", session="test", run_id="run_unknown", status="success")
    emit_codex_usage(
        command="codex-resume",
        session="test",
        run_id="run_zero",
        status="success",
        input_tokens=0,
        output_tokens=0,
        cached_tokens=cached,
        proxy_id=proxy,
    )

    human = CliRunner().invoke(main, ["telemetry", "activity", "test", "--period", "all"])
    assert human.exit_code == 0
    model_row = next(line for line in human.output.splitlines() if "codex-resume" in line)
    assert cell in model_row.split()
    assert f"unknown counts from {unknown} codex-resume" in human.output
