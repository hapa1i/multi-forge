"""Session reports read the same journal, index and telemetry shards as the CLI."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.ops.session_routing import (
    build_codex_proxy_routing_payload,
    commit_launch_routing,
)
from forge.core.reactive.env import new_root_run_identity
from forge.core.run_id import derive_provider_session_id
from forge.core.runtime.codex_proxy_launch import CodexProxyLaunch
from forge.core.telemetry.downstream import write_downstream_record
from forge.core.telemetry.upstream import UpstreamOutcome, write_upstream_outcome
from forge.core.usage.emit import emit_codex_usage
from forge.proxy.cost_logger import build_request_cost_record
from forge.proxy.proxy_orchestrator import ResponsesListener
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.events import get_session_event_journal_path
from tests.fixtures.session_state import delete_published_session, publish_session

pytestmark = pytest.mark.integration

_NAME = "shared"
_PROXY = CodexProxyLaunch(
    proxy_id="shared-instance",
    template="openrouter-anthropic",
    base_url="http://127.0.0.1:8234",
    backend_id="openrouter",
    provider="openrouter",
    requested_model="google/gemini-4-carbon",
    dispatched_model="uncatalogued/provider-model",
    required_zdr=True,
)


def _publish(project: Path) -> str:
    (project / ".forge").mkdir(parents=True, exist_ok=True)
    (project / ".git").mkdir(exist_ok=True)
    state = create_session_state(
        _NAME,
        runtime="codex",
        worktree_path=str(project),
        proxy_template=_PROXY.template,
        proxy_base_url=_PROXY.base_url,
        proxy_id=_PROXY.proxy_id,
    )
    state.forge_root = str(project)
    entry = publish_session(IndexStore(), state, project, forge_root=project)
    assert entry.instance_id
    return entry.instance_id


def _commit(project: Path, instance: str, operation: str) -> str:
    run = new_root_run_identity()
    store = SessionStore(str(project), _NAME)
    commit_launch_routing(
        store=store,
        state=store.read(),
        root=run,
        operation=operation,
        payload=build_codex_proxy_routing_payload(_PROXY, instance),
        authority_attempt=None,
    )
    return run.run_id


def _attempt(run: str | None, charge: int) -> None:
    # Deliberately identical for both projects, including the record with no run ID.
    label = derive_provider_session_id(_NAME, root_run_id="", role=None)
    record = build_request_cost_record(
        proxy_id=_PROXY.proxy_id,
        model=_PROXY.dispatched_model,
        tier="",
        backend_id="openrouter",
        input_tokens=charge,
        output_tokens=1,
        cached_tokens=0,
        cost_micros=charge,
        latency_ms=12.0,
        failed=False,
        request_id=uuid4().hex,
        reporter="openrouter",
        confidence="reported",
        forge_run_id=run,
        forge_root_run_id=run,
    )
    write_downstream_record(replace(record, provider_session_id=label))


def _cli(*args: str) -> str:
    result = CliRunner().invoke(main, list(args))
    assert result.exit_code == 0, (result.output, result.exception)
    return result.output


def _activity() -> dict:
    return json.loads(_cli("telemetry", "activity", _NAME, "--period", "all", "--json"))


def test_damaged_routing_journal_preserves_session_show_and_marks_activity_partial(tmp_path, monkeypatch):
    project = tmp_path / "project"
    instance = _publish(project)
    _commit(project, instance, "start")
    monkeypatch.chdir(project)
    path = get_session_event_journal_path(project, _NAME, "routing")
    path.write_text('{"broken": true}\n', encoding="utf-8")

    detail = json.loads(_cli("session", "show", _NAME, "--json"))
    assert detail["intent"]["proxy"]["proxy_id"] == _PROXY.proxy_id
    commit = detail["confirmed"]["route_commit"]
    assert commit["evidence_source"] == "unavailable"
    assert commit["reason"]
    assert (
        _cli(
            "session",
            "show",
            _NAME,
            "--field",
            "confirmed.route_commit.evidence_source",
        ).strip()
        == "unavailable"
    )
    human = _cli("session", "show", _NAME)
    assert "Launch commitment unavailable" in human and _PROXY.proxy_id in human
    assert "routing_journal_unavailable" in _activity()["notes"]
    assert "Launch ownership could not be verified" in _cli("telemetry", "activity", _NAME)


def test_same_name_tui_headless_worker_and_recreation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first_id, second_id = _publish(first), _publish(second)
    first_tui = _commit(first, first_id, "start")
    second_headless = _commit(second, second_id, "start")
    _attempt(first_tui, 10)
    _attempt(second_headless, 21)
    _attempt(second_headless, 22)
    _attempt(None, 100)
    # The one headless usage event supplies JSONL totals; each proxy create supplies its own charge.
    emit_codex_usage(
        run_id=second_headless,
        root_run_id=second_headless,
        command="codex-bridge",
        session=_NAME,
        status="success",
        input_tokens=90,
        output_tokens=7,
        proxy_id=_PROXY.proxy_id,
        provider="openrouter",
    )
    monkeypatch.chdir(first)
    assert _activity()["downstream"]["total_cost_micro_usd"] == 10

    _attempt(_commit(first, first_id, "resume"), 11)
    _attempt(_commit(second, second_id, "resume"), 23)
    worker = new_root_run_identity()
    monkeypatch.setenv("FORGE_SESSION", _NAME)
    monkeypatch.setenv("FORGE_SESSION_INSTANCE", second_id)
    write_upstream_outcome(
        UpstreamOutcome(
            command="supervisor", status="warning", session=_NAME, run_id=worker.run_id, root_run_id=worker.root_run_id
        )
    )
    _attempt(worker.run_id, 24)
    first_report = _activity()
    assert first_report["upstream"]["operations"] == []
    assert first_report["downstream"]["downstream_records"] == 2
    assert first_report["downstream"]["total_cost_micro_usd"] == first_report["downstream"]["total_input_tokens"] == 21

    monkeypatch.chdir(second)
    second_report = _activity()
    assert [op["command"] for op in second_report["upstream"]["operations"]] == ["supervisor"]
    assert second_report["downstream"]["downstream_records"] == 4
    assert second_report["downstream"]["total_cost_micro_usd"] == 21 + 22 + 23 + 24
    assert second_report["downstream"]["total_input_tokens"] == 90 + 23 + 24
    assert second_report["downstream"]["total_output_tokens"] == 7 + 1 + 1
    [headless] = [row for row in second_report["downstream"]["rows"] if row["command"] == "codex-bridge"]
    assert headless["workers"] == 1 and headless["cost_micro_usd"] == 43

    assert delete_published_session(IndexStore(), _NAME, second)
    replacement = _publish(second)
    assert replacement != second_id
    _attempt(_commit(second, replacement, "start"), 3)
    replacement_report = _activity()
    assert replacement_report["upstream"]["operations"] == []
    assert replacement_report["downstream"]["downstream_records"] == 1
    assert replacement_report["downstream"]["total_cost_micro_usd"] == 3


def test_session_show_and_model_surfaces_report_verbatim_slugs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    instance = _publish(project)
    _commit(project, instance, "start")
    monkeypatch.chdir(project)

    def listener(
        base_url: str, *, expected_proxy_id: str, expected_template: str, timeout_s: float
    ) -> ResponsesListener:
        assert (base_url, expected_proxy_id, expected_template) == (_PROXY.base_url, _PROXY.proxy_id, _PROXY.template)
        return ResponsesListener(
            "openai/new-default",
            {},
            "openrouter",
            "openrouter",
        )

    monkeypatch.setattr("forge.proxy.proxy_orchestrator.read_responses_listener", listener)
    for args in (("session", "show"), ("session", "model", "show"), ("session", "model", "history")):
        human = _cli(*args, _NAME)
        for field in (_PROXY.proxy_id, _PROXY.requested_model, _PROXY.dispatched_model):
            assert field in human

    detail = json.loads(_cli("session", "show", _NAME, "--json"))
    assert detail["intent"]["proxy"]["proxy_id"] == detail["proxy"]["proxy_id"] == _PROXY.proxy_id
    assert detail["confirmed"]["route_commit"]["codex_proxy"]["dispatched_model"] == _PROXY.dispatched_model
    report = json.loads(_cli("session", "model", "show", _NAME, "--json"))
    assert report["route_intent"]["kind"] == "proxy"
    assert report["live_proxy"]["default_requested_model"] == "openai/new-default"
    assert report["live_proxy"]["responses_ingress"] is True
    assert report["route_commit"]["wire_shape"] == _PROXY.wire_shape
    history = json.loads(_cli("session", "model", "history", _NAME, "--json"))
    assert (
        history["events"][0]["payload"]["codex_proxy"]
        == report["route_commit"]["codex_proxy"]
        == {
            "instance_id": instance,
            "requested_model": _PROXY.requested_model,
            "dispatched_model": _PROXY.dispatched_model,
        }
    )
