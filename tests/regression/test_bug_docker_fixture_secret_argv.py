"""Regression: Docker fixture file contents must not transit process arguments."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from tests.fixtures.docker import DockerContainer

pytestmark = pytest.mark.regression


def test_write_file_streams_secret_on_stdin_with_private_mode() -> None:
    secret = "credential-value-that-must-not-enter-argv"
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    with patch("tests.fixtures.docker.subprocess.run", return_value=completed) as run:
        result = DockerContainer("container-id", "test-image").write_file(
            "/tmp/private-key",
            secret,
            mode=0o600,
        )

    assert result is completed
    argv = run.call_args.args[0]
    assert argv[:3] == ["docker", "exec", "-i"]
    assert secret not in "\0".join(argv)
    assert argv[-2:] == ["/tmp/private-key", "0600"]
    assert run.call_args.kwargs["input"] == secret
