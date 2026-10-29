"""setup-version: never replace a failed source pin with the default branch.

scripts/setup.sh used an unpinned clone after a requested clone failed and ignored
pull failures when updating an existing checkout.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

SETUP_SCRIPT = Path(__file__).parents[2] / "scripts" / "setup.sh"


@pytest.fixture
def installer_environment(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    home.mkdir()
    fake_bin.mkdir()
    commands = {
        "python3": """#!/bin/sh
case "$1" in
    -c) printf '3.11\n' ;;
    -S)
        printf '%s\n' "$@" > "$PIN_CHECK_LOG"
        if [ -n "$MOVE_FETCH_HEAD_TO" ]; then
            printf '%s\n' "$MOVE_FETCH_HEAD_TO" > "$FORGE_HOME/repo/.git/FETCH_HEAD"
        fi
        if [ "$PIN_CHECK_FAILURE" = 1 ]; then
            printf 'Stale dependency constraints: requirements/runtime.txt\n' >&2
            exit 1
        fi
        ;;
    *) exit 1 ;;
esac
""",
        "pip3": "#!/bin/sh\nexit 1\n",
        "pip": "#!/bin/sh\nexit 1\n",
        "docker": "#!/bin/sh\nexit 1\n",
        "uv": '#!/bin/sh\nprintf "%s\\n" "$*" >> "$UV_LOG"\n',
        "git": """#!/bin/sh
printf '%s\n' "$*" >> "$GIT_LOG"
if [ -n "$REAL_GIT" ]; then
    exec "$REAL_GIT" "$@"
fi
if [ "$1" = "$GIT_FAILURE" ]; then
    printf 'synthetic git failure\n' >&2
    exit 1
fi
write_candidate() {
    mkdir -p "$1"
    if [ "$MISSING_BUILD_CONSTRAINTS" != 1 ]; then
        mkdir -p "$1/requirements" "$1/scripts"
        printf 'hatchling==1.27.0\n' > "$1/requirements/build.txt"
        printf '# fixture checker\n' > "$1/scripts/check-dependency-pins.py"
    fi
}
case "$1" in
    clone)
        case "$*" in
            *'--branch '* )
                if [ "$GIT_FAILURE" = "pinned-clone" ]; then
                    printf 'requested ref unavailable\n' >&2
                    exit 1
                fi
                ;;
        esac
        for destination do :; done
        mkdir -p "$destination/.git"
        write_candidate "$destination"
        ;;
    checkout)
        write_candidate .
        ;;
    rev-parse)
        printf '1234567890123456789012345678901234567890\n'
        ;;
    archive)
        for argument do
            case "$argument" in --output=*) archive_output=${argument#--output=} ;; esac
        done
        fixture_dir="${archive_output%/source.tar}/fixture"
        write_candidate "$fixture_dir"
        tar -cf "$archive_output" -C "$fixture_dir" .
        ;;
    status)
        printf '%s' "$GIT_DIRTY"
        ;;
esac
""",
    }
    for command, content in commands.items():
        executable = fake_bin / command
        executable.write_text(content, encoding="utf-8")
        executable.chmod(0o755)
    return {
        **os.environ,
        "HOME": str(home),
        "FORGE_HOME": str(home / ".forge-test"),
        "FORGE_VERSION": "v1.2.3",
        "PATH": os.pathsep.join((str(fake_bin), "/usr/bin", "/bin")),
        "GIT_LOG": str(tmp_path / "git.log"),
        "UV_LOG": str(tmp_path / "uv.log"),
        "GIT_FAILURE": "",
        "GIT_DIRTY": "",
        "REAL_GIT": "",
        "MISSING_BUILD_CONSTRAINTS": "",
        "PIN_CHECK_LOG": str(tmp_path / "pin-check.log"),
        "PIN_CHECK_FAILURE": "",
        "MOVE_FETCH_HEAD_TO": "",
    }


def _install(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(SETUP_SCRIPT), "--no-modify-path", *args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )


@pytest.mark.parametrize("version_arguments", [(), ("--version", "v1.2.3")])
def test_requested_clone_failure_never_falls_back_to_default_branch(
    installer_environment: dict[str, str], version_arguments: tuple[str, ...]
) -> None:
    env = installer_environment
    env["GIT_FAILURE"] = "pinned-clone"

    result = _install(env, *version_arguments)

    assert result.returncode != 0
    assert "v1.2.3" in result.stderr
    assert "Check the requested branch/tag and repository access" in result.stderr
    git_calls = Path(env["GIT_LOG"]).read_text(encoding="utf-8").splitlines()
    assert len(git_calls) == 1
    assert git_calls[0].startswith("clone --depth 1 --branch v1.2.3 ")
    assert "sync " not in Path(env["UV_LOG"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("failure", ["status", "fetch", "rev-parse", "archive", "checkout"])
def test_update_failure_does_not_install_stale_checkout(installer_environment: dict[str, str], failure: str) -> None:
    env = installer_environment
    env["GIT_FAILURE"] = failure
    repo = Path(env["FORGE_HOME"]) / "repo"
    (repo / ".git").mkdir(parents=True)
    sentinel = repo / "keep.txt"
    sentinel.write_text("existing user content", encoding="utf-8")

    result = _install(env)

    assert result.returncode != 0
    assert "synthetic git failure" in result.stderr
    assert "Could not" in result.stderr
    assert "sync " not in Path(env["UV_LOG"]).read_text(encoding="utf-8")
    assert sentinel.read_text(encoding="utf-8") == "existing user content"
    assert not list(Path(env["FORGE_HOME"]).glob(".install-candidate.*"))


def test_dirty_checkout_refuses_before_fetch(
    installer_environment: dict[str, str],
) -> None:
    env = installer_environment
    env["GIT_DIRTY"] = " M pyproject.toml\n"
    (Path(env["FORGE_HOME"]) / "repo" / ".git").mkdir(parents=True)

    result = _install(env)

    assert result.returncode != 0
    assert "uncommitted changes" in result.stderr
    assert Path(env["GIT_LOG"]).read_text(encoding="utf-8").splitlines() == ["status --porcelain"]
    assert "sync " not in Path(env["UV_LOG"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("version", ["v1.2.3", "main"])
def test_existing_checkout_uses_exact_fetched_ref(installer_environment: dict[str, str], version: str) -> None:
    env = installer_environment
    (Path(env["FORGE_HOME"]) / "repo" / ".git").mkdir(parents=True)

    result = _install(env, "--version", version)

    assert result.returncode == 0, result.stdout + result.stderr
    git_calls = Path(env["GIT_LOG"]).read_text(encoding="utf-8").splitlines()
    assert git_calls[:3] == [
        "status --porcelain",
        f"fetch origin {version}",
        "rev-parse --verify FETCH_HEAD^{commit}",
    ]
    assert git_calls[3].startswith("archive --format=tar --output=")
    assert git_calls[3].endswith("1234567890123456789012345678901234567890")
    assert git_calls[4:] == ["checkout --detach 1234567890123456789012345678901234567890"]
    assert "sync --locked --quiet" in Path(env["UV_LOG"]).read_text(encoding="utf-8").splitlines()
    check_arguments = Path(env["PIN_CHECK_LOG"]).read_text(encoding="utf-8").splitlines()
    assert check_arguments[0] == "-S"
    assert check_arguments[1].startswith(f"{env['FORGE_HOME']}/.install-candidate.")
    assert check_arguments[1].endswith("/source/scripts/check-dependency-pins.py")
    assert not list(Path(env["FORGE_HOME"]).glob(".install-candidate.*"))


@pytest.mark.parametrize("version", ["v1.2.3", "main"])
def test_fresh_install_preserves_requested_branch_or_tag(installer_environment: dict[str, str], version: str) -> None:
    env = installer_environment

    result = _install(env, "--version", version)

    assert result.returncode == 0, result.stdout + result.stderr
    git_calls = Path(env["GIT_LOG"]).read_text(encoding="utf-8").splitlines()
    assert len(git_calls) == 1
    assert git_calls[0].startswith(f"clone --depth 1 --branch {version} ")
    assert "sync --locked --quiet" in Path(env["UV_LOG"]).read_text(encoding="utf-8").splitlines()


def test_existing_non_checkout_directory_is_preserved(
    installer_environment: dict[str, str],
) -> None:
    env = installer_environment
    repo = Path(env["FORGE_HOME"]) / "repo"
    repo.mkdir(parents=True)
    sentinel = repo / "keep.txt"
    sentinel.write_text("existing user content", encoding="utf-8")

    result = _install(env)

    assert result.returncode != 0
    assert "not a Git checkout" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "existing user content"
    assert not Path(env["GIT_LOG"]).exists()
    assert "sync " not in Path(env["UV_LOG"]).read_text(encoding="utf-8")


def test_source_revision_without_build_constraints_refuses_before_package_changes(
    installer_environment: dict[str, str],
) -> None:
    env = installer_environment
    env["MISSING_BUILD_CONSTRAINTS"] = "1"

    result = _install(env)

    assert result.returncode != 0
    assert "Reviewed build constraints are missing" in result.stderr
    assert "requirements/build.txt" in result.stderr
    assert Path(env["UV_LOG"]).read_text(encoding="utf-8").splitlines() == ["--version"]


def test_stale_source_pins_refuse_before_package_changes(
    installer_environment: dict[str, str],
) -> None:
    env = installer_environment
    env["PIN_CHECK_FAILURE"] = "1"
    wrapper = Path(env["FORGE_HOME"]) / "bin" / "forge"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("existing installation", encoding="utf-8")

    result = _install(env)

    assert result.returncode != 0
    assert "Stale dependency constraints" in result.stderr
    assert "Dependency pin verification failed" in result.stderr
    assert wrapper.read_text(encoding="utf-8") == "existing installation"
    assert Path(env["UV_LOG"]).read_text(encoding="utf-8").splitlines() == ["--version"]


@pytest.mark.parametrize("arguments", [("--version",), ("--version", ""), ("--version", "--no-modify-path")])
def test_missing_version_value_refuses_before_install(
    installer_environment: dict[str, str], arguments: tuple[str, ...]
) -> None:
    env = installer_environment

    result = _install(env, *arguments)

    assert result.returncode != 0
    assert "--version requires a branch or tag" in result.stderr
    assert not Path(env["GIT_LOG"]).exists()
    assert not Path(env["UV_LOG"]).exists()


def _git(repo: Path, env: dict[str, str], *args: str) -> str:
    result = subprocess.run(
        ["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],
        env=env,
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    return result.stdout.strip()


@pytest.fixture
def local_git_installation(installer_environment: dict[str, str], tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    env = {
        **installer_environment,
        "REAL_GIT": "/usr/bin/git",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Installer test",
        "GIT_AUTHOR_EMAIL": "installer@example.invalid",
        "GIT_COMMITTER_NAME": "Installer test",
        "GIT_COMMITTER_EMAIL": "installer@example.invalid",
    }
    source = tmp_path / "source"
    source.mkdir()
    _git(source, env, "init", "--initial-branch=main")
    (source / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    (source / "requirements").mkdir()
    (source / "scripts").mkdir()
    (source / "scripts" / "check-dependency-pins.py").write_text("# fixture checker\n", encoding="utf-8")
    (source / "requirements" / "build.txt").write_text("hatchling==1.27.0\n", encoding="utf-8")
    (source / "source.txt").write_text("release\n", encoding="utf-8")
    _git(source, env, "add", ".")
    _git(source, env, "commit", "-m", "release")
    _git(source, env, "tag", "v1.2.3")
    (source / "source.txt").write_text("main\n", encoding="utf-8")
    _git(source, env, "commit", "-am", "main development")
    repo = Path(env["FORGE_HOME"]) / "repo"
    _git(tmp_path, env, "clone", "--branch", "main", str(source), str(repo))
    (repo / "local.txt").write_text("local commit\n", encoding="utf-8")
    _git(repo, env, "add", ".")
    _git(repo, env, "commit", "-m", "local development")
    return source, repo, env


@pytest.mark.parametrize("version", ["v1.2.3", "main"])
def test_real_git_update_installs_requested_remote_revision_without_local_commits(
    local_git_installation: tuple[Path, Path, dict[str, str]], version: str
) -> None:
    source, repo, env = local_git_installation
    requested_commit = _git(source, env, "rev-parse", version)
    assert _git(repo, env, "rev-parse", "HEAD") != requested_commit

    result = _install(env, "--version", version)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(repo, env, "rev-parse", "HEAD") == requested_commit
    assert _git(repo, env, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"
    assert not (repo / "local.txt").exists()
    assert "pull" not in Path(env["GIT_LOG"]).read_text(encoding="utf-8")


def test_real_git_dirty_update_preserves_files_and_revision(
    local_git_installation: tuple[Path, Path, dict[str, str]],
) -> None:
    _, repo, env = local_git_installation
    original_commit = _git(repo, env, "rev-parse", "HEAD")
    (repo / "source.txt").write_text("uncommitted edit\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("untracked user file\n", encoding="utf-8")

    result = _install(env)

    assert result.returncode != 0
    assert "uncommitted changes" in result.stderr
    assert _git(repo, env, "rev-parse", "HEAD") == original_commit
    assert (repo / "source.txt").read_text(encoding="utf-8") == "uncommitted edit\n"
    assert (repo / "untracked.txt").read_text(encoding="utf-8") == "untracked user file\n"
    assert Path(env["GIT_LOG"]).read_text(encoding="utf-8").splitlines() == ["status --porcelain"]
    assert Path(env["UV_LOG"]).read_text(encoding="utf-8").splitlines() == ["--version"]


@pytest.mark.parametrize("rejection", ["missing-build-constraints", "missing-checker", "stale-pins"])
def test_rejected_revision_does_not_replace_active_editable_source(
    local_git_installation: tuple[Path, Path, dict[str, str]], rejection: str
) -> None:
    source, repo, env = local_git_installation
    original_commit = _git(repo, env, "rev-parse", "HEAD")
    original_source = (repo / "source.txt").read_text(encoding="utf-8")
    executable = repo / ".venv" / "bin" / "forge"
    executable.parent.mkdir(parents=True)
    executable.write_text('#!/bin/sh\ncat "$FORGE_HOME/repo/source.txt"\n', encoding="utf-8")
    executable.chmod(0o755)
    wrapper = Path(env["FORGE_HOME"]) / "bin" / "forge"
    wrapper.parent.mkdir()
    wrapper.write_text('#!/bin/sh\nexec "$FORGE_HOME/repo/.venv/bin/forge" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    original_executable = executable.read_bytes()
    original_wrapper = wrapper.read_bytes()
    _git(source, env, "checkout", "-b", "rejected")
    (source / "source.txt").write_text("refused candidate\n", encoding="utf-8")
    if rejection == "missing-build-constraints":
        (source / "requirements" / "build.txt").unlink()
    elif rejection == "missing-checker":
        (source / "scripts" / "check-dependency-pins.py").unlink()
    else:
        env["PIN_CHECK_FAILURE"] = "1"
    _git(source, env, "add", "-A")
    _git(source, env, "commit", "-m", "candidate that fails admission")

    result = _install(env, "--version", "rejected")

    assert result.returncode != 0
    expected_error = {
        "missing-build-constraints": "Reviewed build constraints are missing",
        "missing-checker": "Dependency pin checker is missing",
        "stale-pins": "Dependency pin verification failed",
    }[rejection]
    assert expected_error in result.stderr
    assert _git(repo, env, "rev-parse", "HEAD") == original_commit
    assert (repo / "source.txt").read_text(encoding="utf-8") == original_source
    assert executable.read_bytes() == original_executable
    assert wrapper.read_bytes() == original_wrapper
    launched = subprocess.run([str(wrapper)], env=env, text=True, capture_output=True, check=True)
    assert launched.stdout == original_source
    assert _git(repo, env, "status", "--porcelain") == ""
    assert Path(env["UV_LOG"]).read_text(encoding="utf-8").splitlines() == ["--version"]
    assert not list(Path(env["FORGE_HOME"]).glob(".install-candidate.*"))


def test_update_activates_admitted_commit_when_fetch_head_changes_during_verification(
    local_git_installation: tuple[Path, Path, dict[str, str]],
) -> None:
    source, repo, env = local_git_installation
    admitted_commit = _git(source, env, "rev-parse", "v1.2.3")
    env["MOVE_FETCH_HEAD_TO"] = _git(repo, env, "rev-parse", "HEAD")

    result = _install(env, "--version", "v1.2.3")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _git(repo, env, "rev-parse", "HEAD") == admitted_commit
    assert (repo / "source.txt").read_text(encoding="utf-8") == "release\n"
