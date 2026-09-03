"""Regression O036: walkthrough provenance must precede target-controlled code.

Root cause: ``run-in-repo.sh`` used ``abspath`` for its denylist and sourced the
target's ``env.sh`` before checking the provenance marker and required structure.

Affected: src/skills/walkthrough/scripts/run-in-repo.sh
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNNER = _REPO_ROOT / "src" / "skills" / "walkthrough" / "scripts" / "run-in-repo.sh"
_SETUP = _REPO_ROOT / "src" / "skills" / "walkthrough" / "scripts" / "setup-test-repo.sh"


def _environment(home: Path, target: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(target)
    return env


def _write_env(target: Path, *, exported_target: Path, sentinel: Path | None = None) -> None:
    env_file = target / ".forge" / "walkthrough" / "env.sh"
    env_file.parent.mkdir(parents=True)
    lines = []
    if sentinel is not None:
        lines.append(f"printf 'sourced\\n' > {shlex.quote(str(sentinel))}")
    lines.extend(
        [
            f"export FORGE_TEST_REPO={shlex.quote(str(exported_target))}",
            f"export FORGE_HOME={shlex.quote(str(exported_target / '.forge-home'))}",
            f"export CLAUDE_HOME={shlex.quote(str(exported_target / '.claude-user'))}",
            f"export CODEX_HOME={shlex.quote(str(exported_target / '.codex-user'))}",
        ]
    )
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(target: Path, home: Path, *command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_RUNNER), *command],
        capture_output=True,
        text=True,
        env=_environment(home, target),
    )


def test_missing_marker_rejects_target_before_sourcing_env(tmp_path: Path) -> None:
    """An unmarked target must not execute its env file while reporting rejection."""
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "unmarked"
    target.mkdir()
    (target / "CLAUDE.md").write_text("# forged target\n", encoding="utf-8")
    sentinel = tmp_path / "env-sourced"
    _write_env(target, exported_target=target, sentinel=sentinel)

    result = _run(target, home, "true")

    assert result.returncode == 1
    assert "Canonical marker file missing" in result.stderr
    assert not sentinel.exists()


def test_reset_refuses_unmarked_directory_without_removing_content(
    tmp_path: Path,
) -> None:
    """Reset must not treat an arbitrary unmarked directory as walkthrough-owned."""
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "unmarked"
    target.mkdir()
    sentinel = target / "user-owned.txt"
    sentinel.write_text("preserve me\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(_SETUP), "--reset"],
        capture_output=True,
        text=True,
        env=_environment(home, target),
    )

    assert result.returncode == 1
    assert "ownership cannot be proven" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "preserve me\n"


def test_incomplete_structure_rejects_target_before_sourcing_env(
    tmp_path: Path,
) -> None:
    """A marked but incomplete target must not execute its env file."""
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "incomplete"
    target.mkdir()
    (target / ".forge-walkthrough-marker").write_text("forge-walkthrough-marker\n", encoding="utf-8")
    sentinel = tmp_path / "env-sourced"
    _write_env(target, exported_target=target, sentinel=sentinel)

    result = _run(target, home, "true")

    assert result.returncode == 1
    assert "Expected file missing" in result.stderr
    assert not sentinel.exists()


def test_symlink_alias_to_denylisted_home_is_rejected(tmp_path: Path) -> None:
    """Canonical path checks must reject a symlink alias to HOME."""
    home = tmp_path / "home"
    home.mkdir()
    alias = tmp_path / "walkthrough-alias"
    alias.symlink_to(home, target_is_directory=True)
    (home / ".forge-walkthrough-marker").write_text("forge-walkthrough-marker\n", encoding="utf-8")
    (home / "CLAUDE.md").write_text("# forged home\n", encoding="utf-8")
    _write_env(home, exported_target=alias)
    command_sentinel = tmp_path / "command-ran"

    result = _run(alias, home, "touch", str(command_sentinel))

    assert result.returncode == 1
    assert "denylisted path" in result.stderr
    assert not command_sentinel.exists()


def test_env_cannot_replace_validated_target_with_denylisted_home(
    tmp_path: Path,
) -> None:
    """A marked target's env file cannot redirect later gates and command execution."""
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "marked-target"
    target.mkdir()
    (target / ".forge-walkthrough-marker").write_text("forge-walkthrough-marker\n", encoding="utf-8")
    (target / "CLAUDE.md").write_text("# walkthrough target\n", encoding="utf-8")
    _write_env(target, exported_target=home)
    command_sentinel = tmp_path / "command-ran"

    result = _run(target, home, "touch", str(command_sentinel))

    assert result.returncode == 1
    assert "env.sh changed FORGE_TEST_REPO after validation" in result.stderr
    assert str(target.resolve()) in result.stderr
    assert str(home.resolve()) in result.stderr
    assert not command_sentinel.exists()


def test_nested_sandbox_home_symlink_is_rejected_before_reuse_mutation(
    tmp_path: Path,
) -> None:
    """A lexical sandbox child must not redirect Forge writes through a symlink."""
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough-repo"
    env = _environment(home, target)
    created = subprocess.run(["bash", str(_SETUP)], capture_output=True, text=True, env=env)
    assert created.returncode == 0, created.stderr

    external = tmp_path / "external-forge-home"
    log = external / "logs/keep.log"
    log.parent.mkdir(parents=True)
    log.write_text("preserve\n", encoding="utf-8")
    shutil.rmtree(target / ".forge-home")
    (target / ".forge-home").symlink_to(external, target_is_directory=True)

    wrapper = _run(target, home, "true")
    reuse = subprocess.run(["bash", str(_SETUP)], capture_output=True, text=True, env=env)

    assert wrapper.returncode == 1
    assert "FORGE_HOME is not redirected" in wrapper.stderr
    assert reuse.returncode == 1
    assert log.read_text(encoding="utf-8") == "preserve\n"


def test_safe_symlink_alias_remains_compatible(tmp_path: Path) -> None:
    """Equivalent canonical roots pass even when env.sh retains a safe alias."""
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough-repo"
    target.mkdir()
    (target / ".forge-walkthrough-marker").write_text("forge-walkthrough-marker\n", encoding="utf-8")
    (target / "CLAUDE.md").write_text("# walkthrough target\n", encoding="utf-8")
    alias = tmp_path / "walkthrough-alias"
    alias.symlink_to(target, target_is_directory=True)
    for directory in (".forge-home", ".claude-user", ".codex-user"):
        (target / directory).mkdir()
    _write_env(target, exported_target=alias)

    result = _run(alias, home, "pwd")

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).resolve() == target.resolve()


def test_generated_env_quotes_command_substitution_in_target_path(
    tmp_path: Path,
) -> None:
    """A valid but hostile path spelling must remain inert when env.sh is sourced."""
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough-$(touch${IFS}INJECTED)"
    env = _environment(home, target)

    created = subprocess.run(
        ["bash", str(_SETUP)],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert created.returncode == 0, created.stderr

    result = subprocess.run(
        ["bash", str(_RUNNER), "pwd"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).resolve() == target.resolve()
    assert not (tmp_path / "INJECTED").exists()


def test_generated_walkthrough_repo_still_exports_isolated_homes(
    tmp_path: Path,
) -> None:
    """The setup-generated repo remains runnable through the hardened wrapper."""
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough-repo"
    env = _environment(home, target)
    setup = subprocess.run(["bash", str(_SETUP)], capture_output=True, text=True, env=env)
    assert setup.returncode == 0, setup.stderr

    result = _run(
        target,
        home,
        "bash",
        "-c",
        'printf "%s\\n" "$PWD" "$FORGE_HOME" "$CLAUDE_HOME" "$CODEX_HOME" "$FORGE_DEBUG"',
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        str(target),
        str(target / ".forge-home"),
        str(target / ".claude-user"),
        str(target / ".codex-user"),
        "1",
    ]
