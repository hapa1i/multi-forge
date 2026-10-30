#!/usr/bin/env python3
"""Require successful Python 3.11/3.13 suites with identical selected tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

PYTHON_VERSIONS = ("3.11", "3.13")
SUITES = ("unit", "regression")


def check(evidence_root: Path) -> dict[str, object]:
    """Validate all lane evidence and compare exact selected-test multisets."""
    suites: dict[str, object] = {}
    for suite in SUITES:
        records = {
            version: _read_evidence(evidence_root / f"python-{version}" / f"{suite}.json", version)
            for version in PYTHON_VERSIONS
        }
        first, second = (records[version][0] for version in PYTHON_VERSIONS)
        if first != second:
            first_only = Counter(first) - Counter(second)
            second_only = Counter(second) - Counter(first)
            raise ValueError(
                f"{suite} selected tests differ: "
                f"only Python 3.11: {_describe_difference(first_only)}; "
                f"only Python 3.13: {_describe_difference(second_only)}"
            )
        suites[suite] = {
            "matched": True,
            "lanes": {version: records[version][1] for version in PYTHON_VERSIONS},
        }
    return {"schema_version": 1, "matched": True, "suites": suites}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_root", type=Path, help="Directory containing python-3.11/ and python-3.13/")
    parser.add_argument("--output", type=Path, help="Also write the comparison summary to this JSON file")
    args = parser.parse_args()
    try:
        summary = check(args.evidence_root)
    except ValueError as error:
        summary = {"schema_version": 1, "matched": False, "error": str(error)}
        print(f"Python matrix evidence failed: {error}", file=sys.stderr)
    encoded = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        except OSError as error:
            print(f"Cannot write Python matrix summary: {error}", file=sys.stderr)
            return 1
    print(encoded, end="")
    return 0 if summary["matched"] else 1


def _read_evidence(path: Path, expected_python: str) -> tuple[list[str], dict[str, object]]:
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"{path}: cannot read evidence: {error}") from error
    if not isinstance(evidence, dict) or type(evidence.get("schema_version")) is not int:
        raise ValueError(f"{path}: expected a schema-versioned evidence object")
    if evidence["schema_version"] != 1:
        raise ValueError(f"{path}: unsupported evidence schema {evidence['schema_version']!r}")
    if evidence.get("expected_python") != expected_python:
        raise ValueError(f"{path}: expected_python must be {expected_python}")
    if type(evidence.get("exitstatus")) is not int or evidence["exitstatus"] != 0:
        raise ValueError(f"{path}: pytest did not finish successfully")
    if evidence.get("collection_complete") is not True or evidence.get("errors") != []:
        raise ValueError(f"{path}: interpreter/collection evidence is incomplete or reports errors")

    controller = _interpreter(evidence.get("controller"), expected_python, f"{path}: controller")
    node_ids = evidence.get("node_ids")
    if (
        not isinstance(node_ids, list)
        or not node_ids
        or any(not isinstance(item, str) or not item for item in node_ids)
    ):
        raise ValueError(f"{path}: node_ids must be a nonempty list of test IDs")
    node_ids = sorted(node_ids)
    digest = hashlib.sha256(json.dumps(node_ids, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    workers = evidence.get("workers")
    if not isinstance(workers, dict) or not workers:
        raise ValueError(f"{path}: full-suite evidence must include xdist workers")
    identities: dict[str, dict[str, str]] = {}
    for worker_id, worker in workers.items():
        if not isinstance(worker_id, str) or not worker_id:
            raise ValueError(f"{path}: worker IDs must be nonempty strings")
        identities[worker_id] = _interpreter(worker, expected_python, f"{path}: worker {worker_id}")
        if type(worker.get("collected_count")) is not int or worker["collected_count"] != len(node_ids):
            raise ValueError(f"{path}: worker {worker_id} collected_count does not match node_ids")
        if worker.get("node_ids_sha256") != digest:
            raise ValueError(f"{path}: worker {worker_id} node_ids_sha256 does not match node_ids")
    return node_ids, {
        "selected_count": len(node_ids),
        "node_ids_sha256": digest,
        "controller": controller,
        "workers": identities,
    }


def _interpreter(value: object, expected_python: str, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{label}: missing interpreter identity")
    version, executable = value.get("version"), value.get("executable")
    if (
        not isinstance(version, str)
        or len(version.split(".")) != 3
        or not all(part.isdecimal() for part in version.split("."))
        or version.split(".")[:2] != expected_python.split(".")
    ):
        raise ValueError(f"{label}: expected Python {expected_python}, got {version!r}")
    if not isinstance(executable, str) or not executable.strip():
        raise ValueError(f"{label}: missing executable")
    return {"version": version, "executable": executable}


def _describe_difference(counts: Counter[str]) -> str:
    examples = [f"{node_id} ({count} occurrence(s))" for node_id, count in sorted(counts.items())[:10]]
    return f"{sum(counts.values())} case(s) {examples}"


if __name__ == "__main__":
    raise SystemExit(main())
