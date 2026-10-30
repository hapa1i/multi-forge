"""Guidance uses admitted launch facts without another proxy request."""

from __future__ import annotations

import shlex
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import click
import pytest

from forge.cli.main import main
from forge.cli.session_effort_hint import print_derived_effort_hint
from forge.cli.session_fork import _ClaudeForkCliPresenter
from forge.cli.session_lifecycle import (
    _ClaudeResumeCliPresenter,
    _ClaudeStartCliPresenter,
)
from forge.core.ops.claude_session import ClaudeLaunchReady
from forge.proxy.runtime_truth import ProxyRuntimeTruth
from forge.session.models import ModelRouteIntent


@pytest.fixture
def proxy_info() -> dict[str, Any]:
    return {
        "is_proxy": True,
        "template": "openrouter-openai",
        "proxy": {"proxy_id": "test-proxy"},
        "wire_shape": "openai_translated",
        "runtime": {
            "active_tier": "sonnet",
            "llm_defaults_by_tier": {"opus": {"reasoning_effort": "high"}, "sonnet": {}},
        },
    }


@pytest.fixture
def ready(proxy_info: dict[str, Any]) -> ClaudeLaunchReady:
    return ClaudeLaunchReady(
        session="actual-child",
        operation="start",
        incognito=False,
        template="openrouter-openai",
        proxy_id="test-proxy",
        model_route=ModelRouteIntent("gpt-6.1-sol", "opus", "proxy", "openrouter"),
        runtime=ProxyRuntimeTruth(proxy_info),
    )


@pytest.fixture(autouse=True)
def no_hint_probe(monkeypatch: pytest.MonkeyPatch) -> Mock:
    probe = Mock(side_effect=AssertionError("Guidance must reuse the cost snapshot"))
    monkeypatch.setattr("httpx.get", probe)
    monkeypatch.setattr("forge.session.launch_confirmation.urlopen", probe)
    return probe


def _context(verb: str, argv: list[str]) -> click.Context:
    group = main.get_command(click.Context(main), "session")
    assert isinstance(group, click.Group)
    parent = click.Context(group, info_name="session")
    command = group.get_command(parent, verb)
    assert command is not None
    return command.make_context(verb, list(argv), parent=parent)


@pytest.mark.parametrize(
    ("verb", "argv"),
    [
        ("start", ["original", "--worktree", "--branch", "feature/one", "--proxy", "test-proxy"]),
        ("resume", ["parent", "--fresh", "--child-name", "child", "--depth", "all", "--review"]),
        ("fork", ["parent", "--name", "child", "--strategy", "rewind", "--drop-last", "2"]),
        ("resume", ["original", "--proxy", "test-proxy", "--model", "gpt-6.1-sol", "--model-tier", "opus"]),
    ],
)
def test_durable_hint_targets_actual_session_without_replaying_creation_or_runtime_args(
    verb: str, argv: list[str], ready: ClaudeLaunchReady, capsys: pytest.CaptureFixture[str], no_hint_probe: Mock
) -> None:
    with _context(verb, [*argv, "--", "--add-dir", "/tmp/path with spaces", "--debug"]):
        print_derived_effort_hint(replace(ready, operation=verb))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("Effort is derived") == 1
    assert "thinking and the selected tier minimum (opus: high)" in captured.err
    assert captured.err.splitlines()[-1] == "  forge session resume actual-child --effort '<level>'"
    assert "After exiting" in captured.err
    assert all(token not in captured.err for token in ("original", "parent", "--fresh", "--branch", "--debug"))
    no_hint_probe.assert_not_called()


def test_long_prompt_is_not_reproduced(ready: ClaudeLaunchReady, capsys: pytest.CaptureFixture[str]) -> None:
    prompt = "first 'quoted' line\nsecond line " * 100
    with _context("start", ["original", "--system-prompt", prompt]):
        print_derived_effort_hint(ready)
    rendered = capsys.readouterr().err
    assert "quoted" not in rendered
    assert rendered.splitlines()[-1] == "  forge session resume actual-child --effort '<level>'"


@pytest.mark.parametrize("verb", ["incognito", "start", "fork"])
def test_incognito_guidance_is_a_new_nameless_launch_with_actual_route(
    verb: str, ready: ClaudeLaunchReady, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["old-name"] if verb == "incognito" else ["old-name", "--incognito"]
    with _context(verb, argv):
        print_derived_effort_hint(replace(ready, operation="incognito", incognito=True))
    rendered = capsys.readouterr().err
    assert "deleted on exit" in rendered
    assert "old-name" not in rendered
    assert "resume" not in rendered
    assert shlex.split(rendered.splitlines()[-1]) == [
        "forge",
        "session",
        "incognito",
        "--proxy",
        "test-proxy",
        "--model",
        "gpt-6.1-sol",
        "--model-tier",
        "opus",
        "--effort",
        "<level>",
    ]


def test_incognito_preserves_legacy_model_selector(
    ready: ClaudeLaunchReady, capsys: pytest.CaptureFixture[str]
) -> None:
    with _context("incognito", []):
        print_derived_effort_hint(replace(ready, incognito=True, model_route=None, direct_model="claude-opus-4-6"))
    assert "--model claude-opus-4-6" in capsys.readouterr().err


@pytest.mark.parametrize("shape", ["openai_translated", "openai_responses_passthrough"])
def test_all_messages_translation_shapes_emit(
    shape: str, proxy_info: dict[str, Any], ready: ClaudeLaunchReady, capsys: pytest.CaptureFixture[str]
) -> None:
    proxy_info["wire_shape"] = shape
    with _context("resume", ["task"]):
        print_derived_effort_hint(replace(ready, runtime=ProxyRuntimeTruth(proxy_info)))
    assert "Effort is derived" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("wire_shape", []),
        ("wire_shape", {}),
        ("wire_shape", True),
        ("wire_shape", 42),
        ("wire_shape", "anthropic_passthrough"),
        ("wire_shape", "unknown"),
        ("wire_shape", None),
        ("is_proxy", False),
        ("template", "another-template"),
        ("proxy", {"proxy_id": "other-proxy"}),
        ("proxy", None),
    ],
)
def test_unconfirmed_malformed_and_passthrough_routes_stay_silent(
    key: str, value: object, proxy_info: dict[str, Any], ready: ClaudeLaunchReady, capsys: pytest.CaptureFixture[str]
) -> None:
    proxy_info[key] = value
    with _context("resume", ["task"]):
        print_derived_effort_hint(replace(ready, runtime=ProxyRuntimeTruth(proxy_info)))
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("params", [{"effort": "high"}, {"no_launch": True}, {"json_output": True}, {"json": True}])
def test_excluded_launch_modes_stay_silent(
    params: dict[str, object], ready: ClaudeLaunchReady, capsys: pytest.CaptureFixture[str]
) -> None:
    with _context("start", ["task"]) as ctx:
        ctx.params.update(params)
        print_derived_effort_hint(ready)
    assert capsys.readouterr().err == ""


def test_direct_bare_and_unavailable_snapshot_stay_silent(
    ready: ClaudeLaunchReady, capsys: pytest.CaptureFixture[str]
) -> None:
    with _context("start", ["task"]):
        print_derived_effort_hint(replace(ready, template=None, proxy_id=None))
        print_derived_effort_hint(replace(ready, runtime=None))
    with click.Context(click.Command("start"), parent=click.Context(click.Group("claude"))):
        print_derived_effort_hint(ready)
    print_derived_effort_hint(ready)
    assert capsys.readouterr().err == ""


def test_unpinned_launch_names_reported_floors_without_claiming_default_tier(
    ready: ClaudeLaunchReady, capsys: pytest.CaptureFixture[str]
) -> None:
    with _context("resume", ["task"]):
        print_derived_effort_hint(replace(ready, model_route=None))
    assert "configured minimums: opus: high" in capsys.readouterr().err


@pytest.mark.parametrize("verb", ["start", "incognito", "resume", "fork"])
def test_each_presenter_renders_only_after_existing_snapshot_arrives(
    verb: str,
    ready: ClaudeLaunchReady,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("forge.cli.session_lifecycle._warn_before_claude_launch", lambda root: None)
    monkeypatch.setattr("forge.cli.session_fork._warn_before_claude_launch", lambda root: None)
    presenter = (
        _ClaudeResumeCliPresenter()
        if verb == "resume"
        else (
            _ClaudeForkCliPresenter(session_name="actual-child")
            if verb == "fork"
            else _ClaudeStartCliPresenter(session_name="actual-child")
        )
    )
    with _context(verb, ["task"]):
        presenter.before_launch(tmp_path)
        assert capsys.readouterr().err == ""
        presenter.on_launch_ready(replace(ready, operation=verb, incognito=verb == "incognito"))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("Effort is derived") == 1


def test_worktree_recovery_supplies_actual_project_scope(
    ready: ClaudeLaunchReady, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "a [release] 'branch'"
    target.mkdir()
    with _context("fork", ["parent", "--into", str(target)]):
        print_derived_effort_hint(replace(ready, forge_root=str(target)))
    command = capsys.readouterr().err.splitlines()[-1].strip()
    assert shlex.split(command) == [
        "cd",
        str(target),
        "&&",
        "forge",
        "session",
        "resume",
        "actual-child",
        "--effort",
        "<level>",
    ]
