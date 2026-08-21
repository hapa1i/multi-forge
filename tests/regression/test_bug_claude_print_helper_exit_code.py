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
        self.writes: list[tuple[str, str, int]] = []

    def write_file(
        self,
        path: str,
        content: str,
        timeout: int = 30,
        *,
        mode: int = 0o644,
    ) -> subprocess.CompletedProcess[str]:
        del timeout
        self.writes.append((path, content, mode))
        return subprocess.CompletedProcess(args=["write-file", path], returncode=0, stdout="", stderr="")

    def exec(self, command: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
        del timeout
        self.commands.append(command)

        if command == "rm -f /tmp/.anthropic_key /tmp/.forge_prompt":
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
    assert workspace.writes == [
        ("/tmp/.anthropic_key", "test-key", 0o600),
        ("/tmp/.forge_prompt", "Say hello", 0o600),
    ]
    assert "|| true" not in workspace.commands[0]
    assert workspace.commands[-1] == "rm -f /tmp/.anthropic_key /tmp/.forge_prompt"
