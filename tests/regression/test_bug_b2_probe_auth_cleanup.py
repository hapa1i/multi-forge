"""B2: stage 84 teardown must preserve the independently refreshed login."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests.fixtures.codex_probe import PROBES, load_script

pytestmark = pytest.mark.regression


def test_cross_project_stage_preserves_independent_login(tmp_path):
    """Run the full stage, including its EXIT trap, without network or model calls."""
    home = tmp_path / "home"
    home.mkdir()
    login = load_script("probe-home").prepare_home(tmp_path / "codex-home")
    (login / "auth.json").write_text('{"fixture": "refreshed"}')
    capture = tmp_path / "captures"
    binary = tmp_path / "bin"
    binary.mkdir()
    codex = binary / "codex"
    codex.write_text(
        f"#!{sys.executable}\n"
        "import json, os, subprocess, sys, tomllib\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "if args == ['--version']: print('codex-cli 0.161.0')\n"
        "elif args == ['login', 'status']: print('Logged in using ChatGPT')\n"
        "elif args[0] == 'exec':\n"
        " cfg = tomllib.loads((Path(os.environ['CODEX_HOME'])/'config.toml').read_text())\n"
        " for row in cfg['hooks']['SessionStart']:\n"
        "  for hook in row['hooks']:\n"
        "   subprocess.run([hook['command']], input=json.dumps({'hook_event_name':'SessionStart',"
        "'session_id':'fixture-thread','cwd':os.getcwd()}), text=True, check=True)\n"
        " Path(args[args.index('-o')+1]).write_text('OK')\n"
        " print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}))\n"
        "else: raise SystemExit(2)\n"
    )
    codex.chmod(0o700)
    env = {
        "HOME": str(home),
        "PATH": str(binary) + os.pathsep + os.environ["PATH"],
        "PROBE_CODEX_HOME": str(login),
        "CODEX_HOOKS_CAPTURE_DIR": str(capture),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    prepare = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'source "$1/lib.sh"; fixture_init setup; fixture_build; '
            "fixture_register_user; fixture_tee_all; fixture_mark_enrolled fixture",
            "probe",
            str(PROBES),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    result = subprocess.run(
        ["/bin/bash", str(PROBES / "stages/84-fresh-project.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, prepare.stdout + result.stdout + result.stderr
    assert "CROSS-PROJECT-TRUST-SCOPED" in result.stdout
    assert (login / "auth.json").read_text() == '{"fixture": "refreshed"}'
