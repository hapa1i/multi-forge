"""Opt-in interpreter and collection evidence for the supported-Python CI lanes."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
from pathlib import Path
from typing import Any

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("Python matrix evidence")
    group.addoption("--expected-python", help="Require this Python major.minor in pytest and every xdist worker")
    group.addoption("--python-evidence", type=Path, help="Write interpreter and selected-test evidence as JSON")


def pytest_configure(config: pytest.Config) -> None:
    expected = config.getoption("expected_python")
    output = config.getoption("python_evidence")
    if (expected is None and output is None) or hasattr(config, "workerinput"):
        return
    if expected is not None and re.fullmatch(r"[0-9]+\.[0-9]+", expected) is None:
        raise pytest.UsageError("--expected-python must be a major.minor version, such as 3.11")
    config.pluginmanager.register(PythonMatrixEvidence(config, expected, output), "forge-python-matrix-evidence")


class PythonMatrixEvidence:
    def __init__(self, config: pytest.Config, expected: str | None, output: Path | None) -> None:
        self.config = config
        self.expected = expected
        self.output = output
        self.controller = {"version": platform.python_version(), "executable": sys.executable}
        self.workers: dict[str, dict[str, Any]] = {}
        self.configured_workers: set[str] = set()
        self.collections: dict[str, list[str]] = {}
        self.serial_ids: list[str] | None = None
        self.errors: list[str] = []

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        self._log("controller", self.controller)
        mismatch = self._version_error("controller", sys.version_info[:2])
        if mismatch:
            self.errors.append(mismatch)
        # Replace a previous report before collection, so an interrupted run cannot reuse success evidence.
        self._write(pytest.ExitCode.USAGE_ERROR if mismatch else pytest.ExitCode.INTERRUPTED)
        if mismatch:
            raise pytest.UsageError(mismatch)

    @pytest.hookimpl(optionalhook=True)
    def pytest_configure_node(self, node: Any) -> None:
        self.configured_workers.add(node.gateway.id)

    @pytest.hookimpl(optionalhook=True)
    def pytest_testnodeready(self, node: Any) -> None:
        worker = node.gateway.id
        info = node.workerinfo
        version = info.get("version_info")
        executable = info.get("executable")
        if (
            not isinstance(version, (tuple, list))
            or len(version) < 3
            or any(type(part) is not int for part in version[:3])
            or not isinstance(executable, str)
            or not executable
        ):
            self._stop(f"{worker} did not report a valid Python version and executable")
        identity = {"version": ".".join(str(part) for part in version[:3]), "executable": executable}
        self.workers[worker] = identity
        self._log(worker, identity)
        mismatch = self._version_error(worker, version[:2])
        if mismatch:
            self._stop(mismatch)

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node: Any, ids: list[str]) -> None:
        worker = node.gateway.id
        selected = sorted(ids)
        self.collections[worker] = selected
        if worker in self.workers:
            self.workers[worker].update(collected_count=len(selected), node_ids_sha256=_identity_hash(selected))
        if any(selected != other for other in self.collections.values()):
            self._stop(f"{worker} selected different test identities from another worker")

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self.errors.append(f"collection failed for {report.nodeid}")

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        if not self.configured_workers:
            self.serial_ids = sorted(item.nodeid for item in session.items)

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self.configured_workers:
            for worker in sorted(self.configured_workers):
                if worker not in self.workers:
                    self.errors.append(f"{worker} did not report its interpreter")
                if worker not in self.collections:
                    self.errors.append(f"{worker} did not report its selected test identities")
        elif self.serial_ids is None:
            self.errors.append("controller did not finish test collection")
        if self.errors and exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.INTERNAL_ERROR
        self._write(session.exitstatus)
        for error in self.errors:
            self._line(f"Python matrix evidence error: {error}")

    def _version_error(self, owner: str, version: tuple[int, ...] | list[int]) -> str | None:
        actual = ".".join(str(part) for part in version[:2])
        if self.expected is not None and actual != self.expected:
            return f"{owner} uses Python {actual}; expected Python {self.expected}"
        return None

    def _stop(self, message: str) -> None:
        self.errors.append(message)
        pytest.exit(message, returncode=pytest.ExitCode.USAGE_ERROR)

    def _log(self, owner: str, identity: dict[str, Any]) -> None:
        self._line(f"Python matrix {owner}: Python {identity['version']} ({identity['executable']})")

    def _line(self, message: str) -> None:
        terminal = self.config.pluginmanager.get_plugin("terminalreporter")
        if terminal is not None:
            terminal.write_line(message)

    def _write(self, exitstatus: int) -> None:
        if self.output is None:
            return
        node_ids = next(iter(self.collections.values()), self.serial_ids or [])
        complete = (
            self.configured_workers == self.workers.keys() == self.collections.keys()
            if self.configured_workers
            else self.serial_ids is not None
        )
        report = {
            "schema_version": 1,
            "expected_python": self.expected,
            "controller": self.controller,
            "workers": self.workers,
            "node_ids": node_ids,
            "collection_complete": complete and not self.errors,
            "errors": self.errors,
            "exitstatus": int(exitstatus),
        }
        try:
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        except OSError as exc:
            pytest.exit(f"Cannot write Python matrix evidence to {self.output}: {exc}", returncode=3)


def _identity_hash(node_ids: list[str]) -> str:
    payload = json.dumps(node_ids, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
