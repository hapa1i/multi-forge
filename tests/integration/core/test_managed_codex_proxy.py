"""A real managed Codex turn can use two Responses creates and reopen the same thread without native auth."""

import json
import os
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path

import httpx
import pytest
import yaml
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.paths import get_forge_home
from forge.core.telemetry.downstream import read_downstream_records
from forge.core.usage.ledger import read_usage_events
from forge.session.store import SessionStore
from tests.fixtures.proxy import allocate_ephemeral_port
from tests.integration.core.test_codex_session_start import (
    _init_git_repo,
    _register_parent,
    _write_planning_transcript,
)
from tests.integration.proxy.conftest import (
    _register_proxy_for_test,
    _start_proxy_subprocess,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]


_stub = import_module("scripts.experiments.openrouter.helpers.responses_stub")


@pytest.fixture
def start_responses_proxy(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    _init_git_repo(project)
    (project / ".forge").mkdir()
    (project / "fixture.txt").write_text(_stub.MARKER)
    planning = project / "plan.jsonl"
    _write_planning_transcript(planning)
    _register_parent(project, planning)
    monkeypatch.chdir(project)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    for var in ("CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(var, "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost,::1")
    codex_home = Path(os.environ["CODEX_HOME"])
    (codex_home / "config.toml").write_text(
        'cli_auth_credentials_store="file"\ncheck_for_update_on_startup=false\n'
        "[analytics]\nenabled=false\n[feedback]\nenabled=false\n"
    )
    port = allocate_ephemeral_port()
    template = "codex-responses-openrouter"
    upstream = _stub.ResponsesStub(tmp_path / "capture")
    respond = upstream.respond

    def metered_response(method, url, body):
        status, mime, payload = respond(method, url, body)
        return status, mime, payload.replace(b'"input_tokens":', b'"cost":0.01,"input_tokens":')

    monkeypatch.setattr(upstream, "respond", metered_response)
    with upstream:

        @contextmanager
        def serve(proxy_id, *, settings=None):
            path = get_forge_home() / "proxies" / proxy_id / "proxy.yaml"
            if not path.exists():
                _register_proxy_for_test(
                    proxy_id=proxy_id,
                    template=template,
                    port=port,
                    forge_home=get_forge_home(),
                    upstream_base_url=upstream.base_url,
                )
            if settings:
                config = yaml.safe_load(path.read_text())
                config.update(settings)
                path.write_text(yaml.safe_dump(config))
            proc = _start_proxy_subprocess(
                template=template,
                port=port,
                forge_home=get_forge_home(),
                proxy_id=proxy_id,
                cwd=project,
                env={**os.environ, "OPENROUTER_API_KEY": "fixture-loopback", "OPENROUTER_BASE_URL": upstream.base_url},
            )
            try:
                yield
            finally:
                proc.terminate()
                proc.wait(timeout=10)

        yield serve, upstream


@pytest.fixture
def proxy(start_responses_proxy):
    serve, upstream = start_responses_proxy
    with serve("bound", settings={"costs": {"caps": {"per_day": 0.03}, "on_cap_hit": "reject"}}):
        yield upstream


def test_proxy_only_managed_start_and_resume(proxy):
    def cli(*args):
        result = CliRunner().invoke(main, ["session", *args])
        assert result.exit_code == 0, (result.output, result.exception)
        return result.output

    def read_turn():
        facts = SessionStore(str(Path.cwd()), "impl").read().confirmed.codex
        assert facts and facts.completed_turn and facts.reconciled_run_id
        assert (facts.auth_method, facts.auth_source, facts.billing_mode) == ("proxy_token", "forge_proxy", "unknown")
        assert facts.completed_turn.requested_model == facts.completed_turn.dispatched_model == "google/gemini-4-carbon"
        return facts.thread_id, facts.reconciled_run_id

    cli(
        "start",
        "impl",
        "--runtime",
        "codex",
        "--proxy",
        "bound",
        "--resume-from",
        "planner",
        "--strategy",
        "structured",
        "--task",
        "Read fixture.txt using the local shell and reply.",
        "--",
        "-m",
        "google/gemini-4-carbon",
    )
    first_thread, first = read_turn()
    assert [r["sent"] for r in proxy.records] == ["tool", "done"]
    events = read_usage_events(root_run_id=first)
    assert len(events) == 1
    event = events[0]
    assert (event.run_id, event.route, event.proxy_id) == (first, "codex_exec", "bound")
    assert (event.input_tokens, event.output_tokens) == (20, 4)
    attempts = read_downstream_records(kind="attempt", forge_root_run_id=first)
    assert len(attempts) == 2
    assert all(r.forge_run_id == first and r.cost_micros == 10000 and r.source_id == "bound" for r in attempts)
    costs = CliRunner().invoke(main, ["telemetry", "costs", "show", "bound", "--json"])
    assert costs.exit_code == 0, costs.output
    assert json.loads(costs.output)["total_requests"] == 2
    cli("resume", "impl", "--task", "FORGE_FOLLOWUP: Read the value from the last answer.")
    next_thread, second = read_turn()
    assert first_thread == next_thread and first != second
    assert proxy.records[-1]["sent"] == "followup"
    (resumed_event,) = read_usage_events(root_run_id=second)
    assert (resumed_event.input_tokens, resumed_event.output_tokens) == (10, 2)
    binding = SessionStore(str(Path.cwd()), "impl").read().intent.proxy
    assert binding
    with httpx.Client(base_url=binding.base_url, trust_env=False) as client:
        current = client.get("/").json()["metrics"]["costs"]["caps"]["daily"]
        assert current["current_usd"] == current["limit_usd"] == 0.03
        refused = client.post("/v1/responses", json={"model": "google/gemini-4-carbon", "input": "cap check"})
    assert refused.status_code == 429
    assert len(proxy.records) == 3


def test_both_resume_forms_check_bound_listener_and_live_fallback_before_commit(start_responses_proxy):
    from forge.session.routing import read_routing_events

    serve, upstream = start_responses_proxy
    runner = CliRunner()
    requested, fallback = "openai/gpt-6.2-astra", "google/gemini-4-carbon"
    with serve("bound"):
        result = runner.invoke(
            main,
            [
                "session",
                "start",
                "replay",
                "--runtime",
                "codex",
                "--resume-from",
                "planner",
                "--strategy",
                "structured",
                "--proxy",
                "bound",
                "--task",
                "Read fixture.txt and reply.",
                "--",
                "-m",
                requested,
            ],
        )
        assert result.exit_code == 0, (result.output, result.exception)

    store = SessionStore(str(Path.cwd()), "replay")
    state = store.read()
    assert state.confirmed.codex and state.confirmed.codex.completed_turn
    assert state.confirmed.codex.completed_turn.dispatched_model == requested
    history = read_routing_events(Path.cwd(), state)
    first_requests = len(upstream.records)
    assert first_requests

    def refuses(*diagnostics):
        for options in ([], ["--task", "FORGE_FOLLOWUP: read the last answer"]):
            refusal = runner.invoke(main, ["session", "resume", "replay", *options])
            assert refusal.exit_code == 1, (refusal.output, refusal.exception)
            for phrase in diagnostics:
                assert phrase in refusal.output, refusal.output
            assert len(upstream.records) == first_requests
            assert read_routing_events(Path.cwd(), store.read()) == history

    refuses("unreachable")
    with serve("other"):
        refuses("bound", "other")
    with serve("bound", settings={"zdr_fallbacks": {requested: fallback}}):
        refuses(requested, fallback)
    with serve("bound", settings={"zdr_fallbacks": {}}):
        result = runner.invoke(main, ["session", "resume", "replay", "--task", "FORGE_FOLLOWUP: read the last answer"])
        assert result.exit_code == 0, (result.output, result.exception)
    resumed = store.read()
    assert resumed.confirmed.codex and resumed.confirmed.codex.thread_id == state.confirmed.codex.thread_id
    assert len(read_routing_events(Path.cwd(), resumed)) == len(history) + 1
    assert upstream.records[-1]["sent"] == "followup"
