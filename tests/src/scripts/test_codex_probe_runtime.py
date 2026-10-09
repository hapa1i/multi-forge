"""Offline guards for the real-runtime experiment; these make no model calls."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROBES = Path(__file__).resolve().parents[3] / "scripts/experiments/codex-hooks"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), PROBES / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_login_refuses_unowned_or_symlinked_home(tmp_path):
    homes = load_script("probe-home")
    unowned = tmp_path / "unowned"
    unowned.mkdir()
    auth = unowned / "auth.json"
    auth.write_text('{"fixture": "unchanged"}')
    with pytest.raises(ValueError, match="not owned"):
        homes.prepare_home(unowned)
    link = tmp_path / "linked"
    link.symlink_to(unowned, target_is_directory=True)
    with pytest.raises(ValueError, match="canonical"):
        homes.prepare_home(link)
    assert auth.read_text() == '{"fixture": "unchanged"}'
    assert not (unowned / homes.MARKER).exists()


def test_probe_login_preserves_refreshed_credentials(tmp_path):
    homes = load_script("probe-home")
    owned = homes.prepare_home(tmp_path / "codex-home")
    (owned / "auth.json").write_text('{"fixture": "refreshed"}')
    homes.prepare_home(owned)
    assert (owned / "auth.json").read_text() == '{"fixture": "refreshed"}'


def test_budget_refuses_before_overrun(tmp_path):
    runtime = load_script("probe-runtime")
    ledger = tmp_path / "turns.jsonl"
    runtime.reserve_turn(ledger, 3, 2)
    with pytest.raises(ValueError, match="budget exhausted"):
        runtime.reserve_turn(ledger, 3, 2)
    runtime.reserve_turn(ledger, 3)
    assert sum(json.loads(line)["reserved_turns"] for line in ledger.read_text().splitlines()) == 3


@pytest.mark.regression
def test_missing_login_refuses_before_model_launch_or_quota_reservation(tmp_path, monkeypatch):
    runtime = load_script("probe-runtime")
    login = load_script("probe-home").prepare_home(tmp_path / "codex-home")
    binary = tmp_path / "codex"
    binary.write_text('#!/bin/sh\necho "Not logged in" >&2\nexit 1\n')
    binary.chmod(0o700)
    identity = tmp_path / "identity.json"
    identity.write_text(
        json.dumps({"retained_path": str(binary), "sha256": hashlib.sha256(binary.read_bytes()).hexdigest()})
    )
    for name in os.environ:
        if name.endswith("API_KEY") or name in {"CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL"}:
            monkeypatch.delenv(name)
    monkeypatch.setenv("CODEX_HOME", str(login))
    monkeypatch.setenv("PROBE_TURN_CEILING", "10")
    with pytest.raises(ValueError, match="ChatGPT login is unavailable"):
        runtime.codex_exec(identity, ["exec", "Reply OK"])
    assert not (tmp_path / "turns.jsonl").exists()


def test_signal_refuses_reused_pid(monkeypatch):
    runtime = load_script("probe-runtime")
    row = {"pid": 123, "started": "old"}
    monkeypatch.setattr(runtime, "process_table", lambda: {123: {"pid": 123, "started": "new"}})
    calls = []
    monkeypatch.setattr(runtime.os, "kill", lambda *args: calls.append(args))
    runtime.signal_owned([row], 15)
    assert calls == []


def test_outer_owner_kills_detached_term_resistant_descendant(tmp_path):
    runtime = load_script("probe-runtime")
    child = tmp_path / "detached.py"
    child.write_text(
        "import runpy, signal, time\n"
        f"r = runpy.run_path({str(PROBES / 'probe-runtime.py')!r})\n"
        "r['register_process']()\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(30)\n"
    )
    parent = tmp_path / "parent.py"
    parent.write_text(
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, {str(child)!r}], start_new_session=True)\n"
        "time.sleep(30)\n"
    )
    evidence = tmp_path / "evidence"
    result = runtime.bounded_run([sys.executable, str(parent)], evidence, seconds=1, grace=0.3)
    assert result == 124
    state = json.loads((evidence / "process-result.json").read_text())
    assert state["survivors_before_sweep"]
    assert state["kill_escalation"]
    assert not state["remaining"]
    assert state["elapsed_seconds"] < 5


def test_probe_shell_refuses_unbounded_fallback(tmp_path):
    # Source the function without invoking a stage. A PATH with no timeout must
    # not execute even this harmless sentinel command.
    marker = tmp_path / "ran"
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            'source "$1/lib.sh"; PATH=/nonexistent with_timeout /usr/bin/touch "$2"',
            "probe",
            str(PROBES),
            str(marker),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "refusing an unbounded probe" in result.stderr
    assert not marker.exists()


@pytest.mark.regression
def test_shell_probe_auth_rejects_not_logged_in_even_with_exit_zero(tmp_path):
    login = load_script("probe-home").prepare_home(tmp_path / "codex-home")
    (login / "auth.json").write_text('{"fixture": "stale"}')
    binary = tmp_path / "bin"
    binary.mkdir()
    codex = binary / "codex"
    codex.write_text('#!/bin/sh\necho "Not logged in"\n')
    codex.chmod(0o700)
    env = dict(
        os.environ,
        PATH=str(binary) + os.pathsep + os.environ["PATH"],
        PROBE_CODEX_HOME=str(login),
        CODEX_HOOKS_CAPTURE_DIR=str(tmp_path / "captures"),
    )
    result = subprocess.run(
        ["/bin/bash", "-c", 'source "$1/lib.sh"; fixture_init auth; probe_auth', "probe", str(PROBES)],
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert "Stop; no auth fallback" in result.stderr


@pytest.mark.regression
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
