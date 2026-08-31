"""Regression: arbitrary Linux task-name bytes must not abort log cleanup."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

import forge.cli.logs as logs
from forge.cli.main import main
from forge.core.paths import get_forge_home

pytestmark = pytest.mark.regression


def test_non_utf8_live_and_zombie_process_names_are_classified_without_decoding(tmp_path, monkeypatch) -> None:
    proc_root = tmp_path / "proc"
    live_pid = 515151
    zombie_pid = 515152
    for pid, state in ((live_pid, b"R"), (zombie_pid, b"Z")):
        proc_dir = proc_root / str(pid)
        proc_dir.mkdir(parents=True)
        (proc_dir / "stat").write_bytes(str(pid).encode() + b" (\xffforge) " + state + b" 1 2 3\n")
    monkeypatch.setattr(logs, "_PROC_ROOT", proc_root)
    monkeypatch.setattr(logs.os, "kill", lambda *_args: None)

    log_dir = get_forge_home() / "logs" / "proxy"
    log_dir.mkdir(parents=True)
    live_log = log_dir / f"proxy.{live_pid}.log"
    zombie_log = log_dir / f"proxy.{zombie_pid}.log"
    live_log.write_text("active\n", encoding="utf-8")
    zombie_log.write_text("defunct\n", encoding="utf-8")

    result = CliRunner().invoke(main, ["logs", "clean", "--yes"])

    assert result.exit_code == 0
    assert live_log.is_file()
    assert not zombie_log.exists()
