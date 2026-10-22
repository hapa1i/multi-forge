"""Regression coverage for the top-level setup script."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SETUP_SCRIPT = Path(__file__).parents[3] / "scripts" / "setup.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_uninstall_disables_all_extensions_noninteractively(tmp_path: Path) -> None:
    """setup.sh must use disable's --yes confirmation bypass, not removed --force."""
    home = tmp_path / "home"
    forge_home = home / ".forge-test"
    forge_bin = forge_home / "bin"
    fake_bin = tmp_path / "bin"
    invocation_log = tmp_path / "forge-invocations"
    forge_bin.mkdir(parents=True)
    fake_bin.mkdir()
    (forge_home / ".forge-home").write_text("managed-by-setup-sh\n", encoding="utf-8")

    _write_executable(
        forge_bin / "forge",
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$FORGE_INVOCATIONS"\n',
    )
    for command in ("python3", "pip3", "pip", "docker"):
        _write_executable(fake_bin / command, "#!/bin/sh\nexit 1\n")
    _write_executable(fake_bin / "uv", "#!/bin/sh\nexit 0\n")

    env = {
        **os.environ,
        "HOME": str(home),
        "FORGE_HOME": str(forge_home),
        "FORGE_INVOCATIONS": str(invocation_log),
        "PATH": os.pathsep.join((str(fake_bin), "/usr/bin", "/bin")),
    }
    result = subprocess.run(
        ["/bin/bash", str(SETUP_SCRIPT), "--uninstall", "--yes"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert invocation_log.read_text(encoding="utf-8").splitlines() == [
        "info",
        "extension disable --all --yes",
    ]


def test_uninstall_preserves_forge_home_when_extension_teardown_fails(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    forge_home = home / ".forge-test"
    forge_bin = forge_home / "bin"
    fake_bin = tmp_path / "bin"
    tracking = forge_home / "installed.json"
    package_log = tmp_path / "package-invocations"
    forge_bin.mkdir(parents=True)
    fake_bin.mkdir()
    (forge_home / ".forge-home").write_text("managed-by-setup-sh\n", encoding="utf-8")
    tracking.write_text('{"tracked": true}\n', encoding="utf-8")

    _write_executable(
        forge_bin / "forge",
        "#!/bin/sh\n"
        'if [ "$1" = "extension" ]; then\n'
        '  printf "%s\\n" "unsafe package root" >&2\n'
        "  exit 1\n"
        "fi\n",
    )
    for command in ("python3", "pip3", "pip", "docker"):
        _write_executable(fake_bin / command, "#!/bin/sh\nexit 1\n")
    _write_executable(
        fake_bin / "uv",
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{package_log}"\nexit 0\n',
    )

    env = {
        **os.environ,
        "HOME": str(home),
        "FORGE_HOME": str(forge_home),
        "PATH": os.pathsep.join((str(fake_bin), "/usr/bin", "/bin")),
    }
    result = subprocess.run(
        ["/bin/bash", str(SETUP_SCRIPT), "--uninstall", "--yes"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "unsafe package root" in result.stderr
    assert "Could not disable every tracked Forge extension" in result.stderr
    assert forge_home.is_dir()
    assert tracking.read_text(encoding="utf-8") == '{"tracked": true}\n'
    assert not package_log.exists()


def test_uninstall_preserves_tracking_when_forge_command_is_missing(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    forge_home = home / ".forge-test"
    fake_bin = tmp_path / "bin"
    tracking = forge_home / "installed.json"
    package_log = tmp_path / "package-invocations"
    forge_home.mkdir(parents=True)
    fake_bin.mkdir()
    (forge_home / ".forge-home").write_text("managed-by-setup-sh\n", encoding="utf-8")
    tracking.write_text('{"tracked": true}\n', encoding="utf-8")

    for command in ("python3", "pip3", "pip", "docker"):
        _write_executable(fake_bin / command, "#!/bin/sh\nexit 1\n")
    _write_executable(
        fake_bin / "uv",
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{package_log}"\nexit 0\n',
    )

    env = {
        **os.environ,
        "HOME": str(home),
        "FORGE_HOME": str(forge_home),
        "PATH": os.pathsep.join((str(fake_bin), "/usr/bin", "/bin")),
    }
    result = subprocess.run(
        ["/bin/bash", str(SETUP_SCRIPT), "--uninstall", "--yes"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Forge command not found" in result.stderr
    assert "installed.json still tracks extensions" in result.stderr
    assert forge_home.is_dir()
    assert tracking.read_text(encoding="utf-8") == '{"tracked": true}\n'
    assert not package_log.exists()


@pytest.fixture
def local_install_environment(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "local checkout"
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    repo.mkdir()
    home.mkdir()
    fake_bin.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nname = "multi-forge"\n', encoding="utf-8")
    requirements = repo / "requirements"
    requirements.mkdir()
    for name in ("runtime.txt", "build.txt"):
        (requirements / name).write_text("example==1.0\n", encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "check-dependency-pins.py").write_text("# fixture checker\n", encoding="utf-8")
    _write_executable(
        fake_bin / "python3",
        """#!/bin/sh
case "$1" in
    -c) printf '3.11\n' ;;
    -S)
        printf '%s\n' "$@" > "$PIN_CHECK_LOG"
        if [ "$PIN_CHECK_FAILURE" = 1 ]; then
            printf 'Stale dependency constraints: requirements/runtime.txt\n' >&2
            exit 1
        fi
        ;;
    *) exit 1 ;;
esac
""",
    )
    for command in ("pip3", "pip", "docker", "git", "forge"):
        _write_executable(fake_bin / command, "#!/bin/sh\nexit 1\n")
    _write_executable(
        fake_bin / "uv",
        """#!/bin/sh
printf '<call>\n' >> "$UV_LOG"
printf '%s\n' "$@" >> "$UV_LOG"
if [ "$1 $2" = 'tool install' ]; then
    touch "$TOOL_INSTALLED"
elif [ "$1 $2" = 'tool list' ] && [ -f "$TOOL_INSTALLED" ]; then
    printf 'multi-forge v1.2.3\n'
fi
""",
    )
    return repo, {
        **os.environ,
        "HOME": str(home),
        "FORGE_HOME": str(home / ".forge-test"),
        "PATH": os.pathsep.join((str(fake_bin), "/usr/bin", "/bin")),
        "UV_LOG": str(tmp_path / "uv.log"),
        "TOOL_INSTALLED": str(tmp_path / "installed"),
        "PIN_CHECK_LOG": str(tmp_path / "pin-check.log"),
        "PIN_CHECK_FAILURE": "",
    }


def _install_local(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(SETUP_SCRIPT), "--local", "--no-modify-path"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


def test_local_install_constrains_runtime_and_build_dependencies(
    local_install_environment: tuple[Path, dict[str, str]],
) -> None:
    repo, env = local_install_environment

    result = _install_local(repo, env)

    assert result.returncode == 0, result.stdout + result.stderr
    uv_calls = Path(env["UV_LOG"]).read_text(encoding="utf-8").split("<call>\n")
    install_calls = [call.splitlines() for call in uv_calls if call.startswith("tool\ninstall\n")]
    assert install_calls == [
        [
            "tool",
            "install",
            "-e",
            "--force",
            "--constraints",
            str(repo / "requirements" / "runtime.txt"),
            "--build-constraints",
            str(repo / "requirements" / "build.txt"),
            ".",
        ]
    ]
    assert (Path(env["FORGE_HOME"]) / "repo").resolve() == repo
    assert Path(env["PIN_CHECK_LOG"]).read_text(encoding="utf-8").splitlines() == [
        "-S",
        str(repo / "scripts" / "check-dependency-pins.py"),
    ]


@pytest.mark.parametrize("missing", ["runtime.txt", "build.txt"])
@pytest.mark.parametrize("empty", [False, True])
def test_local_install_requires_constraints_before_removing_existing_installation(
    local_install_environment: tuple[Path, dict[str, str]], missing: str, empty: bool
) -> None:
    repo, env = local_install_environment
    constraints = repo / "requirements" / missing
    if empty:
        constraints.write_text("", encoding="utf-8")
    else:
        constraints.unlink()
    wrapper = Path(env["FORGE_HOME"]) / "bin" / "forge"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("existing installation", encoding="utf-8")
    Path(env["TOOL_INSTALLED"]).touch()

    result = _install_local(repo, env)

    assert result.returncode != 0
    assert "Reviewed dependency constraints are missing" in result.stderr
    assert "requirements/runtime.txt and requirements/build.txt" in result.stderr
    assert wrapper.read_text(encoding="utf-8") == "existing installation"
    assert Path(env["UV_LOG"]).read_text(encoding="utf-8").splitlines() == [
        "<call>",
        "--version",
    ]


@pytest.mark.parametrize("missing_checker", [False, True])
def test_local_install_verifies_pins_before_removing_existing_installation(
    local_install_environment: tuple[Path, dict[str, str]], missing_checker: bool
) -> None:
    repo, env = local_install_environment
    if missing_checker:
        (repo / "scripts" / "check-dependency-pins.py").unlink()
    else:
        env["PIN_CHECK_FAILURE"] = "1"
    wrapper = Path(env["FORGE_HOME"]) / "bin" / "forge"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("existing installation", encoding="utf-8")
    Path(env["TOOL_INSTALLED"]).touch()

    result = _install_local(repo, env)

    assert result.returncode != 0
    assert "Dependency pin" in result.stderr
    assert wrapper.read_text(encoding="utf-8") == "existing installation"
    assert Path(env["UV_LOG"]).read_text(encoding="utf-8").splitlines() == [
        "<call>",
        "--version",
    ]
