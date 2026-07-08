"""Tests for the user-scope hook dispatcher artifact."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from forge.install.hook_dispatcher import (
    diagnose_hook_dispatcher,
    dispatcher_source_sha256,
    get_hook_dispatcher_path,
    get_runtime_metadata_path,
    install_hook_dispatcher,
    normalize_dispatcher_command_home,
    parse_dispatcher_stamp,
    read_runtime_metadata,
    render_dispatcher_command,
    render_dispatcher_script,
    write_runtime_metadata,
)
from forge.install.project_registry import ProjectRegistryStore

PHASE0_NOOP_P95_CEILING_MS = 30.0


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
    hook_name: str = "session-start",
    stdin: str = "{}",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(dispatcher), hook_name],
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
    assert _read_fake_record(record_path)["argv"] == [str(fake_forge), "hook", "session-start"]


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
    assert _read_fake_record(record_path)["argv"] == [str(fake_forge), "hook", "session-start"]


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


def test_noop_path_stays_under_phase0_ceiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    samples: list[float] = []
    for _ in range(5):
        start = time.perf_counter()
        result = _run_dispatcher(dispatcher, cwd, env)
        samples.append((time.perf_counter() - start) * 1000)
        assert result.returncode == 0, result.stderr

    assert not record_path.exists()
    assert max(samples) < PHASE0_NOOP_P95_CEILING_MS


def test_install_hook_dispatcher_records_path_from_which(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_forge, _record_path = _make_fake_forge(tmp_path)

    def which(command: str, path: str | None = None) -> str | None:
        assert command == "forge"
        assert path == "/usr/bin:/bin"
        return str(fake_forge)

    install_hook_dispatcher(environ={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}, which=which)

    metadata = read_runtime_metadata()
    assert metadata is not None
    assert metadata["forge_binary_path"] == str(fake_forge)


def test_cli_enable_renders_dispatcher_after_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from click.testing import CliRunner

    from forge.cli.extensions import extensions

    fake_forge, _record_path = _make_fake_forge(tmp_path)

    monkeypatch.setattr("forge.install.hook_dispatcher.find_current_forge_binary", lambda **_kwargs: fake_forge)
    monkeypatch.setattr("forge.install.version.check_minimum_version", lambda: type("Check", (), {"ok": True})())

    result = CliRunner().invoke(extensions, ["enable", "--scope", "user", "--profile", "minimal"])

    assert result.exit_code == 0, result.output
    assert get_hook_dispatcher_path().is_file()
    metadata = read_runtime_metadata()
    assert metadata is not None
    assert metadata["forge_binary_path"] == str(fake_forge)


def test_cli_sync_rerenders_stale_dispatcher(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from click.testing import CliRunner

    from forge.cli.extensions import extensions

    fake_forge, _record_path = _make_fake_forge(tmp_path)
    monkeypatch.setattr("forge.install.hook_dispatcher.find_current_forge_binary", lambda **_kwargs: fake_forge)
    monkeypatch.setattr("forge.install.version.check_minimum_version", lambda: type("Check", (), {"ok": True})())
    runner = CliRunner()

    enable = runner.invoke(extensions, ["enable", "--scope", "user", "--profile", "minimal"])
    assert enable.exit_code == 0, enable.output

    dispatcher = get_hook_dispatcher_path()
    dispatcher.write_text(render_dispatcher_script(version="0.0.0-old"), encoding="utf-8")
    assert diagnose_hook_dispatcher().status == "stale"

    sync = runner.invoke(extensions, ["sync", "--scope", "user"])

    assert sync.exit_code == 0, sync.output
    assert diagnose_hook_dispatcher().status == "current"
