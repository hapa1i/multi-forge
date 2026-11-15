"""The auto-mode judge notice names the backend from the launch-time proxy snapshot."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import Mock

import click
import pytest

from forge.cli.auto_mode_notice import (
    print_auto_mode_judge_notice,
    print_session_auto_mode_judge_notice,
)
from forge.cli.main import main
from forge.cli.session_fork import _ClaudeForkCliPresenter
from forge.cli.session_lifecycle import (
    _ClaudeResumeCliPresenter,
    _ClaudeStartCliPresenter,
)
from forge.core.ops.claude_session import ClaudeLaunchReady
from forge.proxy.runtime_truth import ProxyRuntimeTruth
from forge.session.models import ModelRouteIntent

_NOTICE = "Auto mode: actions are judged by"


@pytest.fixture
def proxy_info() -> dict[str, Any]:
    return {
        "is_proxy": True,
        "template": "openrouter-gemini",
        "proxy": {"proxy_id": "slate-lime"},
        "wire_shape": "openai_translated",
        "runtime": {
            "active_tier": "sonnet",
            "backend_id": "openrouter",
            "tier_mappings": {
                "haiku": "google/gemini-3.8-flash",
                "sonnet": "google/gemini-4-carbon",
                "opus": "google/gemini-4-carbon",
            },
            "model_alternatives": {},
        },
    }


@pytest.fixture
def ready(proxy_info: dict[str, Any]) -> ClaudeLaunchReady:
    return ClaudeLaunchReady(
        session="task",
        operation="start",
        incognito=False,
        template="openrouter-gemini",
        proxy_id="slate-lime",
        model_route=None,
        runtime=ProxyRuntimeTruth(proxy_info),
        auto_mode_classifier_model="claude-sonnet-5",
    )


@pytest.fixture(autouse=True)
def no_notice_probe(monkeypatch: pytest.MonkeyPatch) -> Mock:
    probe = Mock(side_effect=AssertionError("Session notices must reuse the launch snapshot"))
    monkeypatch.setattr("forge.session.launch_confirmation.urlopen", probe)
    return probe


def _context(verb: str, argv: list[str]) -> click.Context:
    group = main.get_command(click.Context(main), "session")
    assert isinstance(group, click.Group)
    parent = click.Context(group, info_name="session")
    command = group.get_command(parent, verb)
    assert command is not None
    return command.make_context(verb, list(argv), parent=parent)


def test_names_tier_backend_for_default_classifier(
    proxy_info: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    print_auto_mode_judge_notice("claude-sonnet-5", ProxyRuntimeTruth(proxy_info))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    assert (
        f"{_NOTICE} google/gemini-4-carbon (requested as claude-sonnet-5, sonnet tier); "
        "Forge turned off the server-side check for translated proxies." in captured.err
    )


def test_names_model_alternative_that_keeps_a_claude_judge(
    proxy_info: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    proxy_info["runtime"]["model_alternatives"] = {"sonnet": {"claude-sonnet-5": "anthropic/claude-sonnet-5"}}
    print_auto_mode_judge_notice("claude-sonnet-5", ProxyRuntimeTruth(proxy_info))
    assert f"{_NOTICE} anthropic/claude-sonnet-5 (requested as claude-sonnet-5, sonnet tier)" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("claude-sonnet-5", f"{_NOTICE} the model this proxy serves for claude-sonnet-5;"),
        ("anthropic/claude-sonnet-5", f"{_NOTICE} anthropic/claude-sonnet-5 through this proxy;"),
    ],
)
def test_without_snapshot_names_only_the_request_model(
    model: str, expected: str, capsys: pytest.CaptureFixture[str]
) -> None:
    print_auto_mode_judge_notice(model, None)
    assert expected in capsys.readouterr().err


def test_projected_tier_routes_non_claude_classifier_model(
    proxy_info: dict[str, Any], ready: ClaudeLaunchReady, capsys: pytest.CaptureFixture[str]
) -> None:
    """A routed sonnet-tier --model becomes the classifier model and keeps its tier projection."""
    proxy_info["runtime"]["model_alternatives"] = {"sonnet": {"gpt-6.1-sol": "openai/gpt-6.1-sol"}}
    event = replace(
        ready,
        runtime=ProxyRuntimeTruth(proxy_info),
        model_route=ModelRouteIntent("gpt-6.1-sol", "sonnet", "proxy", "openrouter"),
        auto_mode_classifier_model="gpt-6.1-sol",
    )
    with _context("start", ["task"]):
        print_session_auto_mode_judge_notice(event)
    assert f"{_NOTICE} openai/gpt-6.1-sol (requested as gpt-6.1-sol, sonnet tier)" in capsys.readouterr().err


def test_snapshot_from_another_proxy_is_not_trusted(
    proxy_info: dict[str, Any], ready: ClaudeLaunchReady, capsys: pytest.CaptureFixture[str]
) -> None:
    proxy_info["proxy"] = {"proxy_id": "other-proxy"}
    with _context("resume", ["task"]):
        print_session_auto_mode_judge_notice(replace(ready, runtime=ProxyRuntimeTruth(proxy_info)))
    rendered = capsys.readouterr().err
    assert "the model this proxy serves for claude-sonnet-5" in rendered
    assert "gemini" not in rendered


def test_launch_without_forge_default_stays_silent(
    ready: ClaudeLaunchReady, capsys: pytest.CaptureFixture[str]
) -> None:
    with _context("start", ["task"]):
        print_session_auto_mode_judge_notice(replace(ready, auto_mode_classifier_model=None))
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("params", [{"no_launch": True}, {"json_output": True}, {"json": True}])
def test_excluded_launch_modes_stay_silent(
    params: dict[str, object], ready: ClaudeLaunchReady, capsys: pytest.CaptureFixture[str]
) -> None:
    with _context("start", ["task"]) as ctx:
        ctx.params.update(params)
        print_session_auto_mode_judge_notice(ready)
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("verb", ["start", "incognito", "resume", "fork"])
def test_each_presenter_renders_the_notice_once(
    verb: str,
    ready: ClaudeLaunchReady,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("forge.cli.session_lifecycle._warn_before_claude_launch", lambda _root: None)
    monkeypatch.setattr("forge.cli.session_fork._warn_before_claude_launch", lambda _root: None)
    presenter = (
        _ClaudeResumeCliPresenter()
        if verb == "resume"
        else (
            _ClaudeForkCliPresenter(session_name="task")
            if verb == "fork"
            else _ClaudeStartCliPresenter(session_name="task")
        )
    )
    with _context(verb, ["task"]):
        presenter.on_launch_ready(replace(ready, operation=verb, incognito=verb == "incognito"))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count(_NOTICE) == 1
