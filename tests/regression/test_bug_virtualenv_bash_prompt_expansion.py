"""GHSA-cx6f-vjhg-g3cc: later Bash prompt expansion must not execute virtualenv prompt text."""

from __future__ import annotations

import os
import pty
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("transition", ["promptvars", "posix", "child"])
def test_virtualenv_prompt_stays_literal_after_expansion_is_enabled(tmp_path: Path, transition: str) -> None:
    bash = shutil.which("bash")
    assert bash is not None, "The supported POSIX test environment requires Bash"
    marker = tmp_path / "unexpected-prompt-execution"
    environment = tmp_path / "environment"
    # The payload only writes a marker inside this test's temporary directory.
    prompt = f"x$(printf executed > {shlex.quote(str(marker))})y"
    created = subprocess.run(
        [
            sys.executable,
            "-m",
            "virtualenv",
            "--no-seed",
            "--no-periodic-update",
            "--app-data",
            str(tmp_path / "app-data"),
            "--activators",
            "bash",
            "--prompt",
            prompt,
            str(environment),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    after = {
        "promptvars": "shopt -s promptvars",
        "posix": "set -o posix",
        "child": f"export PS1\nexec {shlex.quote(bash)} --noprofile --norc -i",
    }[transition]
    rcfile = tmp_path / "bashrc"
    rcfile.write_text(f"shopt -u promptvars\nsource {shlex.quote(str(environment / 'bin/activate'))}\n{after}\n")
    env = dict(os.environ)
    for key in ("BASH_ENV", "ENV", "PROMPT_COMMAND", "BASHOPTS", "SHELLOPTS", "PS1", "VIRTUAL_ENV_DISABLE_PROMPT"):
        env.pop(key, None)
    master, slave = pty.openpty()
    try:
        with subprocess.Popen(
            [bash, "--noprofile", "--rcfile", str(rcfile), "-i"],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
        ) as shell:
            os.write(master, b"exit\n")
            try:
                assert shell.wait(timeout=10) == 0
            finally:
                if shell.poll() is None:
                    shell.kill()
                    shell.wait()
    finally:
        os.close(master)
        os.close(slave)
    assert not marker.exists(), "Bash executed the caller-supplied virtualenv prompt"
