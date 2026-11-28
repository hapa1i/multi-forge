"""Codex reports must distinguish missing launch evidence from an unreachable proxy."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.ops.session_routing import (
    build_codex_proxy_routing_payload,
    commit_launch_routing,
)
from forge.core.reactive.env import new_root_run_identity
from forge.core.runtime.codex_proxy_launch import CodexProxyLaunch
from forge.proxy.proxy_orchestrator import ProxyUnreachableError, ResponsesListener
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.events import get_session_event_journal_path
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".forge").mkdir()
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    route = CodexProxyLaunch(
        "bound", "codex-responses-local", "http://127.0.0.1:8105", "codex-responses-local", "litellm", "m", "m", None
    )
    state = create_session_state(
        "work",
        worktree_path=str(tmp_path),
        runtime="codex",
        proxy_id=route.proxy_id,
        proxy_template=route.template,
        proxy_base_url=route.base_url,
    )
    state.forge_root = str(tmp_path)
    entry = publish_session(IndexStore(), state, tmp_path)
    assert entry.instance_id
    commit_launch_routing(
        store=SessionStore(str(tmp_path), state.name),
        state=state,
        root=new_root_run_identity(),
        operation="start",
        payload=build_codex_proxy_routing_payload(route, entry.instance_id),
        authority_attempt=None,
    )
    return tmp_path


@pytest.mark.parametrize("missing", [True, False], ids=["missing", "empty"])
def test_session_show_explains_unproven_commitment(project: Path, missing: bool) -> None:
    path = get_session_event_journal_path(project, "work", "routing")
    if missing:
        path.unlink()
    else:
        path.write_bytes(b"")

    result = CliRunner().invoke(main, ["session", "show", "work"])
    assert result.exit_code == 0, result.output
    assert "Launch commitment unavailable" in result.output
    assert "routing journal" in result.output


@pytest.mark.parametrize("reachable", [True, False], ids=["reachable", "unreachable"])
def test_responses_effort_distinguishes_listener_reachability(project: Path, monkeypatch, reachable: bool) -> None:
    def listener(*args, **kwargs):
        if reachable:
            return ResponsesListener("m", {}, "codex-responses-local", "litellm")
        raise ProxyUnreachableError("fixture listener is offline")

    monkeypatch.setattr("forge.proxy.proxy_orchestrator.read_responses_listener", listener)
    result = CliRunner().invoke(main, ["session", "model", "show", "work", "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["live_proxy"]["reachable"] is reachable
    assert report["effort"]["reason"] == ("proxy_effort_unavailable" if reachable else "proxy_unavailable")
