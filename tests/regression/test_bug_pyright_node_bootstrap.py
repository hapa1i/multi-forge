"""The Pyright hook must not download Node when the host runtime is missing."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.regression
ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts/run-pyright.py"


def test_missing_node_refuses_without_installing(tmp_path):
    binary = tmp_path / "bin"
    binary.mkdir()
    marker = tmp_path / "installer-was-run"
    for name in ("npm", "npx", "nodeenv"):
        installer = binary / name
        installer.write_text('#!/bin/sh\nprintf attempted > "$INSTALLER_MARKER"\n')
        installer.chmod(0o700)
    result = subprocess.run(
        [sys.executable, str(LAUNCHER), "--version"],
        env={**os.environ, "PATH": str(binary), "INSTALLER_MARKER": str(marker)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "Install a reviewed Node.js release on PATH" in result.stderr
    assert result.stdout == ""
    assert not marker.exists()


@pytest.mark.parametrize("exit_code", [0, 7])
def test_bundled_entry_arguments_and_exit_are_forwarded(tmp_path, exit_code):
    binary = tmp_path / "bin"
    binary.mkdir()
    node = binary / "node"
    node.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGUMENT_LOG"\nexit "$NODE_EXIT"\n')
    node.chmod(0o700)
    arguments = ["--project", "project with spaces", "--outputjson"]
    log = tmp_path / "arguments"
    result = subprocess.run(
        [sys.executable, str(LAUNCHER), *arguments],
        env={**os.environ, "PATH": str(binary), "ARGUMENT_LOG": str(log), "NODE_EXIT": str(exit_code)},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == exit_code, result.stderr
    forwarded = log.read_text().splitlines()
    assert Path(forwarded[0]).is_file()
    assert forwarded[0].endswith("pyright/dist/index.js")
    assert forwarded[1:] == arguments


def test_missing_bundled_entry_refuses_without_fallback(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("run_pyright", LAUNCHER)
    assert spec is not None and spec.loader is not None
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/existing/node")
    monkeypatch.setattr(
        launcher.importlib.metadata,
        "distribution",
        lambda name: SimpleNamespace(locate_file=lambda path: tmp_path / "missing.js"),
    )

    def unexpected_execution(*args):
        pytest.fail("A missing bundled entry must not execute another command")

    monkeypatch.setattr(launcher.os, "execv", unexpected_execution)
    assert launcher.main() == 2
    assert "missing its bundled JavaScript entry point" in capsys.readouterr().err
