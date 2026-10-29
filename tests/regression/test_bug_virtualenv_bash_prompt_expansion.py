"""GHSA-cx6f-vjhg-g3cc: later Bash prompt expansion must not execute virtualenv prompt text."""

from __future__ import annotations

import errno
import os
import pty
import select
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("transition", ["promptvars", "posix", "child"])
def test_virtualenv_prompt_stays_literal_after_expansion_is_enabled(
    tmp_path: Path, transition: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    bash = shutil.which("bash")
    assert bash is not None, "The supported POSIX test environment requires Bash"
    marker = tmp_path / "unexpected-prompt-execution"
    environment = tmp_path / "environment"
    inherited_history = tmp_path / "inherited-history"
    original_history = "".join(f"echo history-{index}\n" for index in range(2000))
    inherited_history.write_text(original_history)
    monkeypatch.setenv("HISTFILE", str(inherited_history))
    monkeypatch.setenv("HISTSIZE", "500")
    monkeypatch.setenv("HISTFILESIZE", "500")
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
        "child": f"export PS1\nexec {shlex.quote(bash)} --noprofile --norc --noediting -i",
    }[transition]
    rcfile = tmp_path / "bashrc"
    rcfile.write_text(
        f"shopt -u promptvars\nsource {shlex.quote(str(environment / 'bin/activate'))} || exit 1\n{after}\n"
    )
    env = dict(os.environ)
    for key in ("BASH_ENV", "ENV", "PROMPT_COMMAND", "BASHOPTS", "SHELLOPTS", "PS1", "VIRTUAL_ENV_DISABLE_PROMPT"):
        env.pop(key, None)
    env["HISTFILE"] = str(tmp_path / "shell-history")
    master, slave = pty.openpty()
    output = bytearray()
    with os.fdopen(master, "rb", buffering=0) as terminal, os.fdopen(slave, "wb", buffering=0) as child_terminal:
        with subprocess.Popen(
            # Readline can truncate a long prompt to the PTY width, hiding the payload from the assertion.
            [bash, "--noprofile", "--norc", "--noediting", "-i"],
            stdin=child_terminal,
            stdout=child_terminal,
            stderr=child_terminal,
            env=env,
        ) as shell:
            # Closing our slave handle allows EOF once Bash has drained its output and exited.
            child_terminal.close()
            # Source only our setup after startup, avoiding system bashrc prompt and history overrides.
            os.write(master, f"source {shlex.quote(str(rcfile))}\nexit\n".encode())
            deadline = time.monotonic() + 10
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not select.select([terminal], [], [], remaining)[0]:
                        raise subprocess.TimeoutExpired(shell.args, 10, output=bytes(output))
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        break  # Linux reports PTY closure as EIO instead of an empty read.
                    if not chunk:
                        break
                    output.extend(chunk)
                assert shell.wait(timeout=max(0.001, deadline - time.monotonic())) == 0, output.decode(errors="replace")
            finally:
                if shell.poll() is None:
                    shell.kill()
                    shell.wait()
    assert not marker.exists(), "Bash executed the caller-supplied virtualenv prompt"
    # Virtualenv uses Bash's \$ prompt escape, which renders as # for root.
    rendered_prompt = prompt.replace("$", "#") if os.geteuid() == 0 else prompt
    assert rendered_prompt.encode() in output, "Bash never rendered the literal payload prompt:\n" + output.decode(
        errors="replace"
    )
    assert inherited_history.read_text() == original_history, "Bash modified the inherited history file"
