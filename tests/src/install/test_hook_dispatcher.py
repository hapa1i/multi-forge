"""Tests for the user-scope hook dispatcher artifact."""

from __future__ import annotations

import json
import os
import runpy
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from forge.install.hook_dispatcher import (
    diagnose_hook_dispatcher,
    dispatcher_source_sha256,
    get_hook_dispatcher_path,
    get_runtime_metadata_path,
    install_hook_dispatcher,
    known_forge_launcher_paths,
    normalize_dispatcher_command_home,
    parse_dispatcher_stamp,
    read_runtime_metadata,
    render_dispatcher_command,
    render_dispatcher_script,
    select_forge_binary_for_recording,
    write_runtime_metadata,
)
from forge.install.project_registry import ProjectRegistryStore


def _forge_home() -> Path:
    return Path(os.environ["FORGE_HOME"])


def _env(tmp_path: Path, forge_home: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_HOME"] = str(forge_home)
    env["PATH"] = "/usr/bin:/bin"
    env.pop("FORGE_SESSION", None)
    return env


def _make_fake_forge(tmp_path: Path) -> tuple[Path, Path]:
    record_path = tmp_path / "fake-forge-call.json"
    fake = tmp_path / "fake-bin" / "forge"
    fake.parent.mkdir(parents=True)
    fake.write_text(
        (
            f"#!{sys.executable}\n"
            "import json\n"
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n"
            "record = {\n"
            "    'argv': sys.argv,\n"
            "    'stdin': sys.stdin.read(),\n"
            "}\n"
            "Path(os.environ['FORGE_FAKE_RECORD']).write_text(json.dumps(record), encoding='utf-8')\n"
            "sys.stdout.write(os.environ.get('FORGE_FAKE_STDOUT', ''))\n"
            "sys.stderr.write(os.environ.get('FORGE_FAKE_STDERR', ''))\n"
            "raise SystemExit(int(os.environ.get('FORGE_FAKE_EXIT', '0')))\n"
        ),
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return fake, record_path


def _make_dev_checkout(root: Path) -> tuple[Path, Path]:
    fake, record_path = _make_fake_forge(root / "fixture")
    venv = root / ".venv"
    target = venv / "bin" / "forge"
    target.parent.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    target.write_text(fake.read_text(encoding="utf-8"), encoding="utf-8")
    target.chmod(target.stat().st_mode | stat.S_IXUSR)
    return target, record_path


def _install_dispatcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_forge: Path | None = None) -> Path:
    forge_home = _forge_home()
    monkeypatch.setenv("FORGE_HOME", str(forge_home))
    install_hook_dispatcher(forge_binary_path=fake_forge)
    dispatcher = get_hook_dispatcher_path()
    assert dispatcher.is_file()
    assert os.access(dispatcher, os.X_OK)
    return dispatcher


def _run_dispatcher(
    dispatcher: Path,
    cwd: Path,
    env: dict[str, str],
    *,
    hook_name: str | None = "session-start",
    stdin: str = "{}",
) -> subprocess.CompletedProcess[str]:
    argv = [sys.executable, str(dispatcher)]
    if hook_name is not None:
        argv.append(hook_name)
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )


def _read_fake_record(record_path: Path) -> dict[str, object]:
    return json.loads(record_path.read_text(encoding="utf-8"))


def _forge_project(root: Path, *, git_file: bool = False) -> Path:
    (root / ".forge").mkdir(parents=True)
    if git_file:
        (root / ".git").write_text("gitdir: ../.git/worktrees/example\n", encoding="utf-8")
    else:
        (root / ".git").mkdir(exist_ok=True)
    return root


def _enroll(root: Path) -> None:
    ProjectRegistryStore(_forge_home() / "projects.json").enroll(root, "enable")


def _lookup(start: Path) -> bool:
    return ProjectRegistryStore(_forge_home() / "projects.json").lookup_enrolled_root(start).enrolled


def test_rendered_command_template_golden(tmp_path: Path) -> None:
    forge_home = tmp_path / "home" / ".forge"
    command = render_dispatcher_command("codex-session-start", forge_home=forge_home)

    assert command == f"{forge_home}/bin/forge-hook codex-session-start"
    assert normalize_dispatcher_command_home(command, home=tmp_path / "home") == (
        "$HOME/.forge/bin/forge-hook codex-session-start"
    )
    assert "~" not in command


def test_rendered_script_carries_current_source_stamp() -> None:
    script = render_dispatcher_script()
    version, source_hash = parse_dispatcher_stamp(script)

    assert version is not None
    assert source_hash == dispatcher_source_sha256()
    assert "from forge" not in script
    assert "import pydantic" not in script


def test_install_writes_dispatcher_and_runtime_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_forge, _record = _make_fake_forge(tmp_path)

    dispatcher = _install_dispatcher(tmp_path, monkeypatch, fake_forge)
    metadata = read_runtime_metadata()

    assert dispatcher == _forge_home() / "bin" / "forge-hook"
    assert metadata is not None
    assert metadata["forge_binary_path"] == str(fake_forge)
    assert metadata["dispatcher_path"] == str(dispatcher)
    assert metadata["dispatcher_source_sha256"] == dispatcher_source_sha256()


def test_known_forge_launcher_paths_preserve_dispatcher_precedence(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    env = {
        "HOME": str(home),
        "UV_TOOL_BIN_DIR": str(tmp_path / "uv-bin"),
        "XDG_BIN_HOME": str(tmp_path / "xdg-bin"),
        "PIPX_BIN_DIR": str(tmp_path / "pipx-bin"),
    }

    assert known_forge_launcher_paths(env) == [
        home / ".local" / "bin" / "forge",
        tmp_path / "uv-bin" / "forge",
        tmp_path / "xdg-bin" / "forge",
        tmp_path / "pipx-bin" / "forge",
    ]


def test_dispatcher_resolves_recorded_global_forge_without_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_forge, record_path = _make_fake_forge(tmp_path)
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, fake_forge)
    repo = _forge_project(tmp_path / "repo")
    cwd = repo / "src" / "pkg"
    cwd.mkdir(parents=True)
    _enroll(repo)
    env = _env(tmp_path, _forge_home())
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, cwd, env, hook_name="policy-check", stdin='{"tool":"Read"}')

    assert result.returncode == 0, result.stderr
    record = _read_fake_record(record_path)
    assert record["argv"] == [str(fake_forge), "hook", "policy-check"]
    assert record["stdin"] == '{"tool":"Read"}'


def test_stale_target_falls_back_to_known_user_tool_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_forge, record_path = _make_fake_forge(tmp_path)
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, tmp_path / "missing-forge")
    home = tmp_path / "home"
    known_bin = home / ".local" / "bin"
    known_bin.mkdir(parents=True)
    fallback_forge = known_bin / "forge"
    fallback_forge.symlink_to(fake_forge)
    repo = _forge_project(tmp_path / "repo")
    _enroll(repo)
    env = _env(tmp_path, _forge_home())
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, repo, env, hook_name="stop")

    assert result.returncode == 0, result.stderr
    record = _read_fake_record(record_path)
    assert record["argv"] == [str(fallback_forge), "hook", "stop"]


def test_resolution_failure_names_checked_locations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, tmp_path / "missing-forge")
    repo = _forge_project(tmp_path / "repo")
    _enroll(repo)
    env = _env(tmp_path, _forge_home())

    result = _run_dispatcher(dispatcher, repo, env)

    assert result.returncode == 127
    assert "could not find the global 'forge' launcher" in result.stderr
    assert str(tmp_path / "missing-forge") in result.stderr
    assert str(Path(env["HOME"]) / ".local" / "bin" / "forge") in result.stderr


def test_dev_override_executes_named_checkout_in_different_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_forge, _global_record = _make_fake_forge(tmp_path / "global")
    dev_forge, record_path = _make_dev_checkout(tmp_path / "Forge checkout with spaces")
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, global_forge)
    repo = _forge_project(tmp_path / "other-project")
    project_forge, _project_record = _make_dev_checkout(repo)
    _enroll(repo)
    env = _env(tmp_path, _forge_home())
    env["FORGE_DEV"] = str(dev_forge.parents[2])
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, repo, env, hook_name="policy-check", stdin='{"tool":"Read"}')

    assert result.returncode == 0, result.stderr
    record = _read_fake_record(record_path)
    assert record["argv"] == [str(dev_forge), "hook", "policy-check"]
    assert record["argv"][0] != str(project_forge)
    assert record["stdin"] == '{"tool":"Read"}'


@pytest.mark.parametrize(
    ("value", "expected_stderr", "plant_cwd_competitor"),
    [
        (
            "",
            "FORGE_DEV is set but empty; expected an absolute Forge checkout root",
            False,
        ),
        (
            "relative/path",
            "FORGE_DEV must name an absolute Forge checkout root; got 'relative/path'",
            True,
        ),
        (
            "1",
            "FORGE_DEV must name an absolute Forge checkout root; got '1'",
            False,
        ),
        (
            "true",
            "FORGE_DEV must name an absolute Forge checkout root; got 'true'",
            False,
        ),
        (
            "~forge-user-that-cannot-exist/checkout",
            "FORGE_DEV value '~forge-user-that-cannot-exist/checkout' could not be expanded:",
            False,
        ),
    ],
)
def test_invalid_dev_override_fails_loud_without_global_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected_stderr: str,
    plant_cwd_competitor: bool,
) -> None:
    global_forge, record_path = _make_fake_forge(tmp_path / "global")
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, global_forge)
    repo = _forge_project(tmp_path / "repo")
    if plant_cwd_competitor:
        _make_dev_checkout(repo / value)
    _enroll(repo)
    env = _env(tmp_path, _forge_home())
    env["FORGE_DEV"] = value
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, repo, env)

    assert result.returncode == 127
    assert expected_stderr in result.stderr
    assert "Traceback" not in result.stderr
    assert not record_path.exists()


def test_dev_override_expands_home_relative_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_forge, _global_record = _make_fake_forge(tmp_path / "global")
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, global_forge)
    repo = _forge_project(tmp_path / "repo")
    _enroll(repo)
    env = _env(tmp_path, _forge_home())
    dev_forge, record_path = _make_dev_checkout(Path(env["HOME"]) / "checkout")
    env["FORGE_DEV"] = "~/checkout"
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, repo, env, hook_name="stop")

    assert result.returncode == 0, result.stderr
    record = _read_fake_record(record_path)
    assert record["argv"] == [str(dev_forge), "hook", "stop"]


def test_missing_dev_override_target_fails_without_global_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_forge, record_path = _make_fake_forge(tmp_path / "global")
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, global_forge)
    repo = _forge_project(tmp_path / "repo")
    _enroll(repo)
    env = _env(tmp_path, _forge_home())
    env["FORGE_DEV"] = str(tmp_path / "missing-checkout")
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, repo, env)

    assert result.returncode == 127
    target = tmp_path / "missing-checkout" / ".venv" / "bin" / "forge"
    assert f"FORGE_DEV target is missing or not executable: {target}" in result.stderr
    assert not record_path.exists()


def test_non_executable_dev_override_target_fails_without_global_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_forge, record_path = _make_fake_forge(tmp_path / "global")
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, global_forge)
    repo = _forge_project(tmp_path / "repo")
    _enroll(repo)
    checkout = tmp_path / "checkout"
    target = checkout / ".venv" / "bin" / "forge"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    target.chmod(0o644)
    env = _env(tmp_path, _forge_home())
    env["FORGE_DEV"] = str(checkout)
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, repo, env)

    assert result.returncode == 127
    assert f"FORGE_DEV target is missing or not executable: {target}" in result.stderr
    assert not record_path.exists()


def test_dev_override_exec_failure_is_caught(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global_forge, record_path = _make_fake_forge(tmp_path / "global")
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, global_forge)
    repo = _forge_project(tmp_path / "repo")
    _enroll(repo)
    checkout = tmp_path / "checkout"
    target = checkout / ".venv" / "bin" / "forge"
    target.parent.mkdir(parents=True)
    target.write_text("#!/definitely/missing/interpreter\n", encoding="utf-8")
    target.chmod(0o755)
    env = _env(tmp_path, _forge_home())
    env["FORGE_DEV"] = str(checkout)
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, repo, env)

    assert result.returncode == 127
    assert "FORGE_DEV target could not be executed" in result.stderr
    assert "Traceback" not in result.stderr
    assert not record_path.exists()


def test_returning_override_execv_does_not_enter_normal_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_forge, _global_record = _make_fake_forge(tmp_path / "global")
    dev_forge, _dev_record = _make_dev_checkout(tmp_path / "checkout")
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, global_forge)
    namespace = runpy.run_path(str(dispatcher), run_name="forge_hook_test")
    calls: list[tuple[str, list[str]]] = []

    def returning_execv(path: str, argv: list[str]) -> None:
        calls.append((path, argv))

    monkeypatch.setenv("FORGE_SESSION", "managed")
    monkeypatch.setenv("FORGE_DEV", str(dev_forge.parents[2]))
    monkeypatch.setattr(os, "execv", returning_execv)
    monkeypatch.setattr(sys, "argv", [str(dispatcher), "policy-check"])

    result = namespace["main"]()

    assert result == 127
    assert calls == [
        (
            str(dev_forge),
            [str(dev_forge), "hook", "policy-check"],
        )
    ]


def test_dev_override_does_not_bypass_handler_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global_forge, record_path = _make_fake_forge(tmp_path / "global")
    dev_forge, _dev_record = _make_dev_checkout(tmp_path / "checkout")
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, global_forge)
    repo = _forge_project(tmp_path / "repo")
    _enroll(repo)
    env = _env(tmp_path, _forge_home())
    env["FORGE_DEV"] = str(dev_forge.parents[2])
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, repo, env, hook_name=None)

    assert result.returncode == 2
    assert "missing hook name" in result.stderr
    assert not record_path.exists()


def test_dev_override_does_not_bypass_noop_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global_forge, record_path = _make_fake_forge(tmp_path / "global")
    dev_forge, _dev_record = _make_dev_checkout(tmp_path / "checkout")
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, global_forge)
    repo = _forge_project(tmp_path / "not-enrolled")
    env = _env(tmp_path, _forge_home())
    env["FORGE_DEV"] = str(dev_forge.parents[2])
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, repo, env)

    assert result.returncode == 0
    assert not record_path.exists()


def test_unset_dev_override_never_selects_cwd_checkout_venv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_forge, record_path = _make_fake_forge(tmp_path / "global")
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, global_forge)
    repo = _forge_project(tmp_path / "repo")
    cwd_forge, _cwd_record = _make_dev_checkout(repo)
    _enroll(repo)
    env = _env(tmp_path, _forge_home())
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, repo, env, hook_name="stop")

    assert result.returncode == 0, result.stderr
    record = _read_fake_record(record_path)
    assert record["argv"] == [str(global_forge), "hook", "stop"]
    assert record["argv"][0] != str(cwd_forge)


def test_outside_project_noops_without_importing_forge_or_resolving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_forge, record_path = _make_fake_forge(tmp_path)
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, fake_forge)
    tripwire = tmp_path / "tripwire"
    (tripwire / "forge").mkdir(parents=True)
    (tripwire / "forge" / "__init__.py").write_text("raise SystemExit('imported forge')\n", encoding="utf-8")
    (tripwire / "pydantic.py").write_text("raise SystemExit('imported pydantic')\n", encoding="utf-8")
    repo = _forge_project(tmp_path / "not-enrolled")
    env = _env(tmp_path, _forge_home())
    env["PYTHONPATH"] = str(tripwire)
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, repo, env)

    assert result.returncode == 0, result.stderr
    assert not record_path.exists()


def test_managed_session_short_circuits_enrollment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_forge, record_path = _make_fake_forge(tmp_path)
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, fake_forge)
    cwd = tmp_path / "plain-repo"
    cwd.mkdir()
    env = _env(tmp_path, _forge_home())
    env["FORGE_SESSION"] = "managed"
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, cwd, env)

    assert result.returncode == 0, result.stderr
    assert _read_fake_record(record_path)["argv"] == [
        str(fake_forge),
        "hook",
        "session-start",
    ]


def test_corrupt_and_newer_registry_fail_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_forge, record_path = _make_fake_forge(tmp_path)
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, fake_forge)
    repo = _forge_project(tmp_path / "repo")
    env = _env(tmp_path, _forge_home())
    env["FORGE_FAKE_RECORD"] = str(record_path)
    registry = _forge_home() / "projects.json"

    registry.write_text("{not json", encoding="utf-8")
    corrupt = _run_dispatcher(dispatcher, repo, env)

    registry.write_text(json.dumps({"schema_version": 999, "projects": []}), encoding="utf-8")
    newer = _run_dispatcher(dispatcher, repo, env)

    assert corrupt.returncode == 0, corrupt.stderr
    assert newer.returncode == 0, newer.stderr
    assert not record_path.exists()


def test_unknown_registry_top_level_field_matches_package_fail_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_forge, record_path = _make_fake_forge(tmp_path)
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, fake_forge)
    repo = _forge_project(tmp_path / "repo")
    _enroll(repo)
    registry = _forge_home() / "projects.json"
    data = json.loads(registry.read_text(encoding="utf-8"))
    data["unexpected"] = True
    registry.write_text(json.dumps(data), encoding="utf-8")
    env = _env(tmp_path, _forge_home())
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, repo, env)

    assert _lookup(repo) is False
    assert result.returncode == 0, result.stderr
    assert not record_path.exists()


def test_gate_exceptions_fail_open_for_deleted_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_forge, record_path = _make_fake_forge(tmp_path)
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, fake_forge)
    deleted = tmp_path / "deleted-cwd"
    deleted.mkdir()
    env = _env(tmp_path, _forge_home())
    env["FORGE_FAKE_RECORD"] = str(record_path)
    probe = (
        "import json, os, pathlib, shutil, subprocess, sys\n"
        "work = pathlib.Path(sys.argv[1])\n"
        "dispatcher = sys.argv[2]\n"
        "os.chdir(work)\n"
        "shutil.rmtree(work)\n"
        "result = subprocess.run(\n"
        "    [sys.executable, dispatcher, 'session-start'],\n"
        "    text=True,\n"
        "    capture_output=True,\n"
        "    check=False,\n"
        ")\n"
        "print(json.dumps({'returncode': result.returncode, 'stderr': result.stderr, 'stdout': result.stdout}))\n"
    )

    wrapper = subprocess.run(
        [sys.executable, "-c", probe, str(deleted), str(dispatcher)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert wrapper.returncode == 0, wrapper.stderr
    payload = json.loads(wrapper.stdout)
    assert payload["returncode"] == 0
    assert payload["stdout"] == ""
    assert "Traceback" not in payload["stderr"]
    assert not record_path.exists()


def test_nested_unenrolled_git_repo_noops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_forge, record_path = _make_fake_forge(tmp_path)
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, fake_forge)
    parent = _forge_project(tmp_path / "parent")
    _enroll(parent)
    nested = parent / "nested"
    nested.mkdir()
    (nested / ".git").mkdir()
    cwd = nested / "src"
    cwd.mkdir()
    env = _env(tmp_path, _forge_home())
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, cwd, env)

    assert _lookup(cwd) is False
    assert result.returncode == 0, result.stderr
    assert not record_path.exists()


@pytest.mark.parametrize("git_file", [False, True])
def test_subdirectory_cwd_dispatches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    git_file: bool,
) -> None:
    fake_forge, record_path = _make_fake_forge(tmp_path)
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, fake_forge)
    repo = _forge_project(tmp_path / "repo", git_file=git_file)
    cwd = repo / "a" / "b"
    cwd.mkdir(parents=True)
    _enroll(repo)
    env = _env(tmp_path, _forge_home())
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, cwd, env)

    assert _lookup(cwd) is True
    assert result.returncode == 0, result.stderr
    assert _read_fake_record(record_path)["argv"] == [
        str(fake_forge),
        "hook",
        "session-start",
    ]


def test_symlinked_root_parity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_forge, record_path = _make_fake_forge(tmp_path)
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, fake_forge)
    repo = _forge_project(tmp_path / "repo")
    link = tmp_path / "repo-link"
    try:
        link.symlink_to(repo, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    _enroll(link)
    cwd = repo / "src"
    cwd.mkdir()
    env = _env(tmp_path, _forge_home())
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, cwd, env)

    assert _lookup(cwd) is True
    assert result.returncode == 0, result.stderr
    assert record_path.exists()


def test_case_variant_samefile_parity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _forge_project(tmp_path / "Repo")
    variant = repo.with_name("repo")
    if not variant.exists():
        pytest.skip("filesystem is case-sensitive")

    fake_forge, record_path = _make_fake_forge(tmp_path)
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, fake_forge)
    _enroll(repo)
    env = _env(tmp_path, _forge_home())
    env["FORGE_FAKE_RECORD"] = str(record_path)

    result = _run_dispatcher(dispatcher, variant, env)

    assert _lookup(variant) is True
    assert result.returncode == 0, result.stderr
    assert record_path.exists()


@pytest.mark.parametrize(
    ("payload", "exit_code"),
    [
        ('{"runtime":"claude","hook_event_name":"SessionStart"}', 0),
        ('{"runtime":"codex","event":"PreToolUse"}', 7),
    ],
)
def test_runtime_agnostic_forwarding_preserves_stdio_and_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: str,
    exit_code: int,
) -> None:
    fake_forge, record_path = _make_fake_forge(tmp_path)
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, fake_forge)
    repo = _forge_project(tmp_path / "repo")
    _enroll(repo)
    env = _env(tmp_path, _forge_home())
    env["FORGE_FAKE_RECORD"] = str(record_path)
    env["FORGE_FAKE_STDOUT"] = "forwarded stdout\n"
    env["FORGE_FAKE_STDERR"] = "forwarded stderr\n"
    env["FORGE_FAKE_EXIT"] = str(exit_code)

    result = _run_dispatcher(dispatcher, repo, env, hook_name="codex-policy-check", stdin=payload)

    assert result.returncode == exit_code
    assert result.stdout == "forwarded stdout\n"
    assert result.stderr == "forwarded stderr\n"
    record = _read_fake_record(record_path)
    assert record["argv"] == [str(fake_forge), "hook", "codex-policy-check"]
    assert record["stdin"] == payload


def test_doctor_reports_stale_shim_and_sync_rerenders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_forge, _record_path = _make_fake_forge(tmp_path)
    dispatcher = get_hook_dispatcher_path()
    dispatcher.parent.mkdir(parents=True, exist_ok=True)
    dispatcher.write_text(render_dispatcher_script(version="0.0.0-old"), encoding="utf-8")
    dispatcher.chmod(0o755)
    write_runtime_metadata(forge_binary_path=fake_forge, dispatcher_path=dispatcher)

    stale = diagnose_hook_dispatcher()
    install_hook_dispatcher(forge_binary_path=fake_forge)
    current = diagnose_hook_dispatcher()

    assert stale.status == "stale"
    assert stale.installed_version == "0.0.0-old"
    assert current.status == "current"
    assert current.installed_source_sha256 == dispatcher_source_sha256()
    assert get_runtime_metadata_path().is_file()


def test_doctor_reports_valid_effective_dev_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global_forge, _global_record = _make_fake_forge(tmp_path / "global")
    dev_forge, _dev_record = _make_dev_checkout(tmp_path / "checkout")
    _install_dispatcher(tmp_path, monkeypatch, global_forge)
    env = _env(tmp_path, _forge_home())
    env["FORGE_DEV"] = str(dev_forge.parents[2])

    diagnosis = diagnose_hook_dispatcher(environ=env)

    assert diagnosis.dev_override.to_dict() == {
        "present": True,
        "value": str(dev_forge.parents[2]),
        "target": str(dev_forge),
        "valid": True,
        "effective": True,
        "advice": None,
    }


def test_doctor_separates_valid_override_from_stale_dispatcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_forge, _global_record = _make_fake_forge(tmp_path / "global")
    dev_forge, _dev_record = _make_dev_checkout(tmp_path / "checkout")
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, global_forge)
    dispatcher.write_text(render_dispatcher_script(version="0.0.0-old"), encoding="utf-8")
    dispatcher.chmod(0o755)
    env = _env(tmp_path, _forge_home())
    env["FORGE_DEV"] = str(dev_forge.parents[2])

    diagnosis = diagnose_hook_dispatcher(environ=env)

    assert diagnosis.status == "stale"
    assert diagnosis.dev_override.valid is True
    assert diagnosis.dev_override.effective is False
    assert diagnosis.dev_override.advice is not None
    assert "extension enable --scope user" in diagnosis.dev_override.advice
    assert "--with hooks,codex-hooks --without commands" in diagnosis.dev_override.advice
    assert "extension sync" not in diagnosis.dev_override.advice


def test_doctor_detects_source_hash_staleness_with_current_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_forge, _record = _make_fake_forge(tmp_path / "global")
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, global_forge)
    current = render_dispatcher_script()
    dispatcher.write_text(
        current.replace(
            f'FORGE_HOOK_DISPATCHER_SOURCE_SHA256 = "{dispatcher_source_sha256()}"',
            'FORGE_HOOK_DISPATCHER_SOURCE_SHA256 = "' + ("0" * 64) + '"',
        ),
        encoding="utf-8",
    )

    diagnosis = diagnose_hook_dispatcher()

    assert diagnosis.status == "stale"
    assert diagnosis.installed_version == diagnosis.expected_version
    assert diagnosis.installed_source_sha256 != diagnosis.expected_source_sha256


def test_doctor_reports_mode_drift_as_ineffective(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global_forge, _global_record = _make_fake_forge(tmp_path / "global")
    dev_forge, _dev_record = _make_dev_checkout(tmp_path / "checkout")
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, global_forge)
    dispatcher.chmod(0o644)
    env = _env(tmp_path, _forge_home())
    env["FORGE_DEV"] = str(dev_forge.parents[2])

    diagnosis = diagnose_hook_dispatcher(environ=env)

    assert diagnosis.status == "non_executable"
    assert diagnosis.dev_override.valid is True
    assert diagnosis.dev_override.effective is False
    assert diagnosis.dev_override.advice is not None
    assert "execute permission" in diagnosis.dev_override.advice


def test_doctor_reports_invalid_dev_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    global_forge, _global_record = _make_fake_forge(tmp_path / "global")
    _install_dispatcher(tmp_path, monkeypatch, global_forge)
    env = _env(tmp_path, _forge_home())
    env["FORGE_DEV"] = str(tmp_path / "missing-checkout")

    diagnosis = diagnose_hook_dispatcher(environ=env)

    assert diagnosis.dev_override.present is True
    assert diagnosis.dev_override.valid is False
    assert diagnosis.dev_override.effective is False
    assert diagnosis.dev_override.target == str(tmp_path / "missing-checkout" / ".venv" / "bin" / "forge")
    assert diagnosis.dev_override.advice is not None
    assert "missing or not executable" in diagnosis.dev_override.advice


def test_doctor_advises_sync_when_custom_launcher_is_discoverable_but_not_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    custom_forge, _record = _make_fake_forge(tmp_path / "custom")
    _install_dispatcher(tmp_path, monkeypatch, tmp_path / "missing-recorded")
    env = _env(tmp_path, _forge_home())

    diagnosis = diagnose_hook_dispatcher(
        environ=env,
        argv0="forge",
        which=lambda *_args, **_kwargs: str(custom_forge),
        has_user_installation=True,
    )

    assert diagnosis.status == "current"
    assert diagnosis.advice is not None
    assert "extension sync --scope user" in diagnosis.advice
    assert str(custom_forge) in diagnosis.advice


def test_doctor_advises_enable_when_never_enabled_and_launcher_unrecorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sync refuses on a never-enabled machine, so the advice must name enable."""
    custom_forge, _record = _make_fake_forge(tmp_path / "custom")
    _install_dispatcher(tmp_path, monkeypatch, tmp_path / "missing-recorded")
    env = _env(tmp_path, _forge_home())

    diagnosis = diagnose_hook_dispatcher(
        environ=env,
        argv0="forge",
        which=lambda *_args, **_kwargs: str(custom_forge),
        has_user_installation=False,
    )

    assert diagnosis.status == "current"
    assert diagnosis.advice is not None
    assert "extension enable --scope user" in diagnosis.advice
    assert "--with hooks,codex-hooks --without commands" in diagnosis.advice
    assert "extension sync" not in diagnosis.advice
    assert str(custom_forge) in diagnosis.advice


def test_doctor_missing_dispatcher_never_enabled_advises_enable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh machine (no dispatcher, nothing tracked): advice must not name sync."""
    env = _env(tmp_path, _forge_home())

    diagnosis = diagnose_hook_dispatcher(
        environ=env,
        argv0="forge",
        which=lambda *_args, **_kwargs: None,
        has_user_installation=False,
    )

    assert diagnosis.status == "missing"
    assert diagnosis.advice is not None
    assert "extension enable --scope user" in diagnosis.advice
    assert "--with hooks,codex-hooks --without commands" in diagnosis.advice
    assert "extension sync" not in diagnosis.advice


def test_doctor_unrelated_project_install_still_advises_user_enable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A different project's tracking entry cannot make sync actionable here."""
    from forge.install.models import (
        Installation,
        InstallMode,
        InstallProfile,
        InstallScope,
    )
    from forge.install.tracking import TrackingStore

    unrelated = tmp_path / "unrelated-project"
    unrelated.mkdir()
    TrackingStore().set_installation(
        InstallScope.PROJECT.value,
        Installation(
            scope=InstallScope.PROJECT.value,
            project_path=str(unrelated),
            mode=InstallMode.COPY.value,
            profile=InstallProfile.MINIMAL.value,
            installed_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ),
        str(unrelated),
    )
    env = _env(tmp_path, _forge_home())

    diagnosis = diagnose_hook_dispatcher(
        environ=env,
        argv0="forge",
        which=lambda *_args, **_kwargs: None,
    )

    assert diagnosis.status == "missing"
    assert diagnosis.advice is not None
    assert "extension enable --scope user" in diagnosis.advice
    assert "--with hooks,codex-hooks --without commands" in diagnosis.advice
    assert "extension sync" not in diagnosis.advice


def test_doctor_advises_migrating_recorded_venv_even_with_global_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    venv_forge, _venv_record = _make_dev_checkout(tmp_path / "checkout")
    global_forge, _global_record = _make_fake_forge(tmp_path / "global")
    home = tmp_path / "home"
    global_launcher = home / ".local" / "bin" / "forge"
    global_launcher.parent.mkdir(parents=True)
    global_launcher.symlink_to(global_forge)
    _install_dispatcher(tmp_path, monkeypatch, venv_forge)
    env = _env(tmp_path, _forge_home())
    env["HOME"] = str(home)

    diagnosis = diagnose_hook_dispatcher(
        environ=env,
        argv0="forge",
        which=lambda *_args, **_kwargs: None,
    )

    assert diagnosis.forge_binary_path == str(venv_forge)
    assert diagnosis.advice is not None
    assert "replace the recorded virtualenv launcher" in diagnosis.advice


def test_doctor_advises_install_when_no_runtime_or_recording_target_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_dispatcher(tmp_path, monkeypatch, tmp_path / "missing-recorded")
    env = _env(tmp_path, _forge_home())

    diagnosis = diagnose_hook_dispatcher(
        environ=env,
        argv0="forge",
        which=lambda *_args, **_kwargs: None,
    )

    assert diagnosis.status == "current"
    assert diagnosis.advice is not None
    assert "install one" in diagnosis.advice
    # Isolated FORGE_HOME has no tracked install, so real auto-detection picks
    # the enable spelling (sync would refuse on this machine).
    assert "extension enable --scope user" in diagnosis.advice


def test_doctor_qualifies_missing_normal_launcher_when_dev_override_is_effective(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dev_forge, _record = _make_dev_checkout(tmp_path / "checkout")
    _install_dispatcher(tmp_path, monkeypatch, tmp_path / "missing-recorded")
    env = _env(tmp_path, _forge_home())
    env["FORGE_DEV"] = str(dev_forge.parents[2])

    diagnosis = diagnose_hook_dispatcher(
        environ=env,
        argv0="forge",
        which=lambda *_args, **_kwargs: None,
    )

    assert diagnosis.dev_override.effective is True
    assert diagnosis.advice is not None
    assert diagnosis.advice.startswith(
        "FORGE_DEV is effective for this process; without it, normal resolution reports:"
    )
    assert "install one" in diagnosis.advice


def test_noop_path_skips_dispatch_with_populated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_forge, record_path = _make_fake_forge(tmp_path)
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, fake_forge)
    roots = [_forge_project(tmp_path / "enrolled" / f"repo-{index:02d}") for index in range(40)]
    for root in roots:
        _enroll(root)
    probe = _forge_project(tmp_path / "unenrolled")
    cwd = probe / "a" / "b" / "c" / "d" / "e"
    cwd.mkdir(parents=True)
    env = _env(tmp_path, _forge_home())
    env["FORGE_FAKE_RECORD"] = str(record_path)

    for _ in range(3):
        result = _run_dispatcher(dispatcher, cwd, env)
        assert result.returncode == 0, result.stderr

    assert not record_path.exists()


@pytest.mark.parametrize("discovery_source", ["which", "argv0"])
def test_install_hook_dispatcher_records_first_custom_launcher(
    discovery_source: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_forge, _record_path = _make_fake_forge(tmp_path)

    def which(command: str, path: str | None = None) -> str | None:
        assert command == "forge"
        assert path == "/usr/bin:/bin"
        return str(fake_forge) if discovery_source == "which" else None

    argv0 = "forge" if discovery_source == "which" else str(fake_forge)
    install_hook_dispatcher(
        argv0=argv0,
        environ={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        which=which,
    )

    metadata = read_runtime_metadata()
    assert metadata is not None
    assert metadata["forge_binary_path"] == str(fake_forge)


@pytest.mark.parametrize("discovery_source", ["which", "argv0"])
def test_recording_selector_replaces_global_a_with_discovered_global_b(
    discovery_source: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    global_a, _record_a = _make_fake_forge(tmp_path / "global-a")
    global_b, _record_b = _make_fake_forge(tmp_path / "global-b")
    install_hook_dispatcher(forge_binary_path=global_a)

    argv0 = "forge" if discovery_source == "which" else str(global_b)
    install_hook_dispatcher(
        argv0=argv0,
        environ={"HOME": str(tmp_path), "PATH": "/custom/bin"},
        which=lambda *_a, **_k: str(global_b) if discovery_source == "which" else None,
    )

    metadata = read_runtime_metadata()
    assert metadata is not None
    assert metadata["forge_binary_path"] == str(global_b)


@pytest.mark.parametrize("discovery_source", ["which", "argv0"])
def test_recording_selector_replaces_legacy_venv_with_discovered_non_venv(
    discovery_source: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    legacy_venv, _legacy_record = _make_dev_checkout(tmp_path / "legacy-checkout")
    replacement, _replacement_record = _make_fake_forge(tmp_path / "replacement")
    install_hook_dispatcher(forge_binary_path=legacy_venv)

    argv0 = "forge" if discovery_source == "which" else str(replacement)
    install_hook_dispatcher(
        argv0=argv0,
        environ={"HOME": str(tmp_path), "PATH": "/custom/bin"},
        which=lambda *_a, **_k: str(replacement) if discovery_source == "which" else None,
    )

    metadata = read_runtime_metadata()
    assert metadata is not None
    assert metadata["forge_binary_path"] == str(replacement)


def test_recording_selector_preserves_global_when_discovery_is_venv_or_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    global_forge, _record = _make_fake_forge(tmp_path / "global")
    venv_forge, _venv_record = _make_dev_checkout(tmp_path / "checkout")
    install_hook_dispatcher(forge_binary_path=global_forge)

    install_hook_dispatcher(
        environ={"HOME": str(tmp_path), "PATH": str(venv_forge.parent)},
        which=lambda *_a, **_k: str(venv_forge),
    )
    after_venv = read_runtime_metadata()
    install_hook_dispatcher(
        argv0=str(venv_forge),
        environ={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        which=lambda *_a, **_k: None,
    )
    after_venv_argv0 = read_runtime_metadata()
    install_hook_dispatcher(
        argv0="forge",
        environ={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        which=lambda *_a, **_k: None,
    )
    after_missing = read_runtime_metadata()

    assert after_venv is not None
    assert after_venv["forge_binary_path"] == str(global_forge)
    assert after_venv_argv0 is not None
    assert after_venv_argv0["forge_binary_path"] == str(global_forge)
    assert after_missing is not None
    assert after_missing["forge_binary_path"] == str(global_forge)


@pytest.mark.parametrize("discovery_source", ["which", "argv0"])
def test_recording_selector_replaces_legacy_venv_with_known_global(
    discovery_source: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    venv_forge, _venv_record = _make_dev_checkout(tmp_path / "checkout")
    known_forge, _known_record = _make_fake_forge(tmp_path / "known-source")
    home = tmp_path / "home"
    known_launcher = home / ".local" / "bin" / "forge"
    known_launcher.parent.mkdir(parents=True)
    known_launcher.symlink_to(known_forge)
    install_hook_dispatcher(forge_binary_path=venv_forge)

    argv0 = "forge" if discovery_source == "which" else str(venv_forge)
    install_hook_dispatcher(
        argv0=argv0,
        environ={"HOME": str(home), "PATH": str(venv_forge.parent)},
        which=lambda *_a, **_k: str(venv_forge) if discovery_source == "which" else None,
    )

    metadata = read_runtime_metadata()
    assert metadata is not None
    assert metadata["forge_binary_path"] == str(known_launcher)


@pytest.mark.parametrize("discovery_source", ["which", "argv0"])
def test_recording_selector_clears_legacy_venv_without_fallback(
    discovery_source: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    venv_forge, _venv_record = _make_dev_checkout(tmp_path / "checkout")
    install_hook_dispatcher(forge_binary_path=venv_forge)

    argv0 = "forge" if discovery_source == "which" else str(venv_forge)
    install_hook_dispatcher(
        argv0=argv0,
        environ={"HOME": str(tmp_path / "empty-home"), "PATH": str(venv_forge.parent)},
        which=lambda *_a, **_k: str(venv_forge) if discovery_source == "which" else None,
    )

    metadata = read_runtime_metadata()
    assert metadata is not None
    assert metadata["forge_binary_path"] is None


def test_recording_selector_classifies_global_symlink_lexically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tool_forge, _record = _make_dev_checkout(tmp_path / "tool-venv")
    home = tmp_path / "home"
    launcher = home / ".local" / "bin" / "forge"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(tool_forge)

    selected = select_forge_binary_for_recording(
        discovered=launcher,
        recorded=None,
        environ={"HOME": str(home)},
    )

    assert selected == launcher


def test_recording_selector_rejects_configured_global_dir_that_is_a_venv(
    tmp_path: Path,
) -> None:
    venv_forge, _record = _make_dev_checkout(tmp_path / "checkout")
    env = {
        "HOME": str(tmp_path / "home"),
        "UV_TOOL_BIN_DIR": str(venv_forge.parent),
    }

    selected = select_forge_binary_for_recording(
        discovered=venv_forge,
        recorded=None,
        environ=env,
    )

    assert selected is None


def test_recording_selector_ignores_non_executable_known_fallback(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    launcher = home / ".local" / "bin" / "forge"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")

    selected = select_forge_binary_for_recording(
        discovered=None,
        recorded=None,
        environ={"HOME": str(home)},
    )

    assert selected is None


@pytest.mark.parametrize("discovery_source", ["which", "argv0"])
def test_unexpandable_implicit_discovery_preserves_recorded_target(
    discovery_source: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_forge, _record = _make_fake_forge(tmp_path / "global")
    install_hook_dispatcher(forge_binary_path=global_forge)

    unexpandable = "~forge-user-that-cannot-exist/bin/forge"
    argv0 = "forge" if discovery_source == "which" else unexpandable
    install_hook_dispatcher(
        argv0=argv0,
        environ={"HOME": str(tmp_path), "PATH": "/custom/bin"},
        which=lambda *_a, **_k: unexpandable if discovery_source == "which" else None,
    )

    metadata = read_runtime_metadata()
    assert metadata is not None
    assert metadata["forge_binary_path"] == str(global_forge)


def test_render_hook_dispatcher_wraps_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from forge.install.exceptions import ForgeInstallError
    from forge.install.installer import _ensure_hook_dispatcher

    def fail() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("forge.install.installer.install_hook_dispatcher", fail)

    with pytest.raises(ForgeInstallError, match="Failed to render hook dispatcher: boom"):
        _ensure_hook_dispatcher()


def test_cli_enable_renders_dispatcher_after_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from click.testing import CliRunner

    from forge.cli.extensions import extensions

    fake_forge, _record_path = _make_fake_forge(tmp_path)

    monkeypatch.setattr(
        "forge.install.hook_dispatcher.find_current_forge_binary",
        lambda **_kwargs: fake_forge,
    )
    monkeypatch.setattr(
        "forge.install.version.check_minimum_version",
        lambda: type("Check", (), {"ok": True})(),
    )

    result = CliRunner().invoke(extensions, ["enable", "--scope", "user", "--profile", "minimal"])

    assert result.exit_code == 0, result.output
    assert get_hook_dispatcher_path().is_file()
    metadata = read_runtime_metadata()
    assert metadata is not None
    assert metadata["forge_binary_path"] == str(fake_forge)


def test_user_enable_reports_legacy_root_without_activating_ambient_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from click.testing import CliRunner

    from forge.cli.extensions import extensions
    from forge.install.models import (
        Installation,
        InstallMode,
        InstallModule,
        InstallProfile,
        InstallScope,
    )
    from forge.install.tracking import TrackingStore

    fake_forge, record_path = _make_fake_forge(tmp_path)
    dispatcher = _install_dispatcher(tmp_path, monkeypatch, fake_forge)
    root = _forge_project(tmp_path / "legacy-root")
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text("{not read by user enable", encoding="utf-8")
    tracking = TrackingStore()
    tracking.set_installation(
        InstallScope.PROJECT.value,
        Installation(
            scope=InstallScope.PROJECT.value,
            project_path=str(root),
            mode=InstallMode.COPY.value,
            profile=InstallProfile.STANDARD.value,
            modules_enabled=[InstallModule.HOOKS.value],
            installed_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ),
        str(root),
    )
    env = _env(tmp_path, _forge_home())
    env["FORGE_FAKE_RECORD"] = str(record_path)

    before = _run_dispatcher(dispatcher, root, env)
    assert before.returncode == 0
    assert not record_path.exists()

    monkeypatch.setattr(
        "forge.install.hook_dispatcher.find_current_forge_binary",
        lambda **_kwargs: fake_forge,
    )
    monkeypatch.setattr(
        "forge.install.version.check_minimum_version",
        lambda: type("Check", (), {"ok": True})(),
    )
    monkeypatch.setattr("forge.install.installer._codex_available", lambda: False)
    enabled = CliRunner().invoke(extensions, ["enable", "--scope", "user", "--profile", "standard"])

    assert enabled.exit_code == 0, enabled.output
    assert "Legacy hook cleanup candidates" in enabled.output
    assert "cleanup-project --root" in enabled.output
    assert not _lookup(root)
    after = _run_dispatcher(dispatcher, root, env)
    assert after.returncode == 0
    assert not record_path.exists()


def test_cli_sync_rerenders_stale_dispatcher(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from click.testing import CliRunner

    from forge.cli.extensions import extensions

    fake_forge, _record_path = _make_fake_forge(tmp_path)
    monkeypatch.setattr(
        "forge.install.hook_dispatcher.find_current_forge_binary",
        lambda **_kwargs: fake_forge,
    )
    monkeypatch.setattr(
        "forge.install.version.check_minimum_version",
        lambda: type("Check", (), {"ok": True})(),
    )
    runner = CliRunner()

    enable = runner.invoke(extensions, ["enable", "--scope", "user", "--profile", "minimal"])
    assert enable.exit_code == 0, enable.output

    dispatcher = get_hook_dispatcher_path()
    dispatcher.write_text(render_dispatcher_script(version="0.0.0-old"), encoding="utf-8")
    assert diagnose_hook_dispatcher().status == "stale"

    sync = runner.invoke(extensions, ["sync", "--scope", "user"])

    assert sync.exit_code == 0, sync.output
    assert diagnose_hook_dispatcher().status == "current"
