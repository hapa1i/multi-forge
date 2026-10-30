"""Wheel smoke cleanup must finish backend teardown before deleting its environment."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from textwrap import dedent

import pytest

pytestmark = pytest.mark.regression
SCRIPT = Path(__file__).resolve().parents[2] / "scripts/test-wheel-runtime.sh"


def _wait_for(path: Path, process: subprocess.Popen[str] | None = None) -> None:
    deadline = time.monotonic() + 5
    while not path.exists():
        if process is not None and process.poll() is not None:
            raise AssertionError(f"process exited before {path.name}")
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {path.name}")
        time.sleep(0.01)


def _group_has_live_members(group_id: int) -> bool:
    snapshot = subprocess.run(["ps", "-axo", "pgid=,stat="], capture_output=True, text=True, check=True, timeout=2)
    return any(
        int(pgid) == group_id and not state.startswith("Z")
        for pgid, state in (line.split() for line in snapshot.stdout.splitlines())
    )


@pytest.fixture
def smoke(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    smoke_temps = tmp_path / "smoke"
    smoke_temps.mkdir()
    programs = {
        "uv": """\
            import os, shutil, sys
            from pathlib import Path
            args = sys.argv[1:]
            if args[0] == 'build':
                (Path(args[args.index('--out-dir') + 1]) / 'multi_forge-test.whl').touch()
            elif args[0] == 'venv':
                directory = Path(args[-1]) / 'bin'
                directory.mkdir(parents=True)
                for name in ('python', 'forge'):
                    shutil.copy(Path(os.environ['SMOKE_TEST_ROOT']) / 'bin' / name, directory / name)
            """,
        "python": f"""\
            import os, sys
            if sys.argv[1] != '-c':
                os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])
            """,
        "forge": """\
            import json, os, signal, sys
            from pathlib import Path
            root = Path(os.environ['SMOKE_TEST_ROOT'])
            home = Path(os.environ['FORGE_HOME'])
            group_id = int(os.environ.get('SMOKE_TEST_GROUP', '2147483647'))
            if sys.argv[3] == 'start':
                registry = home / 'backends/index.json'
                registry.parent.mkdir(parents=True, exist_ok=True)
                registry.write_text(json.dumps({'version': 2, 'processes': {'litellm-49178': {
                    'process_id': 'litellm-49178', 'adapter_type': 'litellm', 'port': 49178, 'pid': group_id,
                }}}))
                (root / 'smoke-root').write_text(str(home.parent))
                log = home / 'logs/backend/litellm-49178.log'
                log.parent.mkdir(parents=True)
                log.write_text('backend diagnostic\\n')
                sys.exit(int(os.environ.get('SMOKE_TEST_START_STATUS', '0')))
            elif sys.argv[3] == 'stop':
                print('backend stop diagnostic', file=sys.stderr)
                status = int(os.environ.get('SMOKE_TEST_STOP_STATUS', '0'))
                if status:
                    sys.exit(status)
                if 'SMOKE_TEST_GROUP' in os.environ:
                    os.killpg(group_id, signal.SIGTERM)
                (home / 'backends/index.json').unlink()
                (root / 'stopped').touch()
            """,
        "curl": "pass\n",
        "ps": f"""\
            import os, subprocess, sys
            from pathlib import Path
            result = subprocess.run([{shutil.which('ps')!r}, *sys.argv[1:]], capture_output=True, timeout=2)
            sys.stdout.buffer.write(result.stdout)
            Path(os.environ['SMOKE_TEST_ROOT'], 'polled').touch()
            sys.exit(result.returncode)
            """,
        "rm": """\
            import os, shutil, sys
            from pathlib import Path
            root = Path(os.environ['SMOKE_TEST_ROOT'])
            (root / 'removal-entered').touch()
            if 'SMOKE_TEST_GROUP' in os.environ and not (root / 'writer-done').exists():
                print('removal raced the backend writer', file=sys.stderr)
                sys.exit(17)
            status = int(os.environ.get('SMOKE_TEST_REMOVE_STATUS', '0'))
            if status:
                print('removal diagnostic', file=sys.stderr)
                sys.exit(status)
            shutil.rmtree(sys.argv[-1])
            """,
    }
    for name, program in programs.items():
        executable = fake_bin / name
        executable.write_text(f"#!{sys.executable}\n" + dedent(program))
        executable.chmod(0o755)
    return tmp_path, {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "TMPDIR": str(smoke_temps),
        "FORGE_WHEEL_SMOKE_PORT": "49178",
        "SMOKE_TEST_ROOT": str(tmp_path),
    }


def test_cleanup_waits_for_group_child_before_removing_venv(smoke: tuple[Path, dict[str, str]]) -> None:
    root, env = smoke
    writer = root / "writer.py"
    writer.write_text(dedent("""\
        import signal, sys, time
        from pathlib import Path
        root = Path(sys.argv[1])
        signal.signal(signal.SIGTERM, lambda *_: None)
        (root / 'writer-ready').touch()
        while not (root / 'release-writer').exists():
            time.sleep(0.01)
        site = Path((root / 'smoke-root').read_text()) / 'venv/lib/site-packages'
        site.mkdir(parents=True, exist_ok=True)
        (site / 'late-write').touch()
        (root / 'writer-done').touch()
        """))
    leader = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import subprocess,sys,time; subprocess.Popen(sys.argv[1:]); time.sleep(30)",
            sys.executable,
            str(writer),
            str(root),
        ],
        start_new_session=True,
        text=True,
    )
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], text=True)
    script = None
    try:
        _wait_for(root / "writer-ready")
        script = subprocess.Popen(
            ["bash", str(SCRIPT)],
            env={**env, "SMOKE_TEST_GROUP": str(leader.pid)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_for(root / "stopped", script)
        # Keep the exited leader unreaped so its group id cannot be reused before final cleanup.
        deadline = time.monotonic() + 5
        while True:
            state = subprocess.run(
                ["ps", "-p", str(leader.pid), "-o", "stat="],
                capture_output=True,
                text=True,
                check=True,
                timeout=2,
            )
            if state.stdout.strip().startswith("Z"):
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        deadline = time.monotonic() + 5
        while not (root / "polled").exists() and not (root / "removal-entered").exists():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        (root / "release-writer").touch()
        stdout, stderr = script.communicate(timeout=10)
        assert script.returncode == 0, stdout + stderr
        assert (root / "writer-done").exists()
        assert not list((root / "smoke").iterdir())
        assert sentinel.poll() is None
    finally:
        (root / "release-writer").touch()
        if script is not None and script.poll() is None:
            script.kill()
            script.wait(timeout=5)
        try:
            if _group_has_live_members(leader.pid):
                try:
                    os.killpg(leader.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    # macOS can report EPERM if the last live member just became a zombie.
                    if _group_has_live_members(leader.pid):
                        raise
        finally:
            leader.wait(timeout=5)
            sentinel.terminate()
            sentinel.wait(timeout=5)


@pytest.mark.parametrize("start_status", [0, 23])
@pytest.mark.parametrize("failure", ["STOP", "REMOVE"])
def test_cleanup_failure_retains_diagnostics_and_original_status(
    smoke: tuple[Path, dict[str, str]],
    start_status: int,
    failure: str,
) -> None:
    root, env = smoke
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env={**env, "SMOKE_TEST_START_STATUS": str(start_status), f"SMOKE_TEST_{failure}_STATUS": "19"},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == (start_status or (1 if failure == "STOP" else 19))
    assert "backend stop diagnostic" in result.stderr
    assert "backend diagnostic" in result.stderr
    assert "retained evidence" in result.stderr
    assert list((root / "smoke").iterdir())
    if failure == "STOP":
        assert "backend stop exited with status 19" in result.stderr
        assert not (root / "removal-entered").exists()


@pytest.fixture
def cleanup_helper():
    spec = importlib.util.spec_from_file_location("wheel_smoke_cleanup", SCRIPT.with_name("wheel-smoke-cleanup.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _registry(root: Path, pid: int | None) -> Path:
    registry = root / "backends/index.json"
    registry.parent.mkdir()
    registry.write_text(
        json.dumps(
            {
                "version": 2,
                "processes": {
                    "litellm-49178": {
                        "process_id": "litellm-49178",
                        "adapter_type": "litellm",
                        "port": 49178,
                        "pid": pid,
                    }
                },
            }
        )
    )
    return registry


def test_stop_timeout_is_bounded_and_preserves_registry(tmp_path: Path, cleanup_helper, monkeypatch) -> None:
    registry = _registry(tmp_path, 2147483647)
    forge = tmp_path / "forge"
    forge.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
    forge.chmod(0o755)
    monkeypatch.setattr(cleanup_helper, "STOP_TIMEOUT", 0.1)
    with pytest.raises(subprocess.TimeoutExpired):
        cleanup_helper.stop_and_wait(tmp_path, forge, 49178)
    assert registry.exists()


def test_zombie_only_owned_group_does_not_wait_for_unrelated_process(
    tmp_path: Path, cleanup_helper, monkeypatch
) -> None:
    _registry(tmp_path, 543210)

    def run(args, **kwargs):
        snapshot = "101 543210 Z\n102 543210 Z+\n103 543211 S\n" if args[0] == "ps" else ""
        return subprocess.CompletedProcess(args, 0, stdout=snapshot)

    monkeypatch.setattr(cleanup_helper.subprocess, "run", run)
    cleanup_helper.stop_and_wait(tmp_path, tmp_path / "forge", 49178)


@pytest.mark.parametrize("pid", [None, 0, -1, True])
def test_unowned_registry_refuses_before_stop(tmp_path: Path, cleanup_helper, pid) -> None:
    registry = _registry(tmp_path, pid)
    with pytest.raises(ValueError, match="cannot verify"):
        cleanup_helper.stop_and_wait(tmp_path, tmp_path / "must-not-run", 49178)
    assert registry.exists()


def test_live_group_timeout_and_inspection_error_preserve_evidence(tmp_path: Path, cleanup_helper, monkeypatch) -> None:
    registry = _registry(tmp_path, os.getpgrp())
    forge = tmp_path / "forge"
    forge.write_text("#!/bin/sh\nexit 0\n")
    forge.chmod(0o755)
    monkeypatch.setattr(cleanup_helper, "EXIT_TIMEOUT", 0.1)
    with pytest.raises(TimeoutError, match="still has live members"):
        cleanup_helper.stop_and_wait(tmp_path, forge, 49178)
    assert registry.exists()
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(FileNotFoundError):
        cleanup_helper.stop_and_wait(tmp_path, forge, 49178)
    assert registry.exists()
