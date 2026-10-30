"""CI must refuse interpreter drift before executing test bodies."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression
ROOT = Path(__file__).resolve().parents[2]
CURRENT = f"{sys.version_info.major}.{sys.version_info.minor}"


@pytest.mark.parametrize("mismatch", ["controller", "worker"])
def test_interpreter_mismatch_refuses_before_test_execution(tmp_path: Path, mismatch: str) -> None:
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "test_probe.py").write_text("from pathlib import Path\ndef test_probe(): Path('test-ran').touch()\n")
    args = []
    expected = "0.0"
    if mismatch == "worker":
        expected = CURRENT
        args = ["-p", "xdist.plugin", "-n", "2"]
        (tmp_path / "conftest.py").write_text(
            "import pytest\n"
            "@pytest.hookimpl(tryfirst=True)\n"
            "def pytest_testnodeready(node):\n"
            "    node.workerinfo['version_info'] = (0, 0, 0, 'final', 0)\n"
        )
    report = tmp_path / "evidence.json"
    # A failed attempt must replace old success evidence before tests can run.
    report.write_text('{"exitstatus": 0, "collection_complete": true}\n')
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.fixtures.python_matrix",
            *args,
            "--expected-python",
            expected,
            "--python-evidence",
            str(report),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTEST_ADDOPTS": "",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONPATH": str(ROOT),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 4, result.stdout + result.stderr
    assert "expected Python" in result.stdout + result.stderr
    assert not (tmp_path / "test-ran").exists()
    evidence = json.loads(report.read_text())
    assert evidence["exitstatus"] == 4
    assert evidence["collection_complete"] is False
    assert evidence["errors"]
