"""Regression: use confirmed routing and one policy shadow session selector.

O013: supervisor setup read ``proxy_id`` from ``ProxyIntent``, which has no such field, so a matching current route
looked different and produced a redundant supervisor proxy override.

O034: shadow ``show`` and ``status`` used different implicit-session resolvers, so sole-local selection and failure
reporting depended on which read command the operator chose.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

import forge.core.ops.policy as policy_ops
from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.models import LaunchConfirmed, StartedWithProxy
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression

_SHADOW_COMMANDS = ("show", "status")


@pytest.fixture
def policy_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("FORGE_SESSION", raising=False)

    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)
    return project


def _seed_session(project: Path, name: str) -> None:
    state = create_session_state(name, worktree_path=str(project))
    state.forge_root = str(project)
    publish_session(
        IndexStore(),
        state,
        project,
        forge_root=str(project),
        checkout_root=str(project),
        relative_path=".",
    )


def _invoke_shadow(command: str, session: str | None = None, *, as_json: bool = True):
    args = ["policy", "shadow", command]
    if session is not None:
        args.append(session)
    if as_json:
        args.append("--json")
    return CliRunner().invoke(main, args)


def _supervisor_set_with_matching_source(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    confirm_current_launch: bool,
) -> policy_ops.SupervisorSetResult:
    proxy_id = "proxy-current"
    template = "litellm-anthropic"
    base_url = "http://localhost:8085"

    current = create_session_state(
        "executor",
        proxy_template=template,
        proxy_base_url=base_url,
        worktree_path=str(project),
    )
    current.forge_root = str(project)
    if confirm_current_launch:
        current.confirmed.launch = LaunchConfirmed(routing_mode="proxy", proxy_id=proxy_id, base_url=base_url)
    store = SessionStore(str(project), current.name)
    store.write(current)

    source = create_session_state("planner", worktree_path=str(project))
    source.forge_root = str(project)
    source.confirmed.started_with_proxy = StartedWithProxy(
        base_url=base_url,
        proxy_id=proxy_id,
        template=template,
    )
    monkeypatch.setattr(
        policy_ops.supervisor_semantic,
        "validate_supervisor_target",
        lambda *_args, **_kwargs: source,
    )

    return policy_ops.supervisor_set(
        store=store,
        manifest=current,
        target=source.name,
        policy_forge_root=str(project),
    )


def test_o013_matching_confirmed_proxy_does_not_seed_routing_override(
    policy_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _supervisor_set_with_matching_source(policy_project, monkeypatch, confirm_current_launch=True)

    assert result.routing_display is None
    assert result.config.proxy is None


def test_o013_missing_launch_confirmation_keeps_compatibility_seed(
    policy_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _supervisor_set_with_matching_source(policy_project, monkeypatch, confirm_current_launch=False)

    assert result.routing_display == "proxy-current"
    assert result.config.proxy == "proxy-current"


@pytest.mark.parametrize("command", _SHADOW_COMMANDS)
@pytest.mark.parametrize("selection", ("explicit", "current", "sole_local"))
def test_o034_shadow_reads_share_session_precedence(
    command: str,
    selection: str,
    policy_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_session(policy_project, "selected")
    session: str | None = None
    if selection == "explicit":
        _seed_session(policy_project, "other")
        session = "selected"
    elif selection == "current":
        _seed_session(policy_project, "other")
        monkeypatch.setenv("FORGE_SESSION", "selected")

    result = _invoke_shadow(command, session)

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["session"] == "selected"


@pytest.mark.parametrize("command", _SHADOW_COMMANDS)
@pytest.mark.parametrize("as_json", (False, True))
def test_o034_shadow_reads_report_missing_session_cleanly(
    command: str,
    as_json: bool,
    policy_project: Path,
) -> None:
    result = _invoke_shadow(command, as_json=as_json)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Traceback" not in result.stderr
    if as_json:
        payload = json.loads(result.stderr)
        assert "No session found" in payload["error"]
    else:
        assert "No session found" in result.stderr


@pytest.mark.parametrize("command", _SHADOW_COMMANDS)
@pytest.mark.parametrize("as_json", (False, True))
def test_o034_shadow_reads_report_ambiguous_session_cleanly(
    command: str,
    as_json: bool,
    policy_project: Path,
) -> None:
    _seed_session(policy_project, "alpha")
    _seed_session(policy_project, "beta")

    result = _invoke_shadow(command, as_json=as_json)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Traceback" not in result.stderr
    if as_json:
        error = json.loads(result.stderr)["error"]
    else:
        error = result.stderr
    assert "Multiple sessions" in error
    assert "alpha" in error
    assert "beta" in error
    assert "--session" not in error
    assert "SESSION argument" in error
    assert f"forge policy shadow {command} alpha" in error
