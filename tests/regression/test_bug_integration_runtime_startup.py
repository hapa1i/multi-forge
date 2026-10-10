"""A broken cached CLI must fail preflight before unrelated integration tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.fixtures import docker, runtime_image

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("returncode", [0, 127, 135])
def test_runtime_probe_preserves_failure_and_cleans_its_container(monkeypatch, returncode):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[1] == "rm":
            return subprocess.CompletedProcess(argv, 0)
        return subprocess.CompletedProcess(argv, returncode, "Claude Code: ", "Bun bus error" if returncode else "")

    monkeypatch.setattr(runtime_image.subprocess, "run", run)
    if returncode:
        with pytest.raises(RuntimeError, match=f"image fixture-image .*exit {returncode}") as error:
            runtime_image.check_runtime_image("fixture-image")
        assert "Bun bus error" in str(error.value)
        assert "docker build --no-cache" in str(error.value)
    else:
        assert runtime_image.check_runtime_image("fixture-image") == "Claude Code:"
    argv, kwargs = calls[0]
    assert argv[argv.index("--network") + 1] == "none"
    assert "-e" not in argv and "--env-file" not in argv and "-v" not in argv
    assert "claude --version" in argv[-1] and "codex --version" in argv[-1]
    assert kwargs["timeout"] == 45
    assert calls[1][0] == ["docker", "rm", "-f", argv[argv.index("--name") + 1]]
    assert calls[1][1]["timeout"] == 10


def test_docker_client_timeout_still_removes_the_owned_container(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[1] == "run":
            raise subprocess.TimeoutExpired(argv, 45)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(runtime_image.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="timed out"):
        runtime_image.check_runtime_image("fixture-image")
    assert calls[1] == ["docker", "rm", "-f", calls[0][4]]


@pytest.mark.parametrize("cached", [True, False])
def test_pytest_image_fixture_rejects_broken_runtime_before_yield(monkeypatch, tmp_path, cached):
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker/Dockerfile.forge").touch()
    monkeypatch.setattr(docker, "_find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(docker, "_get_forge_revision", lambda root: "same-revision")
    monkeypatch.setattr(docker, "_image_exists", lambda image: cached)
    monkeypatch.setattr(docker, "_get_image_revision", lambda image: "same-revision")
    monkeypatch.setattr(docker.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 0))

    def broken(image):
        raise RuntimeError("cached Claude exits 135")

    monkeypatch.setattr(docker, "check_runtime_image", broken)
    with pytest.raises(pytest.fail.Exception, match="cached Claude exits 135"):
        docker.forge_test_image.__wrapped__(True, False)


@pytest.mark.parametrize("cached_revision", ["exact-dirty-fingerprint", "older-dirty-fingerprint"])
def test_shell_runner_stops_before_sidecar_or_pytest(tmp_path, cached_revision):
    root = Path(__file__).resolve().parents[2]
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker/Dockerfile.forge").touch()
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "calls"
    scripts = {
        "claude": "printf '2.1.294 (Claude Code)\\n'",
        "codex": "printf 'codex-cli 0.162.1\\n'",
        "git": "exit 1",
        "docker": 'printf "docker %s\\n" "$*" >> "$CALL_LOG"; if [ "$1" = image ]; then echo "$CACHED_REVISION"; fi',
        "uv": (
            'printf "uv %s\\n" "$*" >> "$CALL_LOG"; '
            'if [ "$3" = -c ]; then echo exact-dirty-fingerprint; exit 0; fi; '
            'echo "Runtime startup failed: exit 135" >&2; exit 1'
        ),
    }
    for name, body in scripts.items():
        path = binary / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o700)
    result = subprocess.run(
        ["/bin/bash", str(root / "scripts/test-integration.sh")],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{binary}:/usr/bin:/bin",
            "CALL_LOG": str(log),
            "CACHED_REVISION": cached_revision,
            "PYTHON_DOTENV_DISABLED": "1",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "no tests were run" in result.stderr
    calls = log.read_text()
    assert "uv run python tests/fixtures/runtime_image.py forge-claude-test:2.1.294-codex-0.162.1" in calls
    assert "_get_forge_revision(Path.cwd())" in calls
    assert ("docker build" in calls) is (cached_revision != "exact-dirty-fingerprint")
    assert "Dockerfile.sidecar" not in calls and "uv run pytest" not in calls
