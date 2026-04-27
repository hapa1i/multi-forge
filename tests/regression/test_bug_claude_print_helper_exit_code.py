"""Regression test for preserving non-zero exit codes in run_claude_print()."""

from __future__ import annotations

import subprocess
from typing import cast

import pytest

from tests.fixtures.docker import ContainerLike
from tests.integration.docker.conftest import run_claude_print

pytestmark = pytest.mark.regression


class _FakeWorkspace:
    """Minimal fake workspace for testing run_claude_print."""

    def __init__(self) -> None:
        self.commands: list[str] = []

    def exec(self, command: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        del timeout
        self.commands.append(command)

        if len(self.commands) in (1, 2, 4):
            return subprocess.CompletedProcess(args=["bash", "-c", command], returncode=0, stdout="", stderr="")

        if "|| true" in command:
            return subprocess.CompletedProcess(
                args=["bash", "-c", command],
                returncode=0,
                stdout="masked failure",
                stderr="",
            )

        return subprocess.CompletedProcess(
            args=["bash", "-c", command],
            returncode=42,
            stdout="",
            stderr="claude failed",
        )


def test_run_claude_print_preserves_nonzero_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper must not hide Claude failures behind ``|| true``."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    workspace = _FakeWorkspace()

    exit_code, stdout, stderr = run_claude_print(
        cast(ContainerLike, workspace),
        "Say hello",
        session_name="helper-test",
        timeout=5,
    )

    assert exit_code == 42
    assert stdout == ""
    assert stderr == "claude failed"
    assert "|| true" not in workspace.commands[2]
    assert workspace.commands[-1] == "rm -f /tmp/.anthropic_key"
