"""Live-effort guidance preserves the parsed managed lifecycle command and streams."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import click
import httpx
import pytest

from forge.cli.main import main
from forge.cli.session_effort_hint import print_derived_effort_hint
from forge.cli.session_fork import _ClaudeForkCliPresenter
from forge.cli.session_lifecycle import (
    _ClaudeResumeCliPresenter,
    _ClaudeStartCliPresenter,
)
from forge.core.ops.claude_session import (
    ClaudeResumeAction,
    ClaudeStartCreated,
    ResumePrepared,
)

BASE_URL = "http://127.0.0.1:65530"


@pytest.fixture
def proxy_info() -> dict[str, Any]:
    return {
        "is_proxy": True,
        "template": "openrouter-openai",
        "proxy": {"proxy_id": "test-proxy"},
        "wire_shape": "openai_translated",
        "runtime": {
            "active_tier": "sonnet",
            "llm_defaults_by_tier": {
                "opus": {"reasoning_effort": "high"},
                "sonnet": {},
            },
        },
    }


@pytest.fixture
def hint_probe(monkeypatch: pytest.MonkeyPatch, proxy_info: dict[str, Any]) -> Mock:
    probe = Mock(
        side_effect=lambda *args, **kwargs: httpx.Response(
            200, json=proxy_info, request=httpx.Request("GET", BASE_URL + "/")
        )
    )
    monkeypatch.setattr("forge.cli.session_effort_hint.httpx.get", probe)
    monkeypatch.setattr("forge.cli.session_lifecycle._warn_before_claude_launch", lambda root: None)
    monkeypatch.setattr("forge.cli.session_fork._warn_before_claude_launch", lambda root: None)
    return probe


def _context(verb: str, argv: list[str]) -> click.Context:
    group = main.get_command(click.Context(main), "session")
    assert isinstance(group, click.Group)
    parent = click.Context(group, info_name="session")
    command = group.get_command(parent, verb)
    assert command is not None
    return command.make_context(verb, list(argv), parent=parent)


def _hint(**kwargs: Any) -> None:
    print_derived_effort_hint(
        base_url=kwargs.pop("base_url", BASE_URL),
        template="openrouter-openai",
        proxy_id="test-proxy",
        projected_tier="opus",
        **kwargs,
    )


@pytest.mark.parametrize(
    ("verb", "argv"),
    [
        (
            "start",
            ["task", "--worktree", "--branch", "feature/one", "--proxy", "test-proxy"],
        ),
        (
            "resume",
            [
                "parent",
                "--fresh",
                "--child-name",
                "child",
                "--strategy",
                "ai-curated",
                "--depth",
                "all",
                "--review",
            ],
        ),
        (
            "fork",
            [
                "parent",
                "--name",
                "child",
                "--into",
                "/tmp/a [release]",
                "--strategy",
                "rewind",
                "--drop-last",
                "2",
            ],
        ),
        (
            "incognito",
            [
                "private",
                "--system-prompt",
                "a long prompt with 'quotes'",
                "--proxy",
                "test-proxy",
            ],
        ),
    ],
)
def test_hint_is_one_stderr_line_with_exact_lifecycle_and_passthrough(
    verb: str, argv: list[str], hint_probe: Mock, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    argv = list(argv)
    if "--into" in argv:
        target = tmp_path / "a [release]"
        target.mkdir()
        argv[argv.index("--into") + 1] = str(target)
    tail = ["--", "--add-dir", "/tmp/path with spaces", "--debug"]
    with _context(verb, [*argv, *tail]):
        _hint()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert len(captured.err.splitlines()) == 1
    assert captured.err.count("Effort is derived") == 1
    assert "thinking and the selected tier minimum (opus: high)" in captured.err
    command = shlex.join(["forge", "session", verb, *argv, "--effort", "<level>", *tail])
    assert command in captured.err
    hint_probe.assert_called_once_with(BASE_URL + "/", timeout=0.5)


@pytest.mark.parametrize("shape", ["openai_translated", "openai_responses_passthrough"])
def test_all_messages_translation_shapes_emit(
    shape: str,
    proxy_info: dict[str, Any],
    hint_probe: Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proxy_info["wire_shape"] = shape
    with _context("resume", ["task"]):
        _hint()
    assert "Effort is derived" in capsys.readouterr().err


@pytest.mark.parametrize("shape", [[], {}, True, 42], ids=["list", "object", "boolean", "number"])
def test_malformed_wire_shape_does_not_block_launch(
    shape: object,
    proxy_info: dict[str, Any],
    hint_probe: Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proxy_info["wire_shape"] = shape
    with _context("resume", ["task"]):
        _hint()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    hint_probe.assert_called_once()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("wire_shape", "anthropic_passthrough"),
        ("wire_shape", "unknown"),
        ("wire_shape", None),
        ("is_proxy", False),
        ("template", "another-template"),
        ("proxy", {"proxy_id": "other-proxy"}),
        ("proxy", None),
    ],
)
def test_unconfirmed_and_passthrough_routes_stay_silent(
    key: str,
    value: object,
    proxy_info: dict[str, Any],
    hint_probe: Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proxy_info[key] = value
    with _context("resume", ["task"]):
        _hint()
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    "params",
    [{"effort": "high"}, {"no_launch": True}, {"json_output": True}, {"json": True}],
)
def test_excluded_launch_modes_do_not_probe(
    params: dict[str, object], hint_probe: Mock, capsys: pytest.CaptureFixture[str]
) -> None:
    with _context("start", ["task"]) as ctx:
        ctx.params.update(params)
        _hint()
    hint_probe.assert_not_called()
    assert capsys.readouterr().err == ""


def test_direct_and_bare_launches_do_not_probe(hint_probe: Mock, capsys: pytest.CaptureFixture[str]) -> None:
    with _context("start", ["task"]):
        _hint(base_url=None)
    with click.Context(click.Command("start"), parent=click.Context(click.Group("claude"))):
        _hint()
    _hint()
    hint_probe.assert_not_called()
    assert capsys.readouterr().err == ""


def test_failed_probe_does_not_block_launch(hint_probe: Mock, capsys: pytest.CaptureFixture[str]) -> None:
    hint_probe.side_effect = httpx.ConnectError("offline")
    with _context("resume", ["task"]):
        _hint()
    assert capsys.readouterr().err == ""


def test_unpinned_launch_names_reported_floors_without_claiming_default_tier(
    hint_probe: Mock, capsys: pytest.CaptureFixture[str]
) -> None:
    with _context("resume", ["task"]):
        print_derived_effort_hint(base_url=BASE_URL, template="openrouter-openai", proxy_id="test-proxy")
    assert "configured minimums: opus: high" in capsys.readouterr().err


def test_multiline_prompt_keeps_one_line_hint(hint_probe: Mock, capsys: pytest.CaptureFixture[str]) -> None:
    with _context("start", ["task", "--system-prompt", "first 'quoted' line\nsecond line"]):
        _hint()
    rendered = capsys.readouterr().err
    assert len(rendered.splitlines()) == 1
    assert "$'first \\'quoted\\' line\\nsecond line'" in rendered


@pytest.mark.parametrize("verb", ["start", "incognito", "resume", "fork"])
def test_each_presenter_emits_hint_at_launch_boundary(
    verb: str, hint_probe: Mock, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    presenter: _ClaudeStartCliPresenter | _ClaudeResumeCliPresenter | _ClaudeForkCliPresenter
    with _context(verb, ["task"]):
        if verb in {"start", "incognito"}:
            presenter = _ClaudeStartCliPresenter(session_name="task", projected_tier="opus")
            presenter.on_created(
                ClaudeStartCreated(
                    "task",
                    verb == "incognito",
                    "test-proxy",
                    "openrouter-openai",
                    BASE_URL,
                    None,
                    None,
                    None,
                )
            )
        elif verb == "resume":
            presenter = _ClaudeResumeCliPresenter(projected_tier="opus")
            presenter.on_resume_prepared(
                ResumePrepared(
                    "task",
                    ClaudeResumeAction.RECONNECT,
                    None,
                    None,
                    "openrouter-openai",
                    BASE_URL,
                    tmp_path,
                    None,
                    False,
                    None,
                    (),
                )
            )
        else:
            presenter = _ClaudeForkCliPresenter(
                session_name="task",
                base_url=BASE_URL,
                template="openrouter-openai",
                proxy_id="test-proxy",
                projected_tier="opus",
            )
        capsys.readouterr()
        presenter.before_launch(tmp_path)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("Effort is derived") == 1
    hint_probe.assert_called_once()
