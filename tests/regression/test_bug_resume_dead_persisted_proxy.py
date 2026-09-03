"""Regression: bare resume must reject a dead persisted proxy before launch."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.claude import ProxyNotRunningError
from forge.cli.main import main
from forge.config.loader import write_proxy_instance_config
from forge.config.schema import ProxyInstanceConfig, TierModels
from forge.proxy.proxies import ProxyEntry, ProxyRegistry, ProxyRegistryStore
from forge.session import (
    IndexStore,
    SessionManager,
    SessionState,
    SessionStore,
    create_session_state,
)
from forge.session.active import ActiveSessionStore
from forge.session.config import LAUNCH_MODE_HOST
from forge.session.models import StartedWithProxy
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


def _publish_dead_proxy_session(project: Path, *, recorded_template: str = "openrouter-gemini") -> SessionState:
    state = create_session_state(
        "dead-proxy-resume",
        proxy_template="openrouter-gemini",
        proxy_base_url="http://127.0.0.1:65534",
        worktree_path=str(project),
        worktree_branch="main",
    )
    state.forge_root = str(project)
    state.confirmed.claude_session_id = "dead-proxy-conversation"
    state.confirmed.confirmed_by = "hook:SessionStart:startup"
    state.confirmed.started_with_proxy = StartedWithProxy(
        base_url="http://127.0.0.1:65534",
        proxy_id="dead-proxy-id",
        template=recorded_template,
        port=65534,
    )
    publish_session(IndexStore(), state, project)
    write_proxy_instance_config(
        "dead-proxy-id",
        ProxyInstanceConfig(
            proxy_format=1,
            template="openrouter-gemini",
            template_digest="dead-proxy-template",
            provider="openrouter",
            proxy_endpoint="http://127.0.0.1:65534",
            port=65534,
            upstream_base_url="https://openrouter.ai/api/v1",
            tiers=TierModels(sonnet="google/gemini-3.1-pro"),
            backend="openrouter",
            family="gemini",
        ),
    )
    ProxyRegistryStore().write(
        ProxyRegistry(
            proxies={
                "dead-proxy-id": ProxyEntry(
                    proxy_id="dead-proxy-id",
                    template="openrouter-gemini",
                    base_url="http://127.0.0.1:65534",
                    port=65534,
                    pid=999_999,
                    status="healthy",
                )
            }
        )
    )
    return state


def _prepare_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)
    monkeypatch.setenv("COLUMNS", "500")
    return project


def test_bare_resume_refuses_dead_persisted_proxy_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _prepare_project(tmp_path, monkeypatch)
    state = _publish_dead_proxy_session(project)

    routing_journal = project / ".forge" / "artifacts" / state.name / "routing" / "events.jsonl"
    with (
        patch("forge.cli.session_lifecycle._resolve_context_limit", return_value=200_000),
        patch(
            "forge.cli.claude._healthcheck_proxy",
            side_effect=ProxyNotRunningError("proxy is not running (connection refused at http://127.0.0.1:65534/)"),
        ) as healthcheck,
        patch("forge.core.ops.claude_session.invoke_claude") as invoke_claude,
    ):
        result = CliRunner().invoke(main, ["session", "resume", state.name])

    assert result.exit_code == 1
    assert "Persisted proxy route" in result.stderr
    assert "connection refused" in result.stderr
    assert "forge proxy start dead-proxy-id" in result.stderr
    assert f"forge session resume {state.name} --proxy openrouter-gemini" in result.stderr
    healthcheck.assert_called_once_with(
        base_url="http://127.0.0.1:65534",
        expected_template="openrouter-gemini",
        expected_proxy_id="dead-proxy-id",
    )
    invoke_claude.assert_not_called()
    assert not routing_journal.exists()
    assert SessionStore(str(project), state.name).read().confirmed.route_commit is None


def test_blank_recorded_template_fails_closed_without_noop_restart_tip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _prepare_project(tmp_path, monkeypatch)
    state = _publish_dead_proxy_session(project, recorded_template="")

    with (
        patch("forge.cli.session_lifecycle._resolve_context_limit", return_value=200_000),
        patch(
            "forge.cli.claude._healthcheck_proxy",
            side_effect=ValueError("template mismatch (expected '', got 'openrouter-gemini')"),
        ) as healthcheck,
        patch("forge.core.ops.claude_session.invoke_claude") as invoke_claude,
    ):
        result = CliRunner().invoke(main, ["session", "resume", state.name])

    assert result.exit_code == 1
    assert "template mismatch" in result.stderr
    assert "Repair the recorded proxy identity" in result.stderr
    assert "forge proxy start dead-proxy-id" not in result.stderr
    assert f"forge session resume {state.name} --proxy" not in result.stderr
    healthcheck.assert_called_once_with(
        base_url="http://127.0.0.1:65534",
        expected_template="",
        expected_proxy_id="dead-proxy-id",
    )
    invoke_claude.assert_not_called()


def test_recovery_lookup_failure_keeps_proxy_refusal_actionable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _prepare_project(tmp_path, monkeypatch)
    state = _publish_dead_proxy_session(project)

    with (
        patch("forge.cli.session_lifecycle._resolve_context_limit", return_value=200_000),
        patch(
            "forge.cli.claude._healthcheck_proxy",
            side_effect=ProxyNotRunningError("proxy is not running (connection refused at http://127.0.0.1:65534/)"),
        ),
        patch("forge.config.loader.load_proxy_instance_config", return_value=None),
        patch("forge.config.loader.template_exists", side_effect=OSError("template directory unreadable")),
        patch("forge.core.ops.claude_session.invoke_claude") as invoke_claude,
    ):
        result = CliRunner().invoke(main, ["session", "resume", state.name])

    assert result.exit_code == 1
    assert "Persisted proxy route" in result.stderr
    assert "Repair the recorded proxy identity" in result.stderr
    assert "template directory unreadable" not in result.stderr
    assert "forge proxy start dead-proxy-id" not in result.stderr
    assert f"forge session resume {state.name} --proxy" not in result.stderr
    invoke_claude.assert_not_called()


def test_force_resume_names_retained_child_after_proxy_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _prepare_project(tmp_path, monkeypatch)
    state = _publish_dead_proxy_session(project)
    ActiveSessionStore().upsert_session(
        state.name,
        worktree_path=str(project),
        launch_mode=LAUNCH_MODE_HOST,
        forge_root=str(project),
        launcher_pid=os.getpid(),
    )

    with (
        patch("forge.cli.session_lifecycle._resolve_context_limit", return_value=200_000),
        patch(
            "forge.cli.claude._healthcheck_proxy",
            side_effect=ProxyNotRunningError("proxy is not running (connection refused at http://127.0.0.1:65534/)"),
        ),
        patch("forge.core.ops.claude_session.invoke_claude") as invoke_claude,
    ):
        result = CliRunner().invoke(main, ["session", "resume", state.name, "--force"])

    assert result.exit_code == 1
    children = [
        name for name, _entry in SessionManager().list_sessions(forge_root_filter=str(project)) if name != state.name
    ]
    assert len(children) == 1
    child = children[0]
    assert f"Child session '{child}' was created and retained" in result.stderr
    assert f"retrying parent '{state.name}' creates another child" in result.stderr
    assert f"forge session resume {child} --proxy openrouter-gemini" in result.stderr
    invoke_claude.assert_not_called()
    assert SessionStore(str(project), child).read().confirmed.route_commit is None
