"""Headless Codex reports one token total per launch and one cost per proxy create."""

import pytest

from forge.core.ops.usage_summary import build_session_activity_summary
from forge.core.run_id import mint_run_id
from forge.core.usage.emit import emit_codex_usage
from tests.fixtures.proxy_telemetry import write_request_cost_record

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    ("launch_charges", "expected_cost", "row_partial"),
    [
        (((20, None), (3,)), 23, True),
        (((0,), (0, 0)), 0, False),
        (((), (5,)), 5, True),
        (((None, None), ()), None, True),
    ],
)
def test_activity_joins_proxy_creates_to_each_codex_launch(launch_charges, expected_cost, row_partial):
    for charges in launch_charges:
        run = mint_run_id()
        emit_codex_usage(
            run_id=run,
            session="planner",
            command="codex-resume",
            status="success",
            proxy_id="responses",
            input_tokens=14,
            output_tokens=7,
            cached_tokens=2,
        )
        for index, cost in enumerate(charges):
            write_request_cost_record(
                proxy_id="responses",
                backend_id="openrouter",
                model="example",
                tier="sonnet",
                input_tokens=100,
                output_tokens=20,
                cached_tokens=10,
                cost_micros=cost,
                latency_ms=5,
                failed=False,
                request_id=f"req_{run}_{index}",
                forge_run_id=run,
                forge_root_run_id=run,
            )

    pane = build_session_activity_summary("planner", forge_root=None).downstream
    [row] = pane.rows
    assert row.attempts == pane.downstream_records == sum(len(charges) for charges in launch_charges)
    assert row.cost_partial is row_partial
    assert pane.cost_partial is (expected_cost is not None and row_partial)
    assert row.cost_micro_usd == pane.total_cost_micro_usd == expected_cost
    assert row.workers == 2
    assert row.input_tokens == pane.total_input_tokens == 28
    assert row.output_tokens == pane.total_output_tokens == 14
    assert row.cached_tokens == 4
