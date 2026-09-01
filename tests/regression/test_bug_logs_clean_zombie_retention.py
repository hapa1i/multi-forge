"""Regression: defunct processes must not retain Forge log shards."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

import forge.cli.logs as logs
from forge.cli.main import main
from forge.core.paths import get_forge_home

pytestmark = pytest.mark.regression


def test_zombie_process_does_not_pin_proxy_request_and_tool_logs(tmp_path, monkeypatch) -> None:
    pid = 424242
    proc_root = tmp_path / "proc"
    proc_dir = proc_root / str(pid)
    proc_dir.mkdir(parents=True)
    (proc_dir / "stat").write_text(f"{pid} (forge proxy worker) Z 1 2 3\n")
    monkeypatch.setattr(logs, "_PROC_ROOT", proc_root)
    monkeypatch.setattr(logs.os, "kill", lambda *_args: None)

    logs_root = get_forge_home() / "logs"
    paths = (
        logs_root / "proxy" / f"proxy.{pid}.log",
        logs_root / "requests" / f"20260830_proxy.{pid}.jsonl",
        logs_root / "tool_events" / f"20260830_proxy.{pid}.jsonl",
    )
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("cannot grow\n")

    result = CliRunner().invoke(main, ["logs", "clean", "--yes"])

    assert result.exit_code == 0
    assert "Removed 3 log files" in result.output
    assert all(not path.exists() for path in paths)
