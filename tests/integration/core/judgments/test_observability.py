"""Exercise the real ledgers and CLI readers with an offline Decisions transport."""

import asyncio
import json
import os
import time

import httpx
import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.judgments import NoulQuestion, OpenRouterJudgmentClient
from forge.core.reactive.env import derive_child_run_identity
from forge.core.telemetry.downstream import (
    read_downstream_records,
    write_downstream_record,
)
from forge.core.usage.ledger import read_usage_events
from forge.session.index import IndexStore
from tests.fixtures.session_state import publish_session_from_fields

pytestmark = pytest.mark.integration


def test_evaluations_count_separately_and_retries_retain_ancestry(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    monkeypatch.setenv("FORGE_RUN_ID", "run_session")
    monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_root")
    monkeypatch.delenv("FORGE_PARENT_RUN_ID", raising=False)
    before = dict(os.environ)
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) % 2:
            return httpx.Response(429, json={"error": {"code": 429}}, headers={"retry-after": "0"})
        return httpx.Response(
            200,
            json={
                "model": "typesafe/jev-1.13-20260917",
                "answers": {"q": {"type": "noul", "noul": 0.9}},
                "usage": {"input_tokens": 30, "output_tokens": 2, "cost": 0.00000126},
            },
        )

    identities = [derive_child_run_identity(), derive_child_run_identity()]
    client = OpenRouterJudgmentClient(transport=httpx.MockTransport(handler), command="jev-rule-pack")
    for identity in identities:
        result = asyncio.run(
            client.judge(
                "Synthetic",
                {"q": NoulQuestion(instructions="Synthetic?", criteria={"true": "Yes", "false": "No"})},
                deadline=time.monotonic() + 3,
                run_identity=identity,
            )
        )
        assert len(result.attempts) == 2
    assert dict(os.environ) == before
    records = read_downstream_records()
    assert len(records) == len({record.request_id for record in records}) == 4
    assert {record.forge_run_id for record in records} == {identity.run_id for identity in identities}
    assert {record.forge_root_run_id for record in records} == {"run_root"}
    events = read_usage_events()
    assert {event.run_id for event in events} == {identity.run_id for identity in identities}
    assert {event.parent_run_id for event in events} == {"run_session"}
    assert {event.root_run_id for event in events} == {"run_root"}
    assert {record.schema_version for record in records} == {2}
    assert {event.schema_version for event in events} == {1}
    assert {event.route for event in events} == {"core_llm"}
    response = CliRunner().invoke(main, ["telemetry", "costs", "show", "--period", "all", "--json"])
    assert response.exit_code == 0, response.output
    costs = json.loads(response.output)
    assert costs["total_requests"] == 4
    assert costs["by_verb"]["jev-rule-pack"]["invocations"] == 2


@pytest.mark.parametrize("managed", [False, True])
@pytest.mark.parametrize("grouping", [False, True])
def test_attempts_visible_without_fake_proxy(tmp_path, monkeypatch, managed, grouping):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    monkeypatch.setenv("FORGE_RUN_ID", "run_jev")
    monkeypatch.setenv("FORGE_ROOT_RUN_ID", "run_jev")
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    if managed:
        project = tmp_path / "project"
        project.mkdir()
        publish_session_from_fields(IndexStore(), "jev-test", project, project)
        monkeypatch.setenv("FORGE_SESSION", "jev-test")
    from forge.runtime_config import get_runtime_config

    monkeypatch.setattr(get_runtime_config().provider_trace, "inject_provider_user", grouping)
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        assert payload["provider"]["zdr"] is True
        assert ("user" in payload) is grouping
        if grouping:
            assert payload["user"] == payload["session_id"]
            assert "jev-test" not in payload["user"]
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, json={"error": {"code": 429}}, headers={"retry-after": "0"})
        return httpx.Response(
            200,
            json={
                "model": "typesafe/jev-1.13-20260917",
                "provider": "TypeSafe",
                "id": "gen-synthetic",
                "answers": {"q": {"type": "noul", "noul": 0.9}},
                "usage": {"input_tokens": 307, "output_tokens": 20, "cost": 0.000012894},
            },
        )

    result = asyncio.run(
        OpenRouterJudgmentClient(transport=httpx.MockTransport(handler)).judge(
            "Synthetic",
            {"q": NoulQuestion(instructions="Synthetic?", criteria={"true": "Yes", "false": "No"})},
            deadline=time.monotonic() + 3,
        )
    )
    records = read_downstream_records()
    assert len(records) == len(read_usage_events()) == 2
    # Cost readers merge a repeated downstream write for the same physical attempt.
    write_downstream_record(records[-1])
    runner = CliRunner()

    def run(*args):
        response = runner.invoke(main, args)
        assert response.exit_code == 0, response.output
        return json.loads(response.output)

    traces = run("telemetry", "trace", "list", "--period", "all", "--json")
    assert len(traces) == 2
    for attempt in result.attempts:
        trace = run("telemetry", "trace", "show", attempt.request_id, "--json")
        assert trace["request_id"] == attempt.request_id
        explain = runner.invoke(main, ["telemetry", "trace", "explain", attempt.request_id])
        assert explain.exit_code == 0, explain.output
    costs = run("telemetry", "costs", "show", "--period", "all", "--json")
    assert costs["total_requests"] == 2
    assert costs["total_cost_micros"] == 13
    assert costs["unavailable_requests"] == 1
    assert costs["by_verb"]["jev"]["invocations"] == 1
    for flag in ("--by-model", "--by-verb"):
        rendered = runner.invoke(main, ["telemetry", "costs", "show", "--period", "all", flag])
        assert rendered.exit_code == 0, rendered.output
    assert run("proxy", "metrics", "--json") == {}
    if managed:
        activity = run("telemetry", "activity", "jev-test", "--period", "all", "--json")
        assert sum(row["attempts"] for row in activity["downstream"]["rows"]) == 2
        assert sum(row["cost_micro_usd"] or 0 for row in activity["downstream"]["rows"]) == 13
