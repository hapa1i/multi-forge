"""A non-GNU timeout hid Ubuntu's separately named GNU binary from the probe owner."""

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures.codex_probe import PROBES, load_script

pytestmark = pytest.mark.regression


@pytest.fixture
def timeout_path(tmp_path, monkeypatch):
    binary = shutil.which("gtimeout") or shutil.which("gnutimeout") or shutil.which("timeout")
    assert binary and "GNU coreutils" in subprocess.check_output([binary, "--version"], text=True)
    process_list = shutil.which("ps")
    assert process_list
    directory = tmp_path / "bin"
    directory.mkdir()
    (directory / "ps").symlink_to(process_list)
    marker = tmp_path / "wrong-timeout-ran"
    for name in ("timeout", "gtimeout", "gnutimeout"):
        path = directory / name
        path.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = --version ]; then\n'
            "  printf '%s\\n' 'timeout (uutils coreutils) 0.10.0'\n"
            "else\n"
            f"  printf wrong > {shlex.quote(str(marker))}\n"
            "  exit 99\n"
            "fi\n"
        )
        path.chmod(0o700)
    monkeypatch.setenv("PATH", str(directory))
    return directory, binary, marker


def _run(harness: str, evidence: Path) -> int:
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    if harness == "python":
        return load_script("probe-runtime").bounded_run(command, evidence, seconds=0.25, grace=0.2)
    return subprocess.run(
        [
            "/bin/bash",
            "-c",
            'source "$1/lib.sh"; shift; PROBE_TURN_TIMEOUT=0.25s PROBE_KILL_GRACE=0.2 with_timeout "$@"',
            "probe",
            str(PROBES),
            *command,
        ],
        capture_output=True,
        text=True,
        timeout=5,
    ).returncode


@pytest.mark.parametrize("harness", ["python", "shell"])
@pytest.mark.parametrize("name", ["timeout", "gtimeout", "gnutimeout"])
def test_probe_finds_gnu_timeout_among_other_implementations(tmp_path, timeout_path, harness, name):
    directory, binary, marker = timeout_path
    (directory / name).write_text(f'#!/bin/sh\nexec {shlex.quote(binary)} "$@"\n')
    assert _run(harness, tmp_path / "evidence") == 124
    assert not marker.exists()


@pytest.mark.parametrize("harness", ["python", "shell"])
def test_probe_refuses_when_every_timeout_is_non_gnu(tmp_path, timeout_path, harness):
    _, _, marker = timeout_path
    if harness == "python":
        with pytest.raises(ValueError, match="GNU timeout is required"):
            _run(harness, tmp_path / "evidence")
        assert not (tmp_path / "evidence").exists()
    else:
        assert _run(harness, tmp_path / "evidence") != 0
    assert not marker.exists()
