"""Regression: a non-object JSONL line must not abort telemetry log reads.

Bug: ``read_cost_logs`` / ``read_audit_logs`` called ``record.get(...)`` immediately after
``json.loads``, assuming every line decodes to a dict. A valid-but-non-object line (``[]``, ``"x"``, ``1``) raised
``AttributeError`` -- NOT caught by the file-level ``except OSError`` (it subclasses ``Exception``, not ``OSError``), so
it escaped the reader and aborted the ENTIRE read, dropping every shard's records and crashing the caller (e.g.
``forge telemetry costs show`` / ``forge proxy audit show``). The contract is "skip malformed records," so one bad line must
not nuke the read.

Root cause / fix: guard with ``isinstance(record, dict)`` before ``.get``, mirroring
``src/forge/core/usage/ledger.py::read_usage_events``. Affected readers:

- ``src/forge/proxy/cost_logger.py::read_cost_logs``
- ``src/forge/proxy/audit_logger.py::read_audit_logs``
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from forge.core.paths import get_forge_home
from forge.proxy.audit_logger import log_audit_record, read_audit_logs
from forge.proxy.cost_logger import log_request_cost, read_cost_logs

pytestmark = pytest.mark.regression

_BAD_LINES = ["[]", '"x"', "1", "true", "null"]


def _shard(*subdir: str) -> Path:
    """Return the current-PID shard path under the isolated FORGE_HOME, parent created.

    ``log_request_cost()`` creates ``costs/requests`` itself, but the verb/audit valid
    records are hand-written, so the directory has to exist before the append.
    """
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    directory = get_forge_home().joinpath(*subdir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{month}_{os.getpid()}.jsonl"


def _append(path: Path, line: str) -> None:
    with path.open("a") as f:
        f.write(line + "\n")


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.parametrize("bad_line", _BAD_LINES)
def test_read_cost_logs_skips_non_object_line(bad_line: str) -> None:
    # Valid record via the real writer (proves a full schema'd record still loads).
    log_request_cost(
        proxy_id="p",
        model="m",
        tier="sonnet",
        input_tokens=1,
        output_tokens=1,
        cached_tokens=0,
        cost_micros=1000,
        latency_ms=1.0,
        failed=False,
        request_id="keep",
    )
    _append(_shard("telemetry", "downstream"), bad_line)

    # Before the fix this raised AttributeError instead of returning the valid record.
    records = read_cost_logs()

    assert [r.get("request_id") for r in records] == ["keep"]


@pytest.mark.parametrize("bad_line", _BAD_LINES)
def test_read_audit_logs_skips_non_object_line(bad_line: str) -> None:
    log_audit_record({"ts": _now_ts(), "record_type": "request", "request_id": "keep"})
    _append(_shard("telemetry", "downstream"), bad_line)

    records = read_audit_logs()

    assert [r.get("request_id") for r in records] == ["keep"]
