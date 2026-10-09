"""Offline guards for the real-runtime experiment; these make no model calls."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from tests.fixtures.codex_probe import PROBES, load_script


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
