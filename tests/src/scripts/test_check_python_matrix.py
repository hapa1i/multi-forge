"""Cross-version CI must compare exact, successful worker collections."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/check-python-matrix.py"


@pytest.fixture
def evidence_root(tmp_path: Path) -> Path:
    for version in ("3.11", "3.13"):
        for suite in ("unit", "regression"):
            _write_evidence(tmp_path / f"python-{version}" / f"{suite}.json", version, [f"test_{suite}.py::test_a"])
    return tmp_path


def test_equal_multisets_produce_retained_interpreter_and_hash_summary(evidence_root: Path) -> None:
    ids = ["test_unit.py::test_b", "test_unit.py::test_a", "test_unit.py::test_a"]
    for version in ("3.11", "3.13"):
        _write_evidence(evidence_root / f"python-{version}/unit.json", version, ids if version == "3.11" else ids[::-1])
    output = evidence_root / "summary/result.json"
    result = _run(evidence_root, "--output", str(output))

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary == json.loads(output.read_text())
    assert summary["matched"] is True
    lanes = summary["suites"]["unit"]["lanes"]
    assert lanes["3.11"]["selected_count"] == lanes["3.13"]["selected_count"] == 3
    assert lanes["3.11"]["node_ids_sha256"] == lanes["3.13"]["node_ids_sha256"]
    assert lanes["3.11"]["workers"]["gw0"]["version"] == "3.11.17"
    assert lanes["3.13"]["controller"]["version"] == "3.13.17"


@pytest.mark.parametrize("other_ids", [["test_unit.py::test_b"], ["test_unit.py::test_a", "test_unit.py::test_a"]])
def test_different_ids_or_duplicate_counts_fail(evidence_root: Path, other_ids: list[str]) -> None:
    _write_evidence(evidence_root / "python-3.13/unit.json", "3.13", other_ids)
    result = _run(evidence_root)

    assert result.returncode == 1
    assert "unit selected tests differ" in result.stderr
    assert "only Python 3.13:" in result.stderr
    assert json.loads(result.stdout)["matched"] is False


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", 2, "unsupported evidence schema"),
        ("schema_version", True, "schema-versioned evidence object"),
        ("expected_python", "3.13", "expected_python must be 3.11"),
        ("exitstatus", 1, "pytest did not finish successfully"),
        ("exitstatus", False, "pytest did not finish successfully"),
        ("collection_complete", False, "evidence is incomplete"),
        ("errors", ["worker collection missing"], "evidence is incomplete"),
        ("controller", {"version": "3.13.11", "executable": "/python"}, "controller: expected Python 3.11"),
        ("controller", {"version": "3.11.bad", "executable": "/python"}, "controller: expected Python 3.11"),
        ("controller", {"version": "3.11.17", "executable": ""}, "controller: missing executable"),
        ("workers", {}, "must include xdist workers"),
        ("workers", {"gw0": None}, "worker gw0: missing interpreter identity"),
        ("workers", {"gw0": {"version": "3.13.11", "executable": "/python"}}, "worker gw0: expected Python 3.11"),
        ("node_ids", [], "nonempty list of test IDs"),
        ("node_ids", [42], "nonempty list of test IDs"),
    ],
)
def test_invalid_lane_evidence_is_rejected(evidence_root: Path, field: str, value: object, message: str) -> None:
    path = evidence_root / "python-3.11/unit.json"
    payload = json.loads(path.read_text())
    payload[field] = value
    path.write_text(json.dumps(payload))
    result = _run(evidence_root)

    assert result.returncode == 1
    assert message in result.stderr
    assert "python-3.11/unit.json" in result.stderr


@pytest.mark.parametrize(("field", "value"), [("collected_count", 2), ("node_ids_sha256", "wrong")])
def test_worker_selection_must_match_controller(evidence_root: Path, field: str, value: object) -> None:
    path = evidence_root / "python-3.11/unit.json"
    payload = json.loads(path.read_text())
    payload["workers"]["gw0"][field] = value
    path.write_text(json.dumps(payload))
    result = _run(evidence_root)

    assert result.returncode == 1
    assert f"worker gw0 {field} does not match node_ids" in result.stderr


@pytest.mark.parametrize("contents", [None, "{", "[]"])
def test_missing_or_malformed_evidence_cannot_leave_a_success_summary(
    evidence_root: Path, contents: str | None
) -> None:
    path = evidence_root / "python-3.13/regression.json"
    if contents is None:
        path.unlink()
    else:
        path.write_text(contents)
    output = evidence_root / "summary.json"
    output.write_text('{"matched": true}')
    result = _run(evidence_root, "--output", str(output))

    assert result.returncode == 1
    assert "python-3.13/regression.json" in result.stderr
    assert json.loads(output.read_text())["matched"] is False


def _run(evidence_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), str(evidence_root), *args], capture_output=True, text=True)


def _write_evidence(path: Path, version: str, ids: list[str]) -> None:
    identity = {"version": f"{version}.17", "executable": f"/venv-{version}/bin/python"}
    digest = hashlib.sha256(json.dumps(sorted(ids), ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    payload = {
        "schema_version": 1,
        "expected_python": version,
        "controller": identity,
        "workers": {"gw0": {**identity, "collected_count": len(ids), "node_ids_sha256": digest}},
        "node_ids": ids,
        "exitstatus": 0,
        "collection_complete": True,
        "errors": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
