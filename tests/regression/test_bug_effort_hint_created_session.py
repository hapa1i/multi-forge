"""Effort guidance must resume the created child and reuse the cost probe."""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest

from forge.cli.session_effort_hint import print_derived_effort_hint
from forge.core.ops import claude_session as ops
from forge.core.ops.claude_session import ClaudeLaunchReady
from forge.session import IndexStore, create_session_state
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("operation", ["start", "fork", "resume"])
def test_actual_child_recovery_reuses_one_normalized_cost_probe(
    operation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    state = create_session_state("created-child", worktree_path=str(tmp_path))
    state.forge_root = str(tmp_path)
    publish_session(IndexStore(), state, tmp_path)
    reads: list[str] = []
    order: list[str] = []

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def read(self, _limit: int) -> bytes:
            return json.dumps(
                {
                    "is_proxy": True,
                    "template": "openrouter-openai",
                    "proxy": {"proxy_id": "test-proxy"},
                    "wire_shape": "openai_translated",
                    "metrics": {"costs": {"total_usd": 1}},
                }
            ).encode()

    def read_snapshot(url: str, *, timeout: float) -> Response:
        reads.append(url)
        order.append("cost_probe")
        assert timeout == 0.5
        return Response()

    def render(event: ClaudeLaunchReady) -> None:
        order.append("hint")
        assert event.session == state.name
        assert event.operation == operation
        print_derived_effort_hint(event)

    def invoke(**_kwargs: object) -> int:
        order.append("child")
        return 0

    monkeypatch.setattr("forge.session.launch_confirmation.urlopen", read_snapshot)
    monkeypatch.setattr(ops, "build_claude_routing_payload", lambda *_a, **_k: {})
    monkeypatch.setattr(ops, "commit_launch_routing", lambda **_k: order.append("commit"))
    ctx = click.Context(click.Command(operation), parent=click.Context(click.Group("session")))
    ctx.params = {"name": "parent-or-requested-name", "fresh": operation == "resume"}
    with ctx:
        result = ops.launch_claude_session(
            manifest=state,
            session_id=None,
            resume_id=None,
            effective_template="openrouter-openai",
            runtime_base_url="http://127.0.0.1:65530/v1/messages",
            proxy_id="test-proxy",
            context_limit=200_000,
            use_sidecar=False,
            authority_operation=operation,
            on_launch_ready=render,
            invoke=invoke,
            run_active=lambda runner, **_kwargs: runner(),
        )
    assert result.exit_code == 0
    assert reads == ["http://127.0.0.1:65530/"]
    assert order == ["cost_probe", "hint", "commit", "child"]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines()[-1] == "  forge session resume created-child --effort '<level>'"
    assert "parent-or-requested-name" not in captured.err
