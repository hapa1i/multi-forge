"""Alternate runtime controls cannot override a managed launch's ownership."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    ("runtime", "tail"),
    [
        ("claude", ["--worktree", "other"]),
        ("claude", ["-wother"]),
        ("codex", ["--yolo"]),
        ("codex", ["--worktree"]),
        ("codex", ["--oss"]),
        ("codex", ["--local-provider=ollama"]),
        ("codex", ["--remote", "ws://localhost:9876"]),
        ("codex", ["--remote-auth-token-env", "REMOTE_TOKEN"]),
        ("codex", ["--ephemeral"]),
    ],
)
def test_reserved_control_refused_before_session_or_runtime_creation(
    runtime: str, tail: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    (project / ".forge").mkdir(parents=True)
    monkeypatch.chdir(project)
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    with (
        patch("forge.cli.guards.require_repo_root"),
        patch("forge.cli.session_lifecycle.launch_new_session", return_value=0) as claude_launch,
        patch(
            "forge.core.ops.codex_interactive.assert_codex_ready",
            side_effect=AssertionError("refusal must precede Codex preflight"),
        ) as codex_preflight,
    ):
        result = CliRunner().invoke(main, ["session", "start", "child", "--runtime", runtime, "--", *tail])

    assert result.exit_code == 1, result.output
    assert "is managed by Forge" in result.stderr
    claude_launch.assert_not_called()
    codex_preflight.assert_not_called()
    assert not (project / ".forge" / "sessions" / "child").exists()
