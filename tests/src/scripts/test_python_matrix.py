"""Interpreter evidence must describe real pytest processes and selected tests."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CURRENT = f"{sys.version_info.major}.{sys.version_info.minor}"


@pytest.fixture
def run_pytest(tmp_path: Path):
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers = selected\n")
    (tmp_path / "test_sample.py").write_text(
        "import pytest\n"
        "@pytest.mark.selected\n"
        "def test_retained(): pass\n"
        "@pytest.mark.selected\n"
        "def test_filtered(): pass\n"
        "def test_unmarked(): pass\n"
    )

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PYTEST_ADDOPTS": "",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONPATH": str(ROOT),
        }
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "tests.fixtures.python_matrix", *args],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    return run


def test_options_omitted_leave_ordinary_pytest_unchanged(run_pytest, tmp_path: Path) -> None:
    result = run_pytest("-q")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed" in result.stdout
    assert "Python matrix" not in result.stdout
    assert not list(tmp_path.glob("*.json"))


def test_serial_evidence_records_selected_ids_and_preserves_duplicates(run_pytest, tmp_path: Path) -> None:
    report = tmp_path / "evidence" / "serial.json"
    result = run_pytest(
        "--expected-python",
        CURRENT,
        "--python-evidence",
        str(report),
        "-m",
        "selected",
        "-k",
        "retained",
        "test_sample.py",
        "test_sample.py",
        "--keep-duplicates",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(report.read_text())
    assert evidence["schema_version"] == 1
    assert evidence["expected_python"] == CURRENT
    assert evidence["controller"]["version"].startswith(CURRENT + ".")
    assert evidence["controller"]["executable"] == sys.executable
    assert evidence["node_ids"] == ["test_sample.py::test_retained"] * 2
    assert evidence["workers"] == {}
    assert evidence["collection_complete"] is True
    assert evidence["errors"] == []
    assert evidence["exitstatus"] == 0
    assert f"Python matrix controller: Python {evidence['controller']['version']}" in result.stdout


def test_xdist_evidence_records_each_real_worker_and_matching_collection(run_pytest, tmp_path: Path) -> None:
    report = tmp_path / "parallel.json"
    result = run_pytest(
        "-p",
        "xdist.plugin",
        "-n",
        "2",
        "--expected-python",
        CURRENT,
        "--python-evidence",
        str(report),
        "-m",
        "selected",
        "-k",
        "retained",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    evidence = json.loads(report.read_text())
    assert evidence["node_ids"] == ["test_sample.py::test_retained"]
    digest = hashlib.sha256(json.dumps(evidence["node_ids"], separators=(",", ":")).encode()).hexdigest()
    assert set(evidence["workers"]) == {"gw0", "gw1"}
    for worker, identity in evidence["workers"].items():
        assert identity["version"] == evidence["controller"]["version"]
        assert identity["executable"] == evidence["controller"]["executable"]
        assert identity["collected_count"] == 1
        assert identity["node_ids_sha256"] == digest
        assert f"Python matrix {worker}: Python {identity['version']}" in result.stdout
    assert evidence["collection_complete"] is True
    assert evidence["errors"] == []
    assert evidence["exitstatus"] == 0


def test_failed_test_remains_failed_in_evidence(run_pytest, tmp_path: Path) -> None:
    (tmp_path / "test_sample.py").write_text("def test_failure(): assert False\n")
    report = tmp_path / "failed.json"
    result = run_pytest("--python-evidence", str(report))
    assert result.returncode == 1
    evidence = json.loads(report.read_text())
    assert evidence["node_ids"] == ["test_sample.py::test_failure"]
    assert evidence["collection_complete"] is True
    assert evidence["exitstatus"] == 1


def test_collection_error_cannot_certify_complete_evidence(run_pytest, tmp_path: Path) -> None:
    (tmp_path / "test_sample.py").write_text("raise RuntimeError('broken collection')\n")
    report = tmp_path / "broken.json"
    result = run_pytest("--python-evidence", str(report))
    assert result.returncode != 0
    evidence = json.loads(report.read_text())
    assert evidence["collection_complete"] is False
    assert evidence["errors"]
    assert evidence["exitstatus"] != 0


def test_unwritable_evidence_fails_the_run(run_pytest, tmp_path: Path) -> None:
    blocker = tmp_path / "file-not-directory"
    blocker.touch()
    result = run_pytest("--python-evidence", str(blocker / "report.json"))
    assert result.returncode == 3
    assert "Cannot write Python matrix evidence" in result.stdout + result.stderr


def test_malformed_expected_version_is_usage_error(run_pytest) -> None:
    result = run_pytest("--expected-python", "python3.11")
    assert result.returncode == 4
    assert "must be a major.minor version" in result.stderr


def test_worker_lost_during_collection_cannot_certify_partial_evidence(run_pytest, tmp_path: Path) -> None:
    (tmp_path / "conftest.py").write_text(
        "import os\n"
        "def pytest_collection_modifyitems(session):\n"
        "    if hasattr(session.config, 'workerinput'): os._exit(17)\n"
    )
    report = tmp_path / "incomplete.json"
    result = run_pytest(
        "-p",
        "xdist.plugin",
        "-n",
        "1",
        "--max-worker-restart",
        "0",
        "--python-evidence",
        str(report),
    )
    assert result.returncode != 0
    evidence = json.loads(report.read_text())
    assert evidence["collection_complete"] is False
    assert "gw0 did not report its selected test identities" in evidence["errors"]
    assert evidence["exitstatus"] != 0
