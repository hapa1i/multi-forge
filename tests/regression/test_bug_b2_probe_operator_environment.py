"""B2: second-terminal commands must retain isolation and fail cleanly on missing configuration."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

import pytest

from tests.fixtures.codex_probe import PROBES, load_script

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("missing", ["CODEX_HOME", "PROBE_TURN_CEILING"])
def test_missing_environment_refuses_without_traceback_or_subprocess(tmp_path, missing):
    login = load_script("probe-home").prepare_home(tmp_path / "codex-home")
    marker = tmp_path / "launched"
    binary = tmp_path / "codex"
    binary.write_text(f'#!/bin/sh\ntouch "{marker}"\necho "Logged in using ChatGPT"\n')
    binary.chmod(0o700)
    identity = tmp_path / "identity.json"
    identity.write_text(
        json.dumps({"retained_path": str(binary), "sha256": hashlib.sha256(binary.read_bytes()).hexdigest()})
    )
    env = {"HOME": str(tmp_path), "PATH": os.environ["PATH"], "CODEX_HOME": str(login), "PROBE_TURN_CEILING": "1"}
    del env[missing]
    result = subprocess.run(
        [
            sys.executable,
            str(PROBES / "probe-runtime.py"),
            "codex",
            "--identity",
            str(identity),
            "--",
            "exec",
            "SYNTHETIC",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert missing in result.stderr and "clean round launcher" in result.stderr
    assert "Traceback" not in result.stderr
    assert not marker.exists()
    assert not (tmp_path / "turns.jsonl").exists()


def test_operator_command_uses_clean_launcher_and_restores_project_directory(tmp_path):
    project = tmp_path / "project with spaces"
    project.mkdir()
    binary = tmp_path / "bin"
    binary.mkdir()
    (binary / "codex").write_text(
        f"#!{sys.executable}\nimport json, os\n"
        "print(json.dumps({'cwd': os.getcwd(), 'ceiling': os.environ.get('PROBE_TURN_CEILING'), "
        "'home': os.environ.get('CODEX_HOME'), 'dev': os.environ.get('FORGE_DEV'), "
        "'forge_home': os.environ.get('FORGE_HOME'), 'paid': 'ANTHROPIC_API_KEY' in os.environ}))\n"
    )
    (binary / "codex").chmod(0o700)
    launcher = tmp_path / "clean launcher"
    launcher.write_text(f'#!/bin/bash\ncd /\nexec env -i PATH="{binary}:/usr/bin:/bin" PROBE_TURN_CEILING=9 "$@"\n')
    launcher.chmod(0o700)
    env = dict(
        os.environ,
        PROBE_LAUNCHER=str(launcher),
        REPO_ROOT=str(tmp_path / "checkout"),
        CODEX_HOME=str(tmp_path / "login"),
        FORGE_HOME=str(tmp_path / "forge"),
    )
    printed = subprocess.run(
        ["/bin/bash", "-c", 'source "$1/lib.sh"; product_trust_command "$2"', "probe", str(PROBES), str(project)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    result = subprocess.run(
        ["/bin/bash", "-c", printed.stdout],
        env={**env, "ANTHROPIC_API_KEY": "synthetic-must-be-stripped"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "cwd": str(project.resolve()),
        "ceiling": "9",
        "home": env["CODEX_HOME"],
        "dev": env["REPO_ROOT"],
        "forge_home": env["FORGE_HOME"],
        "paid": False,
    }
