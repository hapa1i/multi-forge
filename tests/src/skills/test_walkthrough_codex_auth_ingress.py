"""Contracts for explicit Codex auth ingress into the walkthrough sandbox."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SETUP = REPO_ROOT / "src/skills/walkthrough/scripts/setup-test-repo.sh"


def _env(home: Path, target: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(target)
    env.pop("CODEX_API_KEY", None)
    env.pop("CODEX_ACCESS_TOKEN", None)
    return env


def _run(env: dict[str, str], *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SETUP), *(str(arg) for arg in args)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_explicit_auth_is_copied_with_private_modes_and_no_source_disclosure(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"
    source = tmp_path / "private-source.json"
    source.write_text('{"secret":"not-for-output"}\n')

    result = _run(_env(home, target), "--codex-auth", source)

    assert result.returncode == 0, result.stderr
    destination = target / ".codex-user/auth.json"
    assert destination.read_bytes() == source.read_bytes()
    assert stat.S_IMODE((target / ".codex-user").stat().st_mode) == 0o700
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    env_text = (target / ".forge/walkthrough/env.sh").read_text()
    assert "export FORGE_WALKTHROUGH_CODEX_AUTH_MODE=explicit-file" in env_text
    assert "unset CODEX_API_KEY" in env_text
    assert "unset CODEX_ACCESS_TOKEN" in env_text
    generated = result.stdout + result.stderr + env_text
    assert str(source) not in generated
    assert "not-for-output" not in generated


def test_reset_does_not_reuse_a_previous_explicit_auth_copy(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"
    source = tmp_path / "auth.json"
    source.write_text('{"tokens":[]}\n')
    env = _env(home, target)
    assert _run(env, "--codex-auth", source).returncode == 0
    assert (target / ".codex-user/auth.json").exists()

    refused = _run(env)
    assert refused.returncode == 1
    assert "Use --reset" in refused.stderr
    assert (target / ".codex-user/auth.json").exists()

    result = _run(env, "--reset")

    assert result.returncode == 0, result.stderr
    assert not (target / ".codex-user/auth.json").exists()
    assert "export FORGE_WALKTHROUGH_CODEX_AUTH_MODE=none" in (
        target / ".forge/walkthrough/env.sh"
    ).read_text()


def test_environment_ingress_records_mode_without_copying_auth(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"
    env = _env(home, target)
    env["CODEX_API_KEY"] = "never-print-this"

    result = _run(env)

    assert result.returncode == 0, result.stderr
    assert not (target / ".codex-user/auth.json").exists()
    env_text = (target / ".forge/walkthrough/env.sh").read_text()
    assert "export FORGE_WALKTHROUGH_CODEX_AUTH_MODE=environment" in env_text
    assert "never-print-this" not in result.stdout + result.stderr + env_text


def test_invalid_arguments_fail_before_creating_the_target(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"

    result = _run(_env(home, target), "--unknown")

    assert result.returncode == 2
    assert "Unknown argument" in result.stderr
    assert not target.exists()
